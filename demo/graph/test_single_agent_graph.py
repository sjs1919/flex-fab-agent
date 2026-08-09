"""单 Agent 状态图集成测试（mock call_llm + 假 registry，不发起真实 LLM）。"""
import json

from demo.graph.single_agent_graph import build_single_agent_graph
from demo.graph.state import AgentState


class FakeRegistry:
    """最小 registry：register 两个工具，execute 返回固定结果。"""

    def __init__(self):
        self.schemas = {
            "query_orders": {"server": "order_server"},
            "query_inventory": {"server": "resource_server"},
        }

    def get_tool_defs(self):
        return [{"type": "function", "function": {"name": n, "parameters": {}}}
                for n in self.schemas]

    def get_schema(self, name):
        if name in self.schemas:
            return type("S", (), {"server": self.schemas[name]["server"]})()
        return None

    def execute(self, name, arguments):
        return f"{name} 返回 ORD003 深圳精密"


class FakeResponse:
    """模拟 OpenAI 响应，可配置 tool_calls 或纯文本。"""

    def __init__(self, content=None, tool_calls=None):
        self.choices = [type("C", (), {"message": type("M", (), {
            "content": content,
            "tool_calls": tool_calls,
        })()})()]


def _make_tool_call(name, args="{}"):
    return [
        type("TC", (), {
            "id": f"call_{name}",
            "type": "function",
            "function": type("F", (), {"name": name, "arguments": args})(),
        })()
    ]


def _disable_compression(monkeypatch):
    """把压缩阈值设极大，避免测试中消息膨胀触发压缩改变末条消息结构。"""
    from demo.graph import context_compressor
    monkeypatch.setattr(context_compressor, "MAX_CHARS", 10 ** 9)


def test_graph_invokes_tool_and_generates_answer(monkeypatch):
    """图应执行 LLM -> 调工具 -> 生成答案 完整链路。"""
    from demo.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)

    # 先调订单 + 库存两个工具（满足 evaluate 的 order+resource 要求），再生成答案
    responses = [
        FakeResponse(tool_calls=_make_tool_call("query_orders")),
        FakeResponse(tool_calls=_make_tool_call("query_inventory")),
        FakeResponse(content="ORD003 今天优先排产"),
    ]

    def fake_call_llm(messages, tools=None, **kwargs):
        if responses:
            return responses.pop(0)
        return FakeResponse(content="兜底答案 ORD003")

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)

    app = build_single_agent_graph(FakeRegistry(), checkpointer=None)
    result = app.invoke({
        "messages": [{"role": "user", "content": "今天先做哪些订单？"}],
        "tool_results": [],
        "iteration": 0,
        "final_answer": "",
    })

    assert "ORD003" in result["final_answer"]
    assert len(result["tool_results"]) == 2
    tools_used = {tr["tool"] for tr in result["tool_results"]}
    assert tools_used == {"query_orders", "query_inventory"}


def test_graph_five_round_safety_valve(monkeypatch):
    """5 轮安全阀：iteration>=5 强制结束，不无限循环。"""
    from demo.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)

    def fake_call_llm(messages, tools=None, **kwargs):
        # 永远调工具 -> 会一直循环
        return FakeResponse(tool_calls=_make_tool_call("query_orders"))

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)

    app = build_single_agent_graph(FakeRegistry(), checkpointer=None)
    result = app.invoke({
        "messages": [{"role": "user", "content": "q"}],
        "tool_results": [],
        "iteration": 0,
        "final_answer": "",
    })

    # 5 轮后强制结束，生成了兜底答案
    assert result["iteration"] >= 5 or result["final_answer"] != ""
    # 不抛异常即通过（无死循环）


def test_graph_no_tool_calls_generates_direct_answer(monkeypatch):
    """LLM 直接返回文本（不调工具）-> 该文本作为答案。"""
    from demo.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)

    responses = iter([
        FakeResponse(content="直接回答，无需工具"),  # 第一轮无 tool_calls
    ])

    def fake_call_llm(messages, tools=None, **kwargs):
        return next(responses)

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)

    app = build_single_agent_graph(FakeRegistry(), checkpointer=None)
    result = app.invoke({
        "messages": [{"role": "user", "content": "q"}],
        "tool_results": [],
        "iteration": 0,
        "final_answer": "",
    })
    assert result["final_answer"] == "直接回答，无需工具"


def test_pure_text_round_increments_iteration(monkeypatch):
    """纯文本轮（LLM 返回文本不调工具）也应递增 iteration。

    坑 22：select_and_execute 的 `if not msg.tool_calls: return state` 不递增
    iteration -> iteration 卡死 -> needs_more 永真 -> 死循环。
    修复后纯文本轮也要 +1，保证安全阀生效。
    """
    from demo.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)

    # 构造：LLM 一直返回纯文本，evaluate 会设 needs_more，应靠 iteration 递增终止
    responses = iter([
        FakeResponse(content="数据不足，无法回答"),  # 纯文本轮 1
        FakeResponse(content="数据不足，无法回答"),  # 纯文本轮 2
        FakeResponse(content="数据不足，无法回答"),  # 纯文本轮 3
        FakeResponse(content="数据不足，无法回答"),  # 纯文本轮 4
        FakeResponse(content="数据不足，无法回答"),  # 纯文本轮 5
        FakeResponse(content="兜底答案"),  # 第 6 次（iteration>=5 强制结束）
    ])

    def fake_call_llm(messages, tools=None, **kwargs):
        return next(responses)

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)

    app = build_single_agent_graph(FakeRegistry(), checkpointer=None)
    result = app.invoke({
        "messages": [{"role": "user", "content": "q"}],
        "tool_results": [],
        "iteration": 0,
        "final_answer": "",
    })

    # 纯文本轮递增后，iteration 会推进（needs_more 在 iteration>=4 失效 -> 生成答案），
    # 而非卡死在 0（坑 22 修复前 iteration 永远不涨）
    assert result["iteration"] >= 1, f"纯文本轮应递增 iteration，实际 {result['iteration']}"
    # 有最终答案（非死循环）
    assert result["final_answer"] != ""


def test_evaluate_loop_detection_breaks_cycle(monkeypatch):
    """同一工具结果重复出现 >=N 次 -> evaluate 检测循环并强制结束（方案3）。

    坑 22：RAG 场景 LLM 反复调同一 search_knowledge_base，数据永远不足，
    needs_more 永真 -> 死循环。方案 3 在 evaluate 检测同一 tool 重复调用
    过多时，清 needs_more 并置 ready_for_answer，强制生成答案。
    """
    from demo.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)

    # LLM 永远调同一工具（query_orders），evaluate 会检测到重复
    def fake_call_llm(messages, tools=None, **kwargs):
        return FakeResponse(tool_calls=_make_tool_call("query_orders"))

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)

    app = build_single_agent_graph(FakeRegistry(), checkpointer=None)
    result = app.invoke({
        "messages": [{"role": "user", "content": "q"}],
        "tool_results": [],
        "iteration": 0,
        "final_answer": "",
    })

    # 循环检测触发：needs_more 被清除（不再死循环），有最终答案
    assert result["needs_more"] is not True, "循环检测应清除 needs_more"
    assert result["final_answer"] != "", "循环检测后应有最终答案"
