"""api.py /ask 看板落库测试（M5b T5b.6，需 WSL MySQL）。

覆盖：/ask 后 cost_record + trace_record 各落一条（trace_id 关联）、
落库失败不影响 /ask 响应（旁路观测红线）。run_single_agent 打桩，
不打真实 LLM。
"""
import pytest
from fastapi.testclient import TestClient

import flex_fab_agent.api as api_mod
from flex_fab_agent.api import app
from flex_fab_agent.tools.data import get_connection

client = TestClient(app)


def _rows_by_trace(trace_id: str, table: str) -> list[tuple]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {table} WHERE trace_id = %s", (trace_id,))
            return cur.fetchall()


@pytest.fixture(autouse=True)
def _stub_agent(monkeypatch):
    """打桩 run_single_agent：不依赖 LLM，但制造真实的 trace span + cost 记录。"""
    from flex_fab_agent.observability.tracer import tracer
    from flex_fab_agent.observability.cost import cost_tracker

    def _fake_run(query, registry=None, thread_id=None):
        with tracer.span("llm:stub", model="stub-model"):
            cost_tracker.record("DeepSeek", model="deepseek-v4-flash",
                                prompt_tokens=100, completion_tokens=50)
        return {"final_answer": f"打桩回答：{query}", "tool_results": []}

    monkeypatch.setattr(api_mod, "run_single_agent", _fake_run)
    yield


def test_ask_persists_cost_and_trace():
    """/ask 后 cost_record/trace_record 各一条，trace_id 与本轮 tracer 一致。"""
    r = client.post("/ask", json={"query": "测试看板落库"})
    assert r.status_code == 200
    assert r.json()["answer"] == "打桩回答：测试看板落库"
    # 请求线程的 trace_id 存 contextvars，测试线程读不到 —— 从响应取
    tid = r.json()["trace_id"]
    assert tid  # M6 T6.7：/ask 响应带 trace_id（前端 judge/回放入口）
    try:
        costs = _rows_by_trace(tid, "cost_record")
        traces = _rows_by_trace(tid, "trace_record")
        assert len(costs) == 1 and len(traces) == 1
        # cost 列序：id, trace_id, created_at, total_cost, total_tokens, total_calls, by_provider, by_model
        assert float(costs[0][3]) == pytest.approx(150 / 1_000_000)  # DeepSeek 1.0¥/百万×150 token
        assert costs[0][4] == 150  # total_tokens = 100 + 50
        assert costs[0][5] == 1    # total_calls
        assert "deepseek-v4-flash" in costs[0][7]  # by_model JSON
        # trace 记录字段（trace_id, created_at, total_ms, span_count, by_kind, spans）
        assert traces[0][4] == 1   # span_count
        assert '"llm:stub"' in traces[0][6]  # spans JSON
    finally:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM cost_record WHERE trace_id = %s", (tid,))
                cur.execute("DELETE FROM trace_record WHERE trace_id = %s", (tid,))
            conn.commit()


def test_ask_survives_dashboard_persistence_failure(monkeypatch):
    """落库异常不影响 /ask 响应（旁路观测红线）。"""
    from flex_fab_agent.observability import dashboard
    monkeypatch.setattr(
        dashboard, "record_cost",
        lambda summary, trace_id="": (_ for _ in ()).throw(RuntimeError("注入落库故障")))
    r = client.post("/ask", json={"query": "落库失败也不影响"})
    assert r.status_code == 200
    assert r.json()["answer"] == "打桩回答：落库失败也不影响"
