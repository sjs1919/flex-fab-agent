"""api.py 调试台读端点测试（M6 T6.5，需 MySQL）。

覆盖：/ask 旁路落 case（trace_id 一致）、/debug/cases 过滤、
/debug/trace/{id} 合并 trace_record + case、缺 id 404、匿名可读。
run_single_agent 打桩，不打真实 LLM；cases.jsonl 指向 tmp_path。
"""
import pytest
from fastapi.testclient import TestClient

import flex_fab_agent.api as api_mod
import flex_fab_agent.observability.case_collector as cc
from flex_fab_agent.api import app
from flex_fab_agent.tools.data import get_connection

client = TestClient(app)


@pytest.fixture(autouse=True)
def _stub_agent(monkeypatch, tmp_path):
    """打桩 run_single_agent + case 文件指向 tmp + 开关默认全开。"""
    from flex_fab_agent.observability.tracer import tracer

    monkeypatch.setattr(cc, "CASES_PATH", tmp_path / "cases.jsonl")
    monkeypatch.setattr(
        cc, "get_config",
        lambda c, k, d="": {"case_collection_enabled": "on",
                            "sample_rate": "1.0"}.get(k, d))

    def _fake_run(query, registry=None, thread_id=None):
        with tracer.span("llm:stub", model="stub-model"):
            pass
        return {"final_answer": f"打桩回答：{query}",
                "tool_results": [{"tool": "query_orders", "arguments": {},
                                  "result": "ok"}]}

    monkeypatch.setattr(api_mod, "run_single_agent", _fake_run)
    yield


