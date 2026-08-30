"""forecaster.py 聚合与预测入口测试（M5a T5a.5，需 WSL MySQL）。

用独立租户 fc-test 构造已知历史（不动 seed 的 default 租户数据）。
"""
from datetime import date

import pytest

from flex_fab_agent.forecast import forecaster
from flex_fab_agent.tools import data

TENANT = "fc-test"


def _clear(order_prefix: str):
    with data.transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM parts WHERE order_id LIKE %s", (order_prefix + "%",))
            cur.execute("DELETE FROM orders WHERE id LIKE %s", (order_prefix + "%",))


def _insert_daily(order_prefix: str, start: date, daily_parts: list[int]):
    """逐日插单：每天 1 订单 1 part（SLA qty=daily_parts[i], height=100）。

    机时 = 100/50*qty = 2*qty（SLA rate=50）。件数序列 = daily_parts。
    """
    rows_o, rows_p = [], []
    for i, qty in enumerate(daily_parts):
        oid = f"{order_prefix}{i + 1:02d}"
        od = start.toordinal() + i
        d = date.fromordinal(od)
        rows_o.append((oid, "C001", 10000, 0, 0, d, date.fromordinal(od + 30),
                       "待排队", TENANT))
        rows_p.append((f"{oid}P1", oid, "P-T", "测试件", qty, "SLA",
                       100, 100, 100, 1, TENANT))
    with data.transaction() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO orders (id, customer_id, amount, urgent, priority, "
                "order_date, due_date, status, tenant_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                rows_o)
            cur.executemany(
                "INSERT INTO parts (id, order_id, product_id, name, quantity, material, "
                "length, width, height, weight, tenant_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                rows_p)


@pytest.fixture()
def constant_history(monkeypatch):
    """10 天恒定负载：每天 5 件 / 10 机时（指数平滑/MA 预测都应是恒定值）。"""
    monkeypatch.setenv("DEMO_DATA_SOURCE", "mysql")
    _clear("TESTF")
    _insert_daily("TESTF", date(2026, 8, 10), [5] * 10)
    yield
    _clear("TESTF")


def test_history_daily_constant_load(constant_history):
    """history_daily：恒定负载聚合出 10 天、每天 5 件 / 10 机时。"""
    hist = forecaster.history_daily(tenant_id=TENANT)
    assert set(hist) == {"SLA"}
    days = hist["SLA"]
    assert len(days) == 10
    assert days["2026-08-10"] == {"parts": 5.0, "hours": 10.0}
    assert days["2026-08-19"] == {"parts": 5.0, "hours": 10.0}


def test_forecast_constant_history_5_days(constant_history):
    """恒定历史 -> 预测 5 天输出 5 行、分材料件数/机时恒定；日期衔接末日后。"""
    out = forecaster.forecast(tenant_id=TENANT)
    assert out["method"] == "exponential"
    assert out["days"] == ["2026-08-20", "2026-08-21", "2026-08-22", "2026-08-23", "2026-08-24"]
    sla = out["materials"]["SLA"]
    assert len(sla) == 5
    for row in sla:
        assert row["parts"] == 5.0
        assert row["hours"] == 10.0
    assert out["note"] == ""


def test_forecast_n_days_override(constant_history):
    """n_days 显式覆盖配置窗口。"""
    out = forecaster.forecast(n_days=3, tenant_id=TENANT)
    assert len(out["days"]) == 3
    assert len(out["materials"]["SLA"]) == 3


def test_forecast_no_history(monkeypatch):
    """无历史订单 -> 空预测 + 友好说明。"""
    monkeypatch.setenv("DEMO_DATA_SOURCE", "mysql")
    out = forecaster.forecast(tenant_id="no-such-tenant")
    assert out["materials"] == {} and out["days"] == []
    assert "无历史" in out["note"]


def test_forecast_invalid_method_falls_back(monkeypatch, constant_history):
    """非法 method 回落 exponential（不抛异常）。"""
    real = forecaster.get_config
    monkeypatch.setattr(forecaster, "get_config",
                        lambda c, k, d="": "bogus" if k == "forecast_method" else real(c, k, d))
    out = forecaster.forecast(tenant_id=TENANT)
    assert out["method"] == "exponential"


def test_forecast_ma_method_trending_series(monkeypatch):
    """method=ma 切换生效：上升趋势序列（件数 1..8）-> MA(5) 预测 = 末 5 期均值 6.0
    （区别于指数平滑的 5.86，验证算法确实切换）。"""
    monkeypatch.setenv("DEMO_DATA_SOURCE", "mysql")
    real = forecaster.get_config
    monkeypatch.setattr(forecaster, "get_config",
                        lambda c, k, d="": "ma" if k == "forecast_method" else real(c, k, d))
    _clear("TESTG")
    _insert_daily("TESTG", date(2026, 8, 10), [1, 2, 3, 4, 5, 6, 7, 8])
    try:
        out = forecaster.forecast(tenant_id=TENANT)
        assert out["method"] == "ma"
        sla = out["materials"]["SLA"]
        assert len(sla) == 5
        for row in sla:
            assert row["parts"] == 6.0   # mean(4,5,6,7,8)
            assert row["hours"] == 12.0  # 2×6
    finally:
        _clear("TESTG")
