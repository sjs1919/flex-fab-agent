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


def test_graph_tool_loop_task_type_simple(monkeypatch):
    """工具轮：无排产复杂工具 -> task_type='simple'（B3 路由）。"""
    from demo.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)
    seen: list = []

    def fake_call_llm(messages, tools=None, **kwargs):
        seen.append(kwargs.get("task_type"))
        return FakeResponse(content="简单回答")  # 直接文本作答，无工具调用

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)
    app = build_single_agent_graph(FakeRegistry(), checkpointer=None)
    app.invoke({
        "messages": [{"role": "user", "content": "有哪些订单？"}],
        "tool_results": [],
        "iteration": 0,
        "final_answer": "",
    })
    assert seen and seen[0] == "simple"


def test_graph_tool_loop_task_type_complex(monkeypatch):
    """工具轮：注册表含排产复杂工具（query_ctp）-> task_type='complex'。"""
    from demo.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)

    class FakeComplexRegistry(FakeRegistry):
        def __init__(self):
            super().__init__()
            self.schemas["query_ctp"] = {"server": "scheduler_server"}

    seen: list = []

    def fake_call_llm(messages, tools=None, **kwargs):
        seen.append(kwargs.get("task_type"))
        return FakeResponse(content="排产建议")  # 直接文本作答

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)
    app = build_single_agent_graph(FakeComplexRegistry(), checkpointer=None)
    app.invoke({
        "messages": [{"role": "user", "content": "CTP 什么时候？"}],
        "tool_results": [],
        "iteration": 0,
        "final_answer": "",
    })
    assert seen and seen[0] == "complex"


class FakeScheduleRegistry(FakeRegistry):
    """FakeRegistry + query_schedule（排产上下文工具，仅此一个，无订单工具）。"""

    def __init__(self):
        super().__init__()
        self.schemas["query_schedule"] = {"server": "schedule_server"}


def _invoke_schedule_flow(monkeypatch):
    """走完整流程：第一轮调 query_schedule，第二轮直接作答。返回 (result, prompts)。"""
    from demo.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)
    prompts: list = []
    responses = [
        FakeResponse(tool_calls=_make_tool_call("query_schedule")),
        FakeResponse(content="排产建议：ORD003 优先，依据排产版本 12"),
    ]

    def fake_call_llm(messages, tools=None, **kwargs):
        if tools is None:  # generate_answer 综合指令（无工具 schema）
            prompts.append(messages[-1]["content"])
        return responses.pop(0) if responses else FakeResponse(content="兜底答案")

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)
    app = build_single_agent_graph(FakeScheduleRegistry(), checkpointer=None)
    result = app.invoke({
        "messages": [{"role": "user", "content": "当前排产什么进度？"}],
        "tool_results": [],
        "iteration": 0,
        "final_answer": "",
    })
    return result, prompts


def test_graph_schedule_context_marks_data_sufficient(monkeypatch):
    """仅调 query_schedule 未调 query_orders -> evaluate 判定数据充足（C2）。"""
    result, _ = _invoke_schedule_flow(monkeypatch)
    assert "排产上下文" in result.get("evaluation_notes", "")
    assert result.get("ready_for_answer") is True
    assert "ORD003" in result["final_answer"]


def test_graph_generate_answer_injects_schedule_citation(monkeypatch):
    """generate_answer 综合指令含排产引用提示（版本号/延期清单）。"""
    _, prompts = _invoke_schedule_flow(monkeypatch)
    assert prompts, "应有一次 generate_answer 的 LLM 调用"
    assert "版本号" in prompts[-1] and "延期清单" in prompts[-1]


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


# ---- 缓存投毒根因修复：DSML 标记文本误作答案 ----

_MARKUP = ('<|tool_calls|>\n<invoke name="query_orders">\n'
           '{"status": "pending"}\n</invoke>')


def test_tool_markup_content_retries_not_answered(monkeypatch):
    """坑（缓存投毒）：LLM 把工具调用意图写成 DSML 标记文本且 tool_calls 为空 ->
    不得作为最终答案；应注入纠错提示重试，第二轮干净文本才作答案。"""
    from demo.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)

    responses = iter([
        FakeResponse(content=_MARKUP),                # 第一轮：DSML 标记文本，无 tool_calls
        FakeResponse(content="ORD003 今天优先排产"),  # 第二轮：干净文本答案
    ])
    seen: list = []

    def fake_call_llm(messages, tools=None, **kwargs):
        seen.append(messages[-1]["content"])
        return next(responses)

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)

    app = build_single_agent_graph(FakeRegistry(), checkpointer=None)
    result = app.invoke({
        "messages": [{"role": "user", "content": "今天先做哪些订单？"}],
        "tool_results": [],
        "iteration": 0,
        "final_answer": "",
    })

    assert result["final_answer"] == "ORD003 今天优先排产"
    assert "tool_calls" not in result["final_answer"]
    assert any("未解析的工具调用标记" in m for m in seen), "应注入纠错提示后重试"
    # select_and_execute 共 2 次 LLM 调用：首轮带用户问题、重试轮带纠错提示
    assert len(seen) == 2, f"应恰好重试一次，实际 {len(seen)} 轮"