def _cleanup(trace_id: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            for table in ("cost_record", "trace_record"):
                cur.execute(f"DELETE FROM {table} WHERE trace_id=%s", (trace_id,))
        conn.commit()


def test_ask_records_case():
    """/ask 后 cases.jsonl 有行：type=normal、good=null、trace_id 与本轮一致。"""
    r = client.post("/ask", json={"query": "查询订单风险"})
    assert r.status_code == 200
    tid = r.json()["trace_id"]  # 请求线程 trace_id 存 contextvars，测试线程读不到 —— 从响应取
    try:
        rows = cc.load_cases()
        c = next((r for r in rows if r["trace_id"] == tid), None)
        assert c is not None, "应记录本轮 case"
        assert c["type"] == "normal" and c["good"] is None
        assert c["tools"] == ["query_orders"]
    finally:
        _cleanup(tid)


def test_debug_cases_list_and_filter():
    """匿名可读；type 过滤生效。"""
    cc.record_case("查询订单", "a", [], "tc1")
    cc.record_case("你好", "b", [], "tc2")
    r = client.get("/debug/cases")
    assert r.status_code == 200
    ids = [c["trace_id"] for c in r.json()["items"]]
    assert ids == ["tc2", "tc1"]  # 时间倒序（2026-08-26：debug_cases 改最新在前）
    r = client.get("/debug/cases", params={"type": "chitchat"})
    assert [c["trace_id"] for c in r.json()["items"]] == ["tc2"]


def test_debug_trace_merges_record_and_case():
    """回放：trace_record（DB）+ case（JSONL）合并结构；缺 id 404。"""
    r = client.post("/ask", json={"query": "查询库存"})
    assert r.status_code == 200
    tid = r.json()["trace_id"]  # 请求线程 trace_id 存 contextvars，测试线程读不到 —— 从响应取
    try:
        r = client.get(f"/debug/trace/{tid}")
        assert r.status_code == 200
        body = r.json()
        assert body["trace"]["trace_id"] == tid
        assert body["trace"]["spans"], "trace_record 应含 span 明细"
        assert body["case"]["query"] == "查询库存"
    finally:
        _cleanup(tid)

    r = client.get("/debug/trace/no-such-id")
    assert r.status_code == 404


def test_debug_case_failure_does_not_break_ask(monkeypatch):
    """case 落盘抛异常不影响 /ask 响应（旁路红线）。"""
    def _boom(*a, **k):
        raise RuntimeError("case 炸了")
    monkeypatch.setattr(cc, "record_case", _boom)
    r = client.post("/ask", json={"query": "查询订单"})
    assert r.status_code == 200
    assert r.json()["answer"] == "打桩回答：查询订单"
    from flex_fab_agent.observability.tracer import tracer
    _cleanup(tracer.trace_id)


# ---- M6 T6.6：rerun / judge / stats / label / config ----

def _admin_token() -> str:
    from flex_fab_agent.auth.token_exchange import STS
    return STS().issue_user_token("admin-debug", "admin")


def test_write_endpoints_require_admin():
    """R-7 回归：rerun/judge/label/config 写端点无 token 401。"""
    assert client.post("/debug/rerun/x").status_code == 401
    assert client.post("/debug/judge/x").status_code == 401
    assert client.put("/debug/cases/x/label", json={"good": True}).status_code == 401
    assert client.put("/config", json={}).status_code == 401


def test_rerun_admin_ok():
    """admin rerun：case.query 重走 run_single_agent（打桩），返回新答案并回写 rerun。"""
    cc.record_case("查询订单风险", "旧答案", [], "tr-rerun1")
    tid = _admin_token()
    r = client.post("/debug/rerun/tr-rerun1", headers={"X-Admin-Token": tid})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "打桩回答：查询订单风险"
    assert body["new_trace_id"] != "tr-rerun1"
    c = cc.load_cases()[0]
    assert c["rerun"]["answer"] == "打桩回答：查询订单风险"
    assert c["rerun"]["trace_id"] == body["new_trace_id"]
    _cleanup(body["new_trace_id"])

    assert client.post("/debug/rerun/no-such",
                       headers={"X-Admin-Token": tid}).status_code == 404


def test_judge_admin_ok(monkeypatch):
    """admin judge：分数写回 case.judge（有 rerun 优先评 rerun 答案）。"""
    import flex_fab_agent.eval.judge as judge_mod
    cc.record_case("查询订单风险", "旧答案", [], "tr-judge1")
    cc.attach_rerun("tr-judge1", {"trace_id": "tr-judge1-n", "answer": "新答案"})
    monkeypatch.setattr(judge_mod, "judge_semantic_quality",
                        lambda q, c, a: {"answer_relevancy": 0.9,
                                         "judged_answer": a})
    r = client.post("/debug/judge/tr-judge1", headers={"X-Admin-Token": _admin_token()})
    assert r.status_code == 200
    assert r.json()["judge"]["answer_relevancy"] == 0.9
    assert r.json()["judge"]["judged_answer"] == "新答案"
    assert cc.load_cases()[0]["judge"]["answer_relevancy"] == 0.9


def test_debug_stats_conversion():
    """stats：总数/分类/good-bad 计数 + bad->good 转化率（手工构造 2 bad 1 转化）。"""
    cc.record_case("问甲", "答甲", [], "ts1")   # normal -> bad -> rerun+judge 达标
    cc.record_case("问乙", "答乙", [], "ts2")   # normal -> bad -> 无 rerun
    cc.record_case("你好", "答丙", [], "ts3")   # chitchat
    cc.label_case("ts1", False)
    cc.label_case("ts2", False)
    cc.attach_rerun("ts1", {"trace_id": "ts1-n", "answer": "好答案"})
    cc.attach_judge("ts1", {"answer_relevancy": 0.9})
    r = client.get("/debug/stats")
    assert r.status_code == 200
    s = r.json()
    assert s["total"] == 3
    assert s["by_type"] == {"normal": 2, "chitchat": 1}
    assert s["good_count"] == 0 and s["bad_count"] == 2
    assert s["bad_to_good_rate"] == 0.5


def test_label_endpoint_admin_ok():
    """PUT label：admin 标注 normal case 生效。"""
    cc.record_case("查询订单风险", "a", [], "tl1")
    r = client.put("/debug/cases/tl1/label", json={"good": True},
                   headers={"X-Admin-Token": _admin_token()})
    assert r.status_code == 200
    assert cc.load_cases()[0]["good"] is True


def test_config_get_and_put():
    """GET /config 读关键配置；PUT 白名单键写 system_config、白名单外 400。"""
    r = client.get("/config")
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["data_source"] in ("csv", "mysql")
    assert "sim_tick_seconds" in cfg
    assert set(cfg["调试台"]) == {"case_collection_enabled", "sample_rate",
                                   "judge_enabled"}

    tid = _admin_token()
    r = client.put("/config", json={"category": "调试台", "key": "sample_rate",
                                    "value": "1.0"},
                   headers={"X-Admin-Token": tid})
    assert r.status_code == 200
    r = client.put("/config", json={"category": "调试台", "key": "evil_key",
                                    "value": "x"},
                   headers={"X-Admin-Token": tid})
    assert r.status_code == 400
