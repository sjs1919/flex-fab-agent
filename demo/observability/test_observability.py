"""观测层单元测试：Tracer（span 采集）+ CostTracker（计费/熔断）。"""
import time

from demo.observability.tracer import Tracer, Span
from demo.observability.cost import CostTracker, CostEntry, BudgetExceededError


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
    from demo.observability import cost as cost_mod
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
