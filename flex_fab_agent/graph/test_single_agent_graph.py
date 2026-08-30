"""单 Agent 状态图集成测试（mock call_llm + 假 registry，不发起真实 LLM）。"""
import json

from flex_fab_agent.graph.single_agent_graph import build_single_agent_graph
from flex_fab_agent.graph.state import AgentState


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
            # 2026-08-29：对齐生产 ToolSchema 契约（select_and_execute 判断 read_only）
            return type("S", (), {
                "server": self.schemas[name]["server"], "read_only": True})()
        return None

    def execute(self, name, arguments, token=None):
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
    from flex_fab_agent.graph import context_compressor
    monkeypatch.setattr(context_compressor, "MAX_CHARS", 10 ** 9)


def test_graph_tool_loop_task_type_simple(monkeypatch):
    """工具轮：无排产复杂工具 -> task_type='simple'（B3 路由）。"""
    from flex_fab_agent.graph import single_agent_graph as sag
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
    from flex_fab_agent.graph import single_agent_graph as sag
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
    from flex_fab_agent.graph import single_agent_graph as sag
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
    from flex_fab_agent.graph import single_agent_graph as sag
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
    from flex_fab_agent.graph import single_agent_graph as sag
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
    from flex_fab_agent.graph import single_agent_graph as sag
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
    from flex_fab_agent.graph import single_agent_graph as sag
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


def test_tool_markup_fullwidth_dsml_detected():
    """全角竖线 + ||DSML|| 双竖线包裹变体也要被识别为标记文本（缓存投毒纵深防御）。

    2026-08-24 实测：LLM 输出 `<｜DSML｜｜tool_calls>`（U+FF5C 全角竖线）
    与 `<||DSML||tool_calls>`（双竖线包裹）两种变体，旧 marker 表均漏检 -> 污染缓存。
    """
    from flex_fab_agent.graph import single_agent_graph as sag
    fw = chr(0xFF5C)  # ｜
    fullwidth = f"<{fw}{fw}DSML{fw}{fw}tool_calls>\n<{fw}{fw}DSML{fw}{fw}invoke name=\"query_orders\">"
    dsml = "<||DSML||tool_calls>\n<||DSML||invoke name=\"query_orders\">"
    assert sag._looks_like_tool_markup(fullwidth), "全角竖线变体应被识别"
    assert sag._looks_like_tool_markup(dsml), "||DSML|| 包裹变体应被识别"
    assert not sag._looks_like_tool_markup("有哪些订单在排队？")
    assert sag._sanitize_answer(fullwidth) == sag._GRACEFUL_FALLBACK


def test_tool_markup_persistent_bounded_by_iteration(monkeypatch):
    """坑（缓存投毒）：LLM 持续输出 DSML 标记 -> 安全阀（iteration>=5）强制结束，
    不产出含标记的答案、不死循环。"""
    from flex_fab_agent.graph import single_agent_graph as sag
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
    from flex_fab_agent.graph import single_agent_graph as sag
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
    from flex_fab_agent.graph import single_agent_graph as sag
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
    from flex_fab_agent.graph import single_agent_graph as sag
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
    from flex_fab_agent.graph import single_agent_graph as sag
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


