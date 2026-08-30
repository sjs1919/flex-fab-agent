"""events.py B 层分布预排 + 随机插单测试（M3 T3.4，需 WSL MySQL）。

覆盖：默认参数、指数分布预排、随机插单 1~10 单（数量/材料/体积/交期随机）、
开工预排（每设备故障 + 全局到达类事件）。
"""
from datetime import datetime, timedelta

import pytest

from flex_fab_agent.simulator import events
from flex_fab_agent.tools.data import get_connection

T0 = datetime(2026, 9, 1, 8, 0, 0)


def _exec(sql, params=()):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()


def _rows(sql, params=()):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


@pytest.fixture(autouse=True)
def _clean():
    _exec("DELETE FROM sim_events")
    _exec("DELETE FROM state_change_log WHERE entity_id LIKE 'SIM%%'")
    _exec("DELETE FROM parts WHERE id LIKE 'SIMP%%'")
    _exec("DELETE FROM orders WHERE id LIKE 'SIM%%'")
    yield
    _exec("DELETE FROM sim_events")
    _exec("DELETE FROM state_change_log WHERE entity_id LIKE 'SIM%%'")
    _exec("DELETE FROM parts WHERE id LIKE 'SIMP%%'")
    _exec("DELETE FROM orders WHERE id LIKE 'SIM%%'")


def test_get_sim_params_default():
    """system_config 无模拟参数 -> 缺省常量（mtbf 96h / mttr 2h / 到达率 2 单/天）。"""
    with get_connection() as conn:
        p = events.get_sim_params(conn)
    assert p["machine_mtbf_h"] == 96
    assert p["machine_mttr_h"] == 2
    assert p["order_arrival_rate"] == 2
    assert p["scrap_rate"] == 0.05
    assert p["new_order_max"] == 10


def test_schedule_next_exponential(monkeypatch):
    """指数分布预排：mock random 确定间隔 -> sim_events(scheduled) sim_time = from + 间隔。"""
    monkeypatch.setattr(events.random, "expovariate", lambda lam: 1 / lam)  # 间隔 = 均值
    with get_connection() as conn:
        with conn.cursor() as cur:
            events.schedule_next(cur, "machine_failure", T0,
                                 {"machine_mtbf_h": 96}, payload={"machine_id": "M0001"})
        conn.commit()
    rows = _rows("SELECT sim_time, event_type, status, payload_json FROM sim_events")
    assert len(rows) == 1
    assert rows[0]["sim_time"] == T0 + timedelta(hours=96)
    assert rows[0]["event_type"] == "machine_failure"
    assert rows[0]["status"] == "scheduled"
    assert "M0001" in rows[0]["payload_json"]


def test_generate_new_order_random_1to10(monkeypatch):
    """用户需求核心：每次触发插 1~10 单随机订单（数量/材料/体积/交期随机）。"""
    # 固定随机序列跑多次，统计每次插单数均在 [1, 10]
    counts = []
    with get_connection() as conn:
        for _ in range(5):
            with conn.cursor() as cur:
                n = events.generate_new_order(conn, cur, T0)
            conn.commit()
            counts.append(n)
    assert all(1 <= c <= 10 for c in counts), counts
    total = sum(counts)
    orders = _rows(
        "SELECT id, customer_id, amount, due_date, status FROM orders WHERE id LIKE 'SIM%%'")
    assert len(orders) == total
    assert all(o["status"] == "待排队" for o in orders)
    assert all(o["customer_id"] in ("C001", "C002", "C003", "C004", "C005") for o in orders)
    parts = _rows(
        "SELECT material, length, width, height, weight, quantity FROM parts "
        "WHERE id LIKE 'SIMP%%'")
    assert parts, "插单必须带 parts"
    assert all(p["material"] in ("SLA", "MJS", "SLM") for p in parts)
    for p in parts:
        lo, hi = events.PART_DIM_RANGE[p["material"]]
        assert lo <= max(p["length"], p["width"], p["height"]) <= hi
        assert p["quantity"] >= 1
    # 交期在未来 7-30 天窗口内
    for o in orders:
        days = (o["due_date"] - T0.date()).days
        assert 7 <= days <= 30


def test_generate_new_order_bounds(monkeypatch):
    """边界：mock randint=1 / randint=10 -> 插单数恰为 1 与 10。"""
    import random as _random
    with get_connection() as conn:
        monkeypatch.setattr(events.random, "randint", lambda a, b: 1)
        with conn.cursor() as cur:
            assert events.generate_new_order(conn, cur, T0) == 1
        conn.commit()
        _exec("DELETE FROM parts WHERE id LIKE 'SIMP%%'")
        _exec("DELETE FROM orders WHERE id LIKE 'SIM%%'")
        monkeypatch.setattr(events.random, "randint", lambda a, b: 10 if b == 10 else 1)
        with conn.cursor() as cur:
            assert events.generate_new_order(conn, cur, T0) == 10
        conn.commit()


def test_seed_schedule_events():
    """开工预排：7 台设备各 1 条 machine_failure + new_order/leave/restock/order_change。"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            events.seed_schedule_events(cur, T0)
        conn.commit()
    rows = _rows("SELECT event_type, COUNT(*) AS n FROM sim_events "
                 "WHERE status='scheduled' GROUP BY event_type")
    by_type = {r["event_type"]: r["n"] for r in rows}
    assert by_type.get("machine_failure") == 7
    for t in ("new_order", "leave", "restock", "order_change"):
        assert by_type.get(t) >= 1, t
    # 预排事件时间均在开工时刻之后
    all_rows = _rows("SELECT sim_time FROM sim_events")
    assert all(r["sim_time"] > T0 for r in all_rows)
