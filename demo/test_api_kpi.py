"""api.py /order/{id}/tracking 与 /kpi 端点测试（M4b T4b.8，需 WSL MySQL）。

覆盖：订单跟踪 200 + 结构、不存在订单 404、/kpi 200 + 5 项指标齐全。
端点内部 load_orders/load_machines 等按 DEMO_DATA_SOURCE 路由，必须切 mysql
（英文列名）才能与 get_connection 的 MySQL 表一致（同 test_scheduler_tools）。
"""
import pytest
from fastapi.testclient import TestClient

from demo.api import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _mysql_source(monkeypatch):
    monkeypatch.setenv("DEMO_DATA_SOURCE", "mysql")
    yield


def test_order_tracking_ok():
    r = client.get("/order/ORD001/tracking")
    assert r.status_code == 200
    j = r.json()
    assert j["order_id"] == "ORD001"
    # 报告含当前环节/批次/前面单据任一关键段
    assert any(k in j["report"] for k in
               ["批次", "未排入批次", "前面单据", "前面无同工艺单据"])


def test_order_tracking_not_found():
    r = client.get("/order/ORD9999/tracking")
    assert r.status_code == 404
    assert "订单不存在" in r.json()["message"]


def test_kpi_endpoint_reports_all_five_indicators():
    r = client.get("/kpi")
    assert r.status_code == 200
    report = r.json()["report"]
    for name in ["准交率", "延期金额", "舱利用率", "良率", "前道瓶颈占用"]:
        assert name in report