def test_generate_answer_markup_retries_not_fallback(monkeypatch):
    """坑（2026-08-26 复现）：汇总步（generate_answer）模型偶发输出 DSML 标记文本
    -> 应注入纠错提示重试后产出干净答案，而不是直接降级为死胡同兜底话术。

    复现 trace：设备/订单/排产数据全部拿到，最后汇总步模型输出标记文本，
    用户只看到「抱歉，本次回答生成异常」。select_and_execute 对标记文本会重试，
    generate_answer 此前不重试——本测试锁住该行为。
    """
    from flex_fab_agent.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)
    responses = iter([
        FakeResponse(tool_calls=_make_tool_call("query_schedule")),  # 选工具轮
        FakeResponse(content=_MARKUP),                              # 汇总步第1次：标记文本
        FakeResponse(content="设备均空闲（7/7），可承接新订单。"),     # 汇总步第2次：干净答案
    ])
    all_messages: list = []

    def fake_call_llm(messages, tools=None, **kwargs):
        all_messages.append(messages)
        return next(responses)

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)

    app = build_single_agent_graph(FakeScheduleRegistry(), checkpointer=None)
    result = app.invoke({
        "messages": [{"role": "user", "content": "帮我检查一下设备的空闲情况"}],
        "tool_results": [],
        "iteration": 0,
        "final_answer": "",
    })

    assert result["final_answer"] == "设备均空闲（7/7），可承接新订单。", \
        f"应重试后产出干净答案，实际: {result['final_answer']!r}"
    assert result["final_answer"] != sag._GRACEFUL_FALLBACK, "不得降级为死胡同兜底话术"
    # 恰好一次重试：工具轮 1 次 + 汇总步 2 次（标记文本 + 干净答案）
    assert len(all_messages) == 3, f"应恰好重试一次，实际 {len(all_messages)} 轮 LLM 调用"
    assert any(any("未解析的工具调用标记" in (m.get("content") or "") for m in msgs)
               for msgs in all_messages), "汇总步应注入纠错提示后重试"


# ---- 2026-08-27 修复：循环守卫误判 + 缓存投毒（状态筛选空结果 / 不同参数探索 / 内部诊断泄漏）----


class FakeEmptyRegistry(FakeRegistry):
    """query_orders 返回「未找到匹配的订单。」（模拟该筛选无匹配订单）。"""

    def execute(self, name, arguments, token=None):
        if name == "query_orders":
            return "未找到匹配的订单。"
        return super().execute(name, arguments, token=token)


def test_status_empty_result_is_terminal_answer(monkeypatch):
    """坑（循环守卫误判 + 缓存投毒）：query_orders(status=完成) 干净返回「未找到」
    = 该状态无订单，应直接据此作答，不再追问其它资源数据、不触发循环守卫原始 dump。

    根因回归：2026-08-27「有没有订单已经打印完成？」→ LLM 3 次 query_orders
    （不同 status）被全局计数误判为循环 → 原始 dump 进语义缓存 → 重问命中垃圾
    （judge 相关度 0 / faithfulness 0，trace 5ac4a01cd16246e1）。
    """
    from flex_fab_agent.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)
    responses = iter([
        FakeResponse(tool_calls=_make_tool_call("query_orders", '{"status": "完成"}')),
        FakeResponse(content="当前没有打印完成的订单。"),
    ])

    def fake_call_llm(messages, tools=None, **kwargs):
        return next(responses)

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)

    app = build_single_agent_graph(FakeEmptyRegistry(), checkpointer=None)
    result = app.invoke({
        "messages": [{"role": "user", "content": "有没有订单已经打印完成？"}],
        "tool_results": [],
        "iteration": 0,
        "final_answer": "",
    })

    assert result["final_answer"] == "当前没有打印完成的订单。", \
        f"筛选空结果应直接作答，实际: {result['final_answer']!r}"
    assert len(result["tool_results"]) == 1, "空结果即答案，不应继续追问更多工具"
    assert "检测到重复检索" not in result["final_answer"]


def test_loop_guard_distinct_args_not_loop(monkeypatch):
    """坑（循环守卫误判）：同一工具 query_orders 但参数不同（不同 status 的合理探索）
    不得判定为循环。旧实现 Counter 全局计数 3 次即触发 → 原始 dump 截断干净答案；
    新实现按（工具+参数）连续分组，参数不同不计数。"""
    from flex_fab_agent.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)
    responses = iter([
        FakeResponse(tool_calls=_make_tool_call("query_orders", '{"status": "待排队"}')),
        FakeResponse(tool_calls=_make_tool_call("query_orders", '{"status": "已审核"}')),
        FakeResponse(tool_calls=_make_tool_call("query_orders", '{"status": "打印中"}')),
        FakeResponse(content="订单汇总"),
    ])

    def fake_call_llm(messages, tools=None, **kwargs):
        return next(responses)

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)

    app = build_single_agent_graph(FakeRegistry(), checkpointer=None)
    result = app.invoke({
        "messages": [{"role": "user", "content": "有哪些订单？"}],
        "tool_results": [],
        "iteration": 0,
        "final_answer": "",
    })

    assert result["final_answer"] == "订单汇总", \
        "不同参数探索不应被误判为循环，干净答案应保留"
    assert not result["final_answer"].startswith(sag.LOOP_GUARD_FALLBACK_PREFIX)


