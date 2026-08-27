"""GET /scheduler/status 端点测试。"""
from fastapi.testclient import TestClient
from demo.api import app


def test_scheduler_status_returns_state():
    """status 端点返回调度器运行态（enabled/interval/runs 等）。"""
    client = TestClient(app)
    r = client.get("/scheduler/status")
    assert r.status_code == 200
    data = r.json()
    assert "enabled" in data and "interval_ticks" in data
    assert data["approve_top_n"] >= 1
