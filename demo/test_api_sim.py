"""api.py /sim/* 与 /schedule/* 端点测试（M4a T4a.5，需 WSL MySQL）。

覆盖：/health 补 sim 状态、/sim/start->status->stop 生命周期、
/schedule/latest 返回排产表、/schedule/load 强制 admin token（R-7 正反例）。
"""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from demo.api import app
from demo.auth.token_exchange import STS
from demo.simulator import clock
from demo.tools.data import get_connection

T0 = datetime(2026, 9, 1, 8, 0, 0)
client = TestClient(app)


def _exec(sql, params=()):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()


@pytest.fixture(autouse=True)
def _env():
    """固定时钟起点 + 清事件；测试结束确保心跳停止。"""
    _exec("DELETE FROM sim_events")
    with get_connection() as conn:
        clock.init_clock(conn, T0)
        conn.commit()
    yield
    client.post("/sim/stop")


def test_health_reports_sim_and_tools():
    r = client.get("/health")
    assert r.status_code == 200
    j = r.json()
    assert j["tools"] == 18
    assert "sim" in j and "running" in j["sim"]


def test_sim_start_status_stop():
    r = client.post("/sim/start")
    assert r.status_code == 200 and r.json()["running"] is True
    r = client.get("/sim/status")
    assert r.status_code == 200
    j = r.json()
    assert j["running"] is True
    assert j["sim_time"] is not None
    r = client.post("/sim/stop")
    assert r.json()["running"] is False
    assert client.get("/sim/status").json()["running"] is False


def test_schedule_latest():
    r = client.get("/schedule/latest")
    assert r.status_code == 200
    j = r.json()
    assert "version" in j and isinstance(j["batches"], list)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(id) FROM schedule_versions")
            max_id = cur.fetchone()[0]
    if max_id:
        assert j["version"]["id"] == max_id
        assert all("machine_id" in b for b in j["batches"])


def test_schedule_load_requires_admin_token():
    """R-7 反例：无 token 401。"""
    r = client.post("/schedule/load")
    assert r.status_code == 401
    assert "admin" in r.json()["detail"]


def test_schedule_load_non_admin_forbidden(monkeypatch):
    """R-7 反例：scheduler token 403（求解被 monkeypatch，聚焦鉴权路径）。"""
    monkeypatch.setattr("demo.tools.scheduler_tools.run_scheduling",
                        lambda **kw: "不应执行到这里")
    tid = STS().issue_user_token("sched-api", "scheduler")
    r = client.post("/schedule/load", headers={"X-Admin-Token": tid})
    assert r.status_code == 403


def test_schedule_load_admin_ok(monkeypatch):
    """R-7 正例：admin token 200，run_scheduling 被调用（triggered_by=api）。"""
    captured = {}

    def _fake(triggered_by="agent"):
        captured["triggered_by"] = triggered_by
        return "✅ 排产完成：版本 999（待审核）"

    monkeypatch.setattr("demo.tools.scheduler_tools.run_scheduling", _fake)
    tid = STS().issue_user_token("admin-api", "admin")
    r = client.post("/schedule/load", headers={"X-Admin-Token": tid})
    assert r.status_code == 200
    assert "版本" in r.json()["result"]
    assert captured["triggered_by"] == "api"