def test_loop_guard_fallback_no_internal_diagnostic(monkeypatch):
    """坑（内部诊断泄漏）：循环守卫兜底文案不得包含「检测到重复检索」/「停止继续查询」
    等内部诊断消息（此前直接拼进 final_answer 透传给用户/缓存）。"""
    from flex_fab_agent.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)

    def fake_call_llm(messages, tools=None, **kwargs):
        return FakeResponse(tool_calls=_make_tool_call("query_orders", "{}"))

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)

    app = build_single_agent_graph(FakeRegistry(), checkpointer=None)
    result = app.invoke({
        "messages": [{"role": "user", "content": "q"}],
        "tool_results": [],
        "iteration": 0,
        "final_answer": "",
    })

    assert result["final_answer"].startswith(sag.LOOP_GUARD_FALLBACK_PREFIX), \
        f"循环守卫应产出 LOOP_GUARD_FALLBACK_PREFIX 兜底，实际: {result['final_answer']!r}"
    assert "检测到重复检索" not in result["final_answer"], "内部诊断不得泄漏给用户"
    assert "停止继续查询" not in result["final_answer"]


# ---- 2026-08-29 修复：单轮同工具多次调用，tool 消息结果错位 ----

def test_multi_same_tool_calls_map_results_by_call_id(monkeypatch):
    """坑（2026-08-29 复现）：单轮 LLM 同时调 3 次 query_orders（不同 status）时，
    旧实现按工具名 matching[-1] 把最后一个结果（「完成→未找到」）塞给全部 3 条 tool
    消息，汇总步 LLM 误读「待排队也空」→ 把 20 条待排队订单吞掉、答「三状态均无记录」。
    修复后按 tool_call 一一对应注入，各 tool 消息内容 = 各自执行结果。"""
    from flex_fab_agent.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)

    class ArgAwareRegistry(FakeRegistry):
        """query_orders 按 status 参数返回不同结果。"""

        def execute(self, name, arguments, token=None):
            if name == "query_orders":
                if arguments.get("status") == "待排队":
                    return "共 20 条订单：ORD001 深圳精密（待排队）"
                return "未找到匹配的订单。"
            return super().execute(name, arguments, token=token)

    # 单轮返回 3 个 query_orders tool_calls（不同 status 参数，id 各不同）
    def _make_calls():
        calls = []
        for sid, status in [("c1", "待排队"), ("c2", "打印中"), ("c3", "完成")]:
            calls.append(type("TC", (), {
                "id": sid,
                "type": "function",
                "function": type("F", (), {
                    "name": "query_orders",
                    "arguments": json.dumps({"status": status}, ensure_ascii=False),
                })(),
            })())
        return calls

    captured_tool_msgs: list = []
    responses = iter([
        FakeResponse(tool_calls=_make_calls()),              # 第一轮：3× query_orders
        FakeResponse(content="待排队 20 条，其余无。"),        # 汇总步
    ])

    def fake_call_llm(messages, tools=None, **kwargs):
        if tools is None:  # generate_answer 综合指令（无工具 schema）
            captured_tool_msgs.extend(
                m["content"] for m in messages if m.get("role") == "tool"
            )
        return next(responses)

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)
    app = build_single_agent_graph(ArgAwareRegistry(), checkpointer=None)
    result = app.invoke({
        "messages": [{"role": "user", "content": "查询待排队、打印中、完成订单列表"}],
        "tool_results": [],
        "iteration": 0,
        "final_answer": "",
    })

    # 3 条 tool 消息，各自内容对应各自结果（而非全部=最后一个「未找到」）
    assert len(captured_tool_msgs) == 3, \
        f"应注入 3 条 tool 消息，实际 {len(captured_tool_msgs)}"
    assert "共 20 条订单" in captured_tool_msgs[0], "待排队结果应保留 20 条订单"
    assert "共 20 条订单" not in captured_tool_msgs[1], "打印中结果不得误带待排队内容"
    assert "共 20 条订单" not in captured_tool_msgs[2], "完成结果不得误带待排队内容"
    assert result["final_answer"] == "待排队 20 条，其余无。"


