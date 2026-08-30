"""M5b E2E 验收（验收条 74 + M4 成本落库；需 WSL MySQL）。

六条链路：
  ① seed 时钟 -> 模拟器 3 tick -> kpi_snapshot 3 行（sim_time 递增）
  ② /ask（打桩 LLM）-> cost_record + trace_record 落库（trace_id 一致）
  ③ 三只读端点返回 {items:[...]}
  ④ 口径一致：最新快照 metrics 与 kpi_metrics() 数值一致；端点 by_model 聚合与明细自洽
  ⑤ 静态 HTML 兜底生成（零 CDN）
  ⑥ /kpi 与 kpi_snapshot 同源（query_kpi 输出含 5 指标，快照 metrics 字段对齐）
"""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import flex_fab_agent.api as api_mod
from flex_fab_agent.api import app
from flex_fab_agent.observability import dashboard
from flex_fab_agent.simulator import clock, runner as runner_mod
from flex_fab_agent.tools.data import get_connection

client = TestClient(app)
T0 = datetime(2026, 9, 2, 8, 0, 0)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """mysql 数据源 + 固定时钟 + 打桩 run_single_agent（不打真实 LLM）。"""
    monkeypatch.setenv("DEMO_DATA_SOURCE", "mysql")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM kpi_snapshot")
        clock.init_clock(conn, T0)
        conn.commit()
    from flex_fab_agent.observability.tracer import tracer
    from flex_fab_agent.observability.cost import cost_tracker

    def _fake_run(query, registry=None, thread_id=None):
        with tracer.span("llm:e2e", model="e2e-model"):
            cost_tracker.record("DeepSeek", model="deepseek-v4-flash",
                                prompt_tokens=200, completion_tokens=100)
        return {"final_answer": "e2e", "tool_results": []}
    monkeypatch.setattr(api_mod, "run_single_agent", _fake_run)
    yield
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM kpi_snapshot")
            cur.execute("DELETE FROM cost_record WHERE trace_id = %s", (tracer.trace_id,))
            cur.execute("DELETE FROM trace_record WHERE trace_id = %s", (tracer.trace_id,))
        conn.commit()


def _tid() -> str:
    from flex_fab_agent.observability.tracer import tracer
    return tracer.trace_id


def test_e2e_m5b_dashboard_chain():
    # ① 模拟器 3 tick -> kpi_snapshot 3 行，sim_time 递增
    r = runner_mod.SimulatorRunner()
    for _ in range(3):
        r.run_tick()
    hist = dashboard.kpi_history()
    assert len(hist) == 3
    times = [h["sim_time"] for h in hist]
    assert times == sorted(times)
    assert times[0] == "2026-09-02 09:00:00" and times[-1] == "2026-09-02 11:00:00"

    # ④ 口径一致（前半）：最新快照与同刻 kpi_metrics() 数值一致
    from flex_fab_agent.tools.scheduler_tools import kpi_metrics
    fresh = kpi_metrics()
    latest = hist[-1]["metrics"]
    assert latest["on_time_rate"] == fresh["on_time_rate"]
    assert latest["delay_total"] == fresh["delay_total"]
    assert latest["yield_rate"] == fresh["yield_rate"]

    # ⑥ /kpi 与快照同源：query_kpi 输出含 5 指标名
    from flex_fab_agent.tools.scheduler_tools import query_kpi
    report = query_kpi()
    for name in ["准交率", "延期金额", "舱利用率", "良率", "前道瓶颈占用"]:
        assert name in report, f"query_kpi 缺指标 {name}"

    # ② /ask -> cost_record + trace_record（trace_id 一致，by_model 含 model）
    resp = client.post("/ask", json={"query": "e2e 看板链路"})
    assert resp.status_code == 200
    tid = resp.json()["trace_id"]  # 请求线程 trace_id 存 contextvars，测试线程读不到
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT total_tokens, by_model FROM cost_record WHERE trace_id=%s", (tid,))
            cost_row = cur.fetchone()
            cur.execute("SELECT span_count FROM trace_record WHERE trace_id=%s", (tid,))
            trace_row = cur.fetchone()
    assert cost_row is not None and trace_row is not None
    assert cost_row[0] == 300  # 200 + 100
    assert "deepseek-v4-flash" in cost_row[1]
    assert trace_row[0] == 1

    # ③ 三只读端点 {items:[...]}，含刚写入的数据
    j1 = client.get("/dashboard/kpi-history").json()
    j2 = client.get("/dashboard/costs").json()
    j3 = client.get("/dashboard/traces").json()
    assert len(j1["items"]) == 3
    assert any(i["trace_id"] == tid for i in j2["items"])
    assert any(t["trace_id"] == tid for t in j3["items"])

    # ④ 口径一致（后半）：端点 by_model 聚合与明细自洽
    manual: dict[str, float] = {}
    for item in j2["items"]:
        for model, st in item["by_model"].items():
            manual[model] = round(manual.get(model, 0.0) + st["cost"], 6)
    for model, cost in manual.items():
        assert abs(j2["by_model"][model]["cost"] - cost) < 1e-9


def test_e2e_m5b_static_html_offline(tmp_path):
    """⑤ 静态 HTML 兜底：零 CDN 离线可开（有数据与空库两态）。"""
    r = runner_mod.SimulatorRunner()
    r.run_tick()  # 保证至少一条快照
    try:
        out = tmp_path / "e2e.html"
        assert dashboard.main(["--out", str(out)]) == 0
        html = out.read_text(encoding="utf-8")
        assert "<svg" in html and "http://" not in html and "https://" not in html
    finally:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM kpi_snapshot")
            conn.commit()
