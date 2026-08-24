"""run_single_agent 缓存守卫测试（缓存投毒纵深防御：标记文本不入语义缓存）。"""
import demo.agents.single_agent as sa


class StubApp:
    """最小假图：invoke 返回固定 final_answer，无 checkpoint（thread_id None 路径）。"""

    def __init__(self, final_answer: str):
        self._final_answer = final_answer

    def invoke(self, state, config):
        return {**state, "final_answer": self._final_answer, "tool_results": []}


def _run(monkeypatch, final_answer: str) -> list:
    calls: list = []
    monkeypatch.setattr(sa, "_get_app", lambda registry: StubApp(final_answer))
    monkeypatch.setattr(sa.semantic_cache, "get", lambda q: None)  # miss，走图执行
    monkeypatch.setattr(sa.semantic_cache, "put", lambda q, a: calls.append((q, a)))
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
    from demo.graph.single_agent_graph import _GRACEFUL_FALLBACK
    calls = _run(monkeypatch, _GRACEFUL_FALLBACK)
    assert calls == [], f"失败兜底文本不得入缓存，实际写入 {calls}"