# ---- 2026-08-30 修复：纯资源查询 LLM 已答即收尾（has_order 硬要求误拉回）----

class FakeResourceRegistry(FakeRegistry):
    """仅资源类工具（query_machine_load），无订单工具——模拟「查空闲设备」场景。"""

    def __init__(self):
        self.schemas = {"query_machine_load": {"server": "resource_server"}}


def test_pure_resource_query_clean_answer_terminates(monkeypatch):
    """坑（2026-08-30 复现，trace 372ae82d）：纯资源查询「帮我查一下空闲的设备」，
    LLM 决策轮调 query_machine_load 拿到空闲表，答案轮已给干净文本答案时，
    **不得被 evaluate 的 has_order 硬要求（needs_more）拉回继续工具轮**——
    否则正确设备列表被后续反问话术（「需要我帮您查看待排产的订单…」）覆盖。
    修复后：LLM 已答 + 有工具结果 -> 直接 ready_for_answer，答案轮即收尾。"""
    from flex_fab_agent.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)
    calls: list = []
    responses = [
        FakeResponse(tool_calls=_make_tool_call("query_machine_load")),  # 决策轮
        FakeResponse(content="当前全部 7 台设备空闲，可承接新订单。"),    # 答案轮
    ]

    def fake_call_llm(messages, tools=None, **kwargs):
        calls.append(messages)
        return responses.pop(0) if responses else FakeResponse(content="兜底答案")

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)
    app = build_single_agent_graph(FakeResourceRegistry(), checkpointer=None)
    result = app.invoke({
        "messages": [{"role": "user", "content": "帮我查一下空闲的设备"}],
        "tool_results": [],
        "iteration": 0,
        "final_answer": "",
    })

    assert result["final_answer"] == "当前全部 7 台设备空闲，可承接新订单。", \
        f"LLM 已答应作为最终答案，实际: {result['final_answer']!r}"
    assert len(calls) == 2, \
        f"LLM 已答即收尾，不应再拉回工具轮，实际 {len(calls)} 次 LLM 调用"


def test_run_scheduling_intent_not_truncated(monkeypatch):
    """A 分支放置优先级：用户明确要求「跑排产」但 run_scheduling 尚未执行时，
    即使 LLM 已输出文本也不得收尾（否则写工具被跳过、排产未落地）。
    收尾分支必须位于 run_intent 强制检查之后。"""
    from flex_fab_agent.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)
    calls: list = []
    responses = iter([
        FakeResponse(tool_calls=_make_tool_call("query_machine_load")),  # 第1轮查资源
        FakeResponse(content="好的，我来安排排产"),                       # 第2轮 LLM 误以为答完
        FakeResponse(content="正在触发排产求解，请稍候"),                 # 第3轮继续工具轮
        FakeResponse(content="排产版本 13 已生成"),                        # 第4轮
    ])

    def fake_call_llm(messages, tools=None, **kwargs):
        calls.append(messages)
        return next(responses) if responses else FakeResponse(content="兜底答案")

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)
    app = build_single_agent_graph(FakeResourceRegistry(), checkpointer=None)
    result = app.invoke({
        "messages": [{"role": "user", "content": "帮我跑一轮排产"}],
        "tool_results": [],
        "iteration": 0,
        "final_answer": "",
    })

    assert len(calls) >= 3, \
        f"排产意图未调写工具，不得在第 2 轮提前收尾，实际 {len(calls)} 次 LLM 调用"
    assert result["final_answer"] != "好的，我来安排排产", \
        "「好的，我来安排排产」这类提前收尾文本不得成为最终答案"


