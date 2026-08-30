"""观测层单元测试：Tracer（span 采集）+ CostTracker（计费/熔断）。"""
import time

from flex_fab_agent.observability.tracer import Tracer, Span
from flex_fab_agent.observability.cost import CostTracker, CostEntry, BudgetExceededError


# ---- Tracer ----

def test_tracer_span_records_duration():
    t = Tracer()
    with t.span("llm:call", provider="test") as s:
        time.sleep(0.01)
    assert s.duration_ms is not None and s.duration_ms > 0
    assert t.get_summary()["span_count"] == 1
    assert t.get_summary()["by_kind"] == {"llm": 1}


def test_tracer_by_kind_groups_by_prefix():
    t = Tracer()
    with t.span("tool:query_orders"):
        pass
    with t.span("tool:query_inventory"):
        pass
    with t.span("llm:call"):
        pass
    sm = t.get_summary()
    assert sm["by_kind"] == {"tool": 2, "llm": 1}


def test_tracer_reset_clears():
    t = Tracer()
    with t.span("llm:call"):
        pass
    t.reset()
    assert t.get_summary()["span_count"] == 0


def test_tracer_span_attrs():
    t = Tracer()
    with t.span("tool:query_orders", server="order_server") as s:
        s.attributes["tool_success"] = True
        s.attributes["tool_retries"] = 1
    spans = t.get_summary()["spans"]
    assert spans[0]["name"] == "tool:query_orders"
    assert spans[0]["attrs"]["tool_success"] is True
    assert spans[0]["attrs"]["tool_retries"] == 1


def test_tracer_record_manual():
    t = Tracer()
    t.record("llm:call", duration_ms=50, provider="test")
    assert t.get_summary()["span_count"] == 1
    assert t.get_summary()["spans"][0]["ms"] == 50


# ---- M6 T6.2：Span 父子树 ----

def test_tracer_nested_span_parent_chain():
    """嵌套 with 自动建树：A>B>C，parent 链正确；退出后栈清空。"""
    t = Tracer()
    with t.span("supervisor:orchestrate") as a:
        with t.span("supervisor:dispatch", agent="x") as b:
            with t.span("tool:query_orders") as c:
                pass
    assert c.parent is b and b.parent is a and a.parent is None
    sm = t.get_summary()
    parents = {sp["name"]: sp["parent"] for sp in sm["spans"]}
    assert parents["supervisor:orchestrate"] is None
    assert parents["supervisor:dispatch"] == "supervisor:orchestrate"
    assert parents["tool:query_orders"] == "supervisor:dispatch"


def test_tracer_sibling_spans_parent_none():
    """平级 with：各自 parent=None（树退化一层）。"""
    t = Tracer()
    with t.span("llm:call"):
        pass
    with t.span("tool:query_orders"):
        pass
    sm = t.get_summary()
    assert all(sp["parent"] is None for sp in sm["spans"])


def test_tracer_nested_span_exception_unwinds_stack():
    """嵌套 with 异常也必须出栈，不留脏栈（下个 span parent 不残留）。"""
    t = Tracer()
    try:
        with t.span("outer"):
            with t.span("inner"):
                raise ValueError("boom")
    except ValueError:
        pass
    assert t._stack == []
    with t.span("after") as s:
        pass
    assert s.parent is None


def test_tracer_record_parent_none():
    """record() 无栈语义，parent=None。"""
    t = Tracer()
    t.record("llm:call", duration_ms=50)
    assert t.get_summary()["spans"][0]["parent"] is None


# ---- CostTracker ----

def test_cost_tracker_records_entry():
    c = CostTracker()
    entry = c.record("DeepSeek", prompt_tokens=1_000_000, completion_tokens=0)
    assert entry.cost_total == 1.0  # DeepSeek ¥1/百万


def test_cost_tracker_unknown_provider_default_price():
    c = CostTracker()
    entry = c.record("未知provider", prompt_tokens=1_000_000, completion_tokens=1_000_000)
    assert entry.cost_total == 4.0  # 默认 ¥2/百万 × 2


def test_cost_tracker_total_tokens():
    c = CostTracker()
    c.record("DeepSeek", prompt_tokens=100, completion_tokens=200)
    assert c.total_tokens == 300


def test_cost_tracker_reset():
    c = CostTracker()
    c.record("DeepSeek", prompt_tokens=100)
    c.reset()
    assert c.total_tokens == 0
    assert c.total_cost == 0


def test_cost_tracker_budget_breach(monkeypatch):
    from flex_fab_agent.observability import cost as cost_mod
    monkeypatch.setattr(cost_mod, "BUDGET_LIMIT", 0.01)  # 极小预算
    c = CostTracker()
    # 一次调用就超预算
    with __import__("pytest").raises(BudgetExceededError):
        c.record("DeepSeek", prompt_tokens=20_000_000)  # ¥20
    assert c.is_budget_exceeded


def test_cost_tracker_by_provider():
    c = CostTracker()
    c.record("DeepSeek", prompt_tokens=1_000_000)
    c.record("火山豆包(coding)", prompt_tokens=1_000_000)
    stats = c.by_provider()
    assert "DeepSeek" in stats
    assert "火山豆包(coding)" in stats
    assert stats["DeepSeek"]["cost"] == 1.0


def test_cost_tracker_by_model():
    """by_model 分组统计（M5b T5b.4）：同 provider 不同 model 分开聚合。"""
    c = CostTracker()
    c.record("DeepSeek", model="deepseek-v4-flash", prompt_tokens=1_000_000)
    c.record("DeepSeek", model="deepseek-v4-flash", completion_tokens=1_000_000)
    c.record("Kimi(coding)", model="kimi-latest", prompt_tokens=500_000)
    stats = c.by_model()
    assert stats["deepseek-v4-flash"]["calls"] == 2
    assert stats["deepseek-v4-flash"]["tokens"] == 2_000_000
    assert stats["deepseek-v4-flash"]["cost"] == 2.0  # 1.0 输入 + 1.0 输出
    assert stats["kimi-latest"]["calls"] == 1


def test_cost_tracker_by_model_empty_model_name():
    """model 为空串时归到 '' 键（与 by_provider 的空 provider 行为一致，不丢数据）。"""
    c = CostTracker()
    c.record("DeepSeek", prompt_tokens=100)
    assert "" in c.by_model()


def test_cost_tracker_get_summary_has_by_model():
    """get_summary 含 by_model 键（M5b 看板落库依赖）。"""
    c = CostTracker()
    c.record("DeepSeek", model="deepseek-v4-flash", prompt_tokens=1_000)
    sm = c.get_summary()
    assert "by_model" in sm
    assert sm["by_model"]["deepseek-v4-flash"]["calls"] == 1