def test_tool_markup_persistent_bounded_by_iteration(monkeypatch):
    """坑（缓存投毒）：LLM 持续输出 DSML 标记 -> 安全阀（iteration>=5）强制结束，
    不产出含标记的答案、不死循环。"""
    from demo.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)

    def fake_call_llm(messages, tools=None, **kwargs):
        return FakeResponse(content=_MARKUP)

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)

    app = build_single_agent_graph(FakeRegistry(), checkpointer=None)
    result = app.invoke({
        "messages": [{"role": "user", "content": "q"}],
        "tool_results": [],
        "iteration": 0,
        "final_answer": "",
    })

    assert result["iteration"] >= 3, f"标记轮应多次重试后由安全阀收口，实际 {result['iteration']}"
    assert "<invoke" not in result["final_answer"], "标记文本不得进入最终答案"
    assert result["final_answer"] != ""


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


# ---- T5a.11：generate_answer 延期解释增强（结构化注入） ----

class FakeDelayRegistry(FakeRegistry):
    """FakeRegistry + query_load_assessment（排产上下文工具）。"""

    def __init__(self):
        super().__init__()
        self.schemas["query_load_assessment"] = {"server": "schedule_server"}


_DELAY_RESULT = (
    "📊 产能负载评估（生成 2026-08-23 08:00，T 窗口 48h）\n"
    "2️⃣ 各订单预计完成（满负荷粗算）：\n"
    "| 订单 | 工艺 | 交期 | 预计完成 | 状态 |\n"
    "| ORD001 | SLA | 2026-09-10 | 2026-09-12 | ⚠️ 延期 2 天 |\n"
    "3️⃣ 满负荷超期预警：\n"
    "| 订单 | 延期 |\n| ORD001 | 2 天 |\n"
)


def _invoke_delay_flow(monkeypatch):
    """seeded 含延期清单的 query_load_assessment 结果 -> 捕获 generate_answer summary_prompt。"""
    from demo.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)
    prompts: list = []
    responses = [
        FakeResponse(tool_calls=_make_tool_call("query_load_assessment")),
        FakeResponse(content="ORD001 会延期 2 天，建议调整排产"),
    ]

    def fake_call_llm(messages, tools=None, **kwargs):
        if tools is None:  # generate_answer 综合指令（无工具 schema）
            prompts.append(messages[-1]["content"])
        return responses.pop(0) if responses else FakeResponse(content="兜底答案")

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)
    app = build_single_agent_graph(FakeDelayRegistry(), checkpointer=None)
    app.invoke({
        "messages": [{"role": "user", "content": "哪些订单会延期？"}],
        "tool_results": [{"tool": "query_load_assessment", "arguments": {},
                          "result": _DELAY_RESULT}],
        "iteration": 0,
        "final_answer": "",
    })
    return prompts


def test_generate_answer_injects_structured_delay(monkeypatch):
    """T5a.11：排产结果含延期清单 -> summary_prompt 注入结构化延期数据+逐单解释指令。"""
    prompts = _invoke_delay_flow(monkeypatch)
    assert prompts, "应有一次 generate_answer 的 LLM 调用"
    summary = prompts[-1]
    assert "结构化延期数据" in summary
    assert "延期 2 天" in summary          # 延期清单+天数注入
    assert "逐单解释" in summary and "为什么" in summary  # 逐单解释指令


def test_generate_answer_no_schedule_ctx_unchanged(monkeypatch):
    """T5a.11：无排产上下文 -> 不注入结构化延期数据（与 M4b 行为一致）。"""
    from demo.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)
    prompts: list = []
    responses = [
        FakeResponse(tool_calls=_make_tool_call("query_orders")),
        FakeResponse(content="订单汇总"),
    ]

    def fake_call_llm(messages, tools=None, **kwargs):
        if tools is None:
            prompts.append(messages[-1]["content"])
        return responses.pop(0) if responses else FakeResponse(content="兜底答案")

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)
    app = build_single_agent_graph(FakeRegistry(), checkpointer=None)
    app.invoke({
        "messages": [{"role": "user", "content": "有哪些订单？"}],
        "tool_results": [{"tool": "query_orders", "arguments": {},
                          "result": "ORD001 A 级 交期 2026-09-10"}],
        "iteration": 1,
        "ready_for_answer": True,
        "final_answer": "",
    })
    assert prompts, "应有一次 generate_answer 的 LLM 调用"
    summary = prompts[-1]
    assert "结构化延期数据" not in summary    # 不注入结构化块
    assert "排产依据" in summary               # M4b 原引用提示保留