def test_pure_resource_query_no_order_forced(monkeypatch):
    """B 加强（根因修复）：纯资源查询（非排产意图）不强制查订单——
    第 1 轮调 query_machine_load 后 evaluate 即判数据充足（ready_for_answer），
    即使 LLM 下一轮被系统 prompt「先查订单再查资源」引导想补调 query_orders，
    也不应执行（否则纯查询空转一轮、浪费 token；本次 bug 的根因正是 has_order
    对非订单查询的误判把 LLM 拉回）。"""
    from flex_fab_agent.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)
    responses = [
        FakeResponse(tool_calls=_make_tool_call("query_machine_load")),  # 决策轮查设备
        FakeResponse(tool_calls=_make_tool_call("query_orders")),        # 被引导想补查订单（应被 B 阻断）
    ]

    def fake_call_llm(messages, tools=None, **kwargs):
        if tools is None:  # generate_answer 汇总轮：直接给干净文本答案
            return FakeResponse(content="当前 7 台设备全部空闲")
        return responses.pop(0) if responses else FakeResponse(content="兜底答案")

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)
    app = build_single_agent_graph(FakeResourceRegistry(), checkpointer=None)
    result = app.invoke({
        "messages": [{"role": "user", "content": "帮我查一下空闲的设备"}],
        "tool_results": [],
        "iteration": 0,
        "final_answer": "",
    })

    # 只执行 query_machine_load，未补调 query_orders（纯查询不强制补订单）
    assert {t["tool"] for t in result["tool_results"]} == {"query_machine_load"}, \
        f"纯资源查询不应补调订单工具，实际工具: {[t['tool'] for t in result['tool_results']]}"
    assert result["final_answer"] != "", "纯查询不应无答案"


# ---- 2026-08-30 修复：汇总步 _SUMMARY_NUDGE 措辞误导（「工具已不可用」被误读为故障）----

def _capture_nudge(fake_call_llm_messages: list) -> list:
    """从 generate_answer 的 messages 中提取注入的 _SUMMARY_NUDGE 文本。"""
    out: list = []
    for msgs in fake_call_llm_messages:
        for m in msgs:
            if m.get("role") == "user" and "系统提示" in (m.get("content") or ""):
                out.append(m["content"])
    return out


def test_summary_nudge_no_fault_implication(monkeypatch):
    """坑（2026-08-30 复现，trace 8516ffd）：汇总步标记文本重试时注入的
    _SUMMARY_NUDGE 措辞不得含「工具已不可用」这类会被 LLM 误读为系统故障的表述——
    否则 LLM 据此拒绝任务（「抱歉，我无法完成这个查询…工具已不可用」）。
    应明确「工具结果已收集齐全，直接基于结果作答」。

    复现路径：query_orders 空结果（「未找到匹配的订单。」）→ evaluate 空结果拦截
    → generate_answer 汇总步 LLM 输出标记文本 → 注入 NUDGE。"""
    from flex_fab_agent.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)
    all_llm_messages: list = []
    responses = [
        FakeResponse(tool_calls=_make_tool_call("query_orders", '{"status": "待排队"}')),
        FakeResponse(content=_MARKUP),                     # 汇总步第1次：标记文本
        FakeResponse(content="当前没有待排产的订单。"),      # 汇总步第2次：正常答案
    ]

    def fake_call_llm(messages, tools=None, **kwargs):
        if tools is None:  # generate_answer
            all_llm_messages.append(messages)
        return responses.pop(0) if responses else FakeResponse(content="兜底答案")

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)
    app = build_single_agent_graph(FakeEmptyRegistry(), checkpointer=None)
    result = app.invoke({
        "messages": [{"role": "user", "content": "帮我查一下所有待排产的订单"}],
        "tool_results": [],
        "iteration": 0,
        "final_answer": "",
    })

    nudges = _capture_nudge(all_llm_messages)
    assert nudges, "应注入 _SUMMARY_NUDGE"
    nudge = nudges[-1]
    assert "工具已不可用" not in nudge, f"NUDGE 不得暗示工具故障，实际: {nudge}"
    assert ("基于" in nudge and "结果" in nudge) or "工具结果" in nudge, \
        f"NUDGE 应引导基于已有结果作答，实际: {nudge}"
    assert result["final_answer"] == "当前没有待排产的订单。", \
        f"汇总步重试应产出正常答案，实际: {result['final_answer']!r}"


