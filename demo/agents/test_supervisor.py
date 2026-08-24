"""Supervisor R-8（T5a.14）测试：orchestrate 回传子 Agent 工具调用序列（tool_results）。

用于 eval multi 模式重建 trajectory——修复前 supervisor 不记录工具调用，
multi 评估轨迹层空置、语义层无 RAG 上下文。
"""
import demo.agents.supervisor as sup_mod


class FakeRegistry:
    """记录 execute 调用的假注册表（模拟真实 registry.execute 副作用）。"""

    def execute(self, name, arguments, token=None, audit=None):
        return f"{name} ok"


def _response(text):
    return type("R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": text})()})()]})()


def test_supervisor_orchestrate_returns_tool_results(monkeypatch):
    """multi 评估前置：supervisor 子 Agent 工具调用序列回传 summary['tool_results']。"""
    registry = FakeRegistry()
    sup = sup_mod.SupervisorAgent(registry)

    # mock 路由/鉴权/审计/子 Agent/LLM，隔离真实依赖（不发 LLM、不落审计文件）
    monkeypatch.setattr(sup.router, "route", lambda query: {"targets": ["full"]})
    monkeypatch.setattr(sup.sts, "issue_user_token", lambda *a, **k: "user-tok")
    monkeypatch.setattr(sup.sts, "exchange", lambda *a, **k: ("sub-tok", "ok"))
    monkeypatch.setattr(sup.sts, "get_token", lambda *a, **k: "sub-tok")
    monkeypatch.setattr(sup.audit, "log", lambda *a, **k: None)
    monkeypatch.setattr(sup.audit, "get_report", lambda: "审计报告")

    def fake_review(order_id, registry, token, audit):
        registry.execute("get_order_detail", {"order_id": order_id}, token, audit)
        return {"order_id": order_id, "risk_assessment": {"risk_level": "低"}}

    def fake_production(order_ids, registry, token, audit):
        registry.execute("query_inventory", {}, token, audit)
        return {"feasibility_assessment": {"feasible": True}}

    monkeypatch.setattr(sup_mod, "review_order", fake_review)
    monkeypatch.setattr(sup_mod, "assess_production_feasibility", fake_production)
    monkeypatch.setattr(sup_mod, "call_llm", lambda *a, **k: _response("综合排产建议"))

    summary = sup.orchestrate("复盘：评估当前产能与订单风险")

    assert "tool_results" in summary, "summary 应含 tool_results（R-8）"
    tools = [t["tool"] for t in summary["tool_results"]]
    # 审核 3 单（ORD001/003/005）各 1 次 get_order_detail + 生产 1 次 query_inventory
    assert tools == ["get_order_detail"] * 3 + ["query_inventory"], f"实际调用序列: {tools}"
    assert summary["tool_results"][0]["arguments"] == {"order_id": "ORD001"}
    assert summary["tool_results"][-1]["result"] == "query_inventory ok"


# ---- M6 T6.3：supervisor 两级 trace 树 ----

def test_supervisor_trace_two_level_tree(monkeypatch):
    """orchestrate 包 supervisor:orchestrate 父 span；dispatch 子 span；
    工具 span 挂 dispatch 下 -> supervisor 级与工具级两层。"""
    from demo.observability import tracer

    class SpanRegistry(FakeRegistry):
        """假注册表 + 手动 tool span（模拟真实 registry.execute 埋点）。"""

        def execute(self, name, arguments, token=None, audit=None):
            with tracer.span(f"tool:{name}"):
                return f"{name} ok"

    sup = sup_mod.SupervisorAgent(SpanRegistry())
    monkeypatch.setattr(sup.router, "route", lambda query: {"targets": ["full"]})
    monkeypatch.setattr(sup.sts, "issue_user_token", lambda *a, **k: "user-tok")
    monkeypatch.setattr(sup.sts, "exchange", lambda *a, **k: ("sub-tok", "ok"))
    monkeypatch.setattr(sup.sts, "get_token", lambda *a, **k: "sub-tok")
    monkeypatch.setattr(sup.audit, "log", lambda *a, **k: None)
    monkeypatch.setattr(sup.audit, "get_report", lambda: "审计报告")
    monkeypatch.setattr(
        sup_mod, "review_order",
        lambda oid, registry, token, audit: (
            registry.execute("get_order_detail", {"order_id": oid}, token, audit) and
            None) or {"order_id": oid, "risk_assessment": {}})
    monkeypatch.setattr(
        sup_mod, "assess_production_feasibility",
        lambda order_ids, registry, token, audit: (
            registry.execute("query_inventory", {}, token, audit) and None)
        or {"feasibility_assessment": {"feasible": True}})
    monkeypatch.setattr(sup_mod, "call_llm", lambda *a, **k: _response("综合排产建议"))

    tracer.reset()
    sup.orchestrate("复盘：评估当前产能与订单风险")
    sm = tracer.get_summary()
    parents = {sp["name"]: sp["parent"] for sp in sm["spans"] if sp["name"].startswith("supervisor:")}
    assert "supervisor:orchestrate" in parents
    assert parents["supervisor:orchestrate"] is None
    for name, parent in parents.items():
        if name != "supervisor:orchestrate":
            assert parent == "supervisor:orchestrate", f"{name} 应挂 orchestrate 下"
    # 工具 span 挂在 dispatch 之下（两级树）
    tool_parents = {sp["parent"] for sp in sm["spans"] if sp["name"].startswith("tool:")}
    assert tool_parents == {"supervisor:dispatch"}, f"工具 span 父层: {tool_parents}"
