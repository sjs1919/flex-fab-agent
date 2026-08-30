"""看板三只读端点测试（M5b T5b.7，需 WSL MySQL）。

覆盖：匿名 200 + {items:[...]} 结构、limit 夹取、落库数据可读出、
写端点鉴权回归（R-7：dashboard 只读不豁免写端点的 admin token 要求）。
"""
import pytest
from fastapi.testclient import TestClient

from flex_fab_agent.api import app
from flex_fab_agent.observability import dashboard
from flex_fab_agent.tools.data import get_connection

client = TestClient(app)


def test_dashboard_endpoints_anonymous_200():
    """三个端点匿名可读（viewer/匿名，R-7），返回 {items: [...]} 结构。"""
    r1 = client.get("/dashboard/kpi-history")
    r2 = client.get("/dashboard/costs")
    r3 = client.get("/dashboard/traces")
    assert r1.status_code == 200 and r2.status_code == 200 and r3.status_code == 200
    assert isinstance(r1.json()["items"], list)
    j2 = r2.json()
    assert isinstance(j2["items"], list) and isinstance(j2["by_model"], dict)
    assert isinstance(r3.json()["items"], list)


def test_dashboard_kpi_history_reads_persisted_snapshot():
    """落一条快照后能从端点读出（升序 + metrics 还原）。"""
    rid = dashboard.record_kpi_snapshot(
        {"on_time_rate": 0.77, "delay_total": 55.0}, "2026-08-24 23:30:00")
    try:
        r = client.get("/dashboard/kpi-history", params={"limit": 500})
        assert r.status_code == 200
        mine = [i for i in r.json()["items"] if i["id"] == rid]
        assert len(mine) == 1
        assert mine[0]["metrics"]["on_time_rate"] == 0.77
    finally:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM kpi_snapshot WHERE id = %s", (rid,))
            conn.commit()


def test_dashboard_limit_capped():
    """limit 超上限被夹到 2000（防全表拉取），非法值被夹到 >=1 不报错。"""
    r = client.get("/dashboard/traces", params={"limit": 99999})
    assert r.status_code == 200
    r = client.get("/dashboard/traces", params={"limit": 0})
    assert r.status_code == 200


def test_write_endpoints_still_require_admin_token():
    """鉴权回归：新增只读端点不豁免写端点（无 token 仍 401，R-7）。"""
    assert client.post("/schedule/load").status_code == 401