def test_summary_nudge_includes_tool_results(monkeypatch):
    """B 加强：汇总步标记文本重试时，NUDGE 应附已收集工具结果摘要（含 query_orders
    空结果「未找到匹配的订单。」），引导 LLM 基于数据作答（不信「未找到」时不再盲目再查）。"""
    from flex_fab_agent.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)
    all_llm_messages: list = []
    responses = [
        FakeResponse(tool_calls=_make_tool_call("query_orders", '{"status": "待排队"}')),
        FakeResponse(content=_MARKUP),
        FakeResponse(content="没有待排产订单"),
    ]

    def fake_call_llm(messages, tools=None, **kwargs):
        if tools is None:
            all_llm_messages.append(messages)
        return responses.pop(0) if responses else FakeResponse(content="兜底答案")

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)
    app = build_single_agent_graph(FakeEmptyRegistry(), checkpointer=None)
    result = app.invoke({
        "messages": [{"role": "user", "content": "帮我查一下所有待排产的订单"}],
        "tool_results": [],
        "iteration": 0,
        "final_answer": "",
    })

    nudges = _capture_nudge(all_llm_messages)
    assert nudges, "应注入 _SUMMARY_NUDGE"
    nudge = nudges[-1]
    assert "未找到匹配的订单" in nudge, \
        f"重试消息应附工具结果摘要（含 query_orders 空结果），实际: {nudge}"
    assert result["final_answer"] == "没有待排产订单"


# ---- 2026-08-30 修复：审核意图识别（app_intent 漏「审核」）+ 汇总兜底不道歉 ----

def test_approve_intent_recognizes_shenhe(monkeypatch):
    """坑（2026-08-30 复现，trace 0e5cddd0）：用户「审核通过」是审批意图，但 app_intent
    关键词只收「审批/驳回」漏「审核」→ evaluate 不强制 approve_schedule → 直接汇总，
    LLM 汇总步仍想调写工具 → 连续标记文本 → 兜底道歉。
    修复：app_intent 补「审核」→ 决策轮只查版本未审批时继续工具轮调 approve_schedule。"""
    from flex_fab_agent.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)
    responses = [
        FakeResponse(tool_calls=_make_tool_call("query_schedule")),      # 决策轮查版本
        FakeResponse(tool_calls=_make_tool_call("approve_schedule")),    # 继续工具轮审批
        FakeResponse(content="排产版本 53 已审核通过"),                    # 汇总
    ]

    def fake_call_llm(messages, tools=None, **kwargs):
        return responses.pop(0) if responses else FakeResponse(content="兜底答案")

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)
    app = build_single_agent_graph(FakeRegistry(), checkpointer=None)
    result = app.invoke({
        "messages": [{"role": "user", "content": "帮我把待审核的排产版本审核通过"}],
        "tool_results": [],
        "iteration": 0,
        "final_answer": "",
    })
    tools_used = {t["tool"] for t in result["tool_results"]}
    assert "approve_schedule" in tools_used, \
        f"审核意图应触发审批工具，实际工具: {tools_used}"
    assert result["final_answer"] != sag._GRACEFUL_FALLBACK, "不得兜底道歉"


def test_query_approved_batches_is_read_not_approve(monkeypatch):
    """坑（2026-08-30 回归，trace e3956b5f）：「帮我查询审核通过的批次」是读操作
    （「审核通过」为定语，查已审核数据），但 app_intent 关键词「审核」误判为审批写
    操作 → 强制工具轮 + 注入审批指令，LLM 被矛盾指令带偏生成综合分析垃圾。
    修复：app_intent 排除查询动词（查/查询/查看/有哪些…），查询场景不得强制审批。"""
    from flex_fab_agent.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)
    responses = [
        FakeResponse(tool_calls=_make_tool_call("query_schedule")),  # 决策轮查排产表
        FakeResponse(content="当前没有审核通过的批次，最新版本 53（87 批）全部待审核"),
    ]

    def fake_call_llm(messages, tools=None, **kwargs):
        return responses.pop(0) if responses else FakeResponse(content="兜底答案")

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)
    app = build_single_agent_graph(FakeRegistry(), checkpointer=None)
    result = app.invoke({
        "messages": [{"role": "user", "content": "帮我查询审核通过的批次"}],
        "tool_results": [],
        "iteration": 0,
        "final_answer": "",
    })
    tools_used = {t["tool"] for t in result["tool_results"]}
    assert "approve_schedule" not in tools_used, \
        f"查询已审核批次是读操作，不得强制审批，实际工具: {tools_used}"
    all_text = " ".join(str(m.get("content", "")) for m in result["messages"])
    assert "用户明确要求执行 approve_schedule" not in all_text, \
        "查询场景不得注入审批指令"
    assert result["final_answer"] == "当前没有审核通过的批次，最新版本 53（87 批）全部待审核", \
        f"查询应正常汇总收尾，实际: {result['final_answer']!r}"


