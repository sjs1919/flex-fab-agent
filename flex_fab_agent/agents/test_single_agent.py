"""run_single_agent 缓存守卫测试（缓存投毒纵深防御：标记文本不入语义缓存）。"""
import flex_fab_agent.agents.single_agent as sa


class StubApp:
    """最小假图：invoke 返回固定 final_answer，无 checkpoint（thread_id None 路径）。"""

    def __init__(self, final_answer: str):
        self._final_answer = final_answer

    def invoke(self, state, config):
        return {**state, "final_answer": self._final_answer, "tool_results": []}


def _run(monkeypatch, final_answer: str) -> list:
    calls: list = []
    monkeypatch.setattr(sa, "_get_app", lambda registry: StubApp(final_answer))
    # single_agent 经 cache_manager facade 访问语义缓存（P0-3 改造后不再直接 import
    # semantic_cache，旧测试 stub sa.semantic_cache 已失效），stub facade 单例方法
    monkeypatch.setattr(sa.cache_manager, "lookup_semantic",
                        lambda q, threshold=None: None)  # miss，走图执行
    monkeypatch.setattr(sa.cache_manager, "store_semantic",
                        lambda q, a, sensitive=False: calls.append((q, a)))
    sa.run_single_agent("今天先做哪些订单？")
    return calls


def test_markup_answer_not_cached(monkeypatch):
    """坑（缓存投毒纵深）：即使上游产出含 DSML 标记的 final_answer，也不得写入语义缓存。"""
    markup = '<|tool_calls|>\n<invoke name="query_orders">\n{"status": "pending"}\n</invoke>'
    calls = _run(monkeypatch, markup)
    assert calls == [], f"标记文本不得入缓存，实际写入 {calls}"


def test_clean_answer_cached(monkeypatch):
    """正常答案仍写入缓存（守卫不误伤）。"""
    calls = _run(monkeypatch, "ORD003 今天优先排产")
    assert len(calls) == 1
    assert calls[0][1] == "ORD003 今天优先排产"


def test_graceful_fallback_not_cached(monkeypatch):
    """坑（缓存投毒纵深）：生成异常的兜底文本不得入缓存，否则用户重问一直命中失败答案。"""
    from flex_fab_agent.graph.single_agent_graph import _GRACEFUL_FALLBACK
    calls = _run(monkeypatch, _GRACEFUL_FALLBACK)
    assert calls == [], f"失败兜底文本不得入缓存，实际写入 {calls}"


def test_loop_guard_dump_not_cached(monkeypatch):
    """坑（缓存投毒纵深）：循环守卫的原始工具 dump 不得入缓存，否则同类问题重问
    一直命中垃圾（2026-08-27「有没有订单已经打印完成？」实测：守卫 dump 进缓存 →
    后续命中跳过整图执行 → judge 0/0）。"""
    from flex_fab_agent.graph.single_agent_graph import LOOP_GUARD_FALLBACK_PREFIX
    dump = LOOP_GUARD_FALLBACK_PREFIX + "- query_orders: 未找到匹配的订单。"
    calls = _run(monkeypatch, dump)
    assert calls == [], f"循环守卫 dump 不得入缓存，实际写入 {calls}"


# ---- _is_state_sensitive 分类器（发现③：关键词过宽误伤知识类问题） ----

def test_knowledge_query_not_state_sensitive():
    """知识类问题不得误判 sensitive：「什么是排产」是概念疑问，与实时状态无关。"""
    assert sa._is_state_sensitive("什么是排产") is False
    assert sa._is_state_sensitive("为什么要做排产？") is False


def test_state_query_still_sensitive():
    """强状态词命中仍判 sensitive：短 TTL + 数据变更清除。"""
    assert sa._is_state_sensitive("订单001当前状态如何？") is True
    assert sa._is_state_sensitive("有哪些订单在排队？") is True


# ---- 2026-08-30 修复：拒绝话术 / 汇总兜底不入语义缓存（投毒变体） ----

def test_rejection_answer_not_cached(monkeypatch):
    """坑（缓存投毒变体，2026-08-30 实测 trace 73d6c8e cache hit 返回拒绝话术）：
    LLM 输出的拒绝/故障话术（「无法完成/工具已不可用」）不得写入语义缓存，
    否则重问一直命中垃圾。"""
    rejection = ("抱歉，我无法完成这个查询。系统提示表明上一轮的工具调用未能正确解析，"
                 "且当前轮次工具已不可用。请您重新发送一次问题。")
    calls = _run(monkeypatch, rejection)
    assert calls == [], f"拒绝话术不得入缓存，实际写入 {calls}"


def test_summary_fallback_prefix_not_cached(monkeypatch):
    """B：汇总步标记耗尽兜底（_SUMMARY_FALLBACK_PREFIX 前缀）不得入缓存（投毒纵深防御）。"""
    from flex_fab_agent.graph.single_agent_graph import SUMMARY_FALLBACK_PREFIX
    fa = SUMMARY_FALLBACK_PREFIX + "- query_schedule: 排产版本 53 待审核"
    calls = _run(monkeypatch, fa)
    assert calls == [], f"汇总兜底不得入缓存，实际写入 {calls}"
    assert sa._is_state_sensitive("设备E01进度到哪了？") is True
    assert sa._is_state_sensitive("3号机还有没有在打印？") is True
    assert sa._is_state_sensitive("查一下目前待排产的订单有哪些") is True  # 2026-08-29 补「目前」
    assert sa._is_state_sensitive("还有哪些订单在排队") is True             # 2026-08-29 补「还有」