def test_approve_intent_forced_by_orchestrator(monkeypatch):
    """坑（2026-08-30 trace 9fb9384a）：LLM 连续多轮不执行审批（DeepSeek 幻觉调用
    历史工具，即使 tools 过滤只留 approve_schedule 仍返回 query_schedule）→
    编排层在 iteration>=2 时代执行 approve_schedule，确定性完成审批，不依赖 LLM 自觉。"""
    from flex_fab_agent.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)

    class FakeVersionRegistry(FakeScheduleRegistry):
        """query_schedule 返回含版本号，供编排层代执行提取 version_id。"""

        def execute(self, name, arguments, token=None):
            if name == "query_schedule":
                return "排产版本 66 | 审批状态 待审核 | 批次 87"
            return super().execute(name, arguments, token=token)

    responses = [
        FakeResponse(tool_calls=_make_tool_call("query_schedule")),  # 轮1 查版本
        FakeResponse(tool_calls=_make_tool_call("query_schedule")),  # 轮2 仍不执行（幻觉）
        FakeResponse(content="排产版本 66 已审批通过并生效"),          # 汇总
    ]

    def fake_call_llm(messages, tools=None, **kwargs):
        return responses.pop(0) if responses else FakeResponse(content="兜底答案")

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)
    app = build_single_agent_graph(FakeVersionRegistry(), checkpointer=None)
    result = app.invoke({
        "messages": [{"role": "user", "content": "帮我把待审核的排产版本审核通过"}],
        "tool_results": [],
        "iteration": 0,
        "final_answer": "",
    })
    tools_used = {t["tool"] for t in result["tool_results"]}
    assert "approve_schedule" in tools_used, \
        f"编排层应代执行审批，实际工具: {tools_used}"
    assert result["final_answer"] == "排产版本 66 已审批通过并生效", \
        f"代执行后应正常汇总，实际: {result['final_answer']!r}"


def test_summary_fallback_uses_tool_results(monkeypatch):
    """B：汇总步标记文本重试耗尽（MAX_RETRIES=2）时，兜底应基于已收集工具结果拼接
    （_SUMMARY_FALLBACK_PREFIX），而非降级 _GRACEFUL_FALLBACK 道歉。"""
    from flex_fab_agent.graph import single_agent_graph as sag
    _disable_compression(monkeypatch)
    responses = [
        FakeResponse(tool_calls=_make_tool_call("query_schedule")),  # 决策轮
        FakeResponse(content=_MARKUP),   # 汇总第1次标记
        FakeResponse(content=_MARKUP),   # 汇总第2次标记
        FakeResponse(content=_MARKUP),   # 汇总第3次标记（重试耗尽）
    ]

    def fake_call_llm(messages, tools=None, **kwargs):
        return responses.pop(0) if responses else FakeResponse(content="兜底答案")

    monkeypatch.setattr(sag, "call_llm", fake_call_llm)
    app = build_single_agent_graph(FakeRegistry(), checkpointer=None)
    result = app.invoke({
        "messages": [{"role": "user", "content": "帮我查一下排产情况"}],
        "tool_results": [],
        "iteration": 0,
        "final_answer": "",
    })

    assert result["final_answer"] != sag._GRACEFUL_FALLBACK, \
        f"标记耗尽不得降级为道歉兜底，实际: {result['final_answer']!r}"
    assert result["final_answer"].startswith(sag.SUMMARY_FALLBACK_PREFIX), \
        f"兜底应带 SUMMARY_FALLBACK_PREFIX 且含工具结果，实际: {result['final_answer']!r}"
