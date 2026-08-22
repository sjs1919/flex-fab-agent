"""solver.py 输出写库/指标/solver span 测试（M2 T2.6）。

persist 测试需 WSL MySQL + seed；指标/span 测试纯函数。
"""
import json
import os

import pytest

import demo.simulator.seed as seed_mod
from demo.observability.tracer import tracer
from demo.scheduler import solver
from demo.scheduler.snapshot import _fetch
from demo.tools.data import get_connection

_MATERIAL = [
    {"process": "SLA", "rate_mm_h": 50, "post_process_hours": 1},
    {"process": "MJS", "rate_mm_h": 25, "post_process_hours": 3},
]
_MACHINES = [
    {"id": "M0001", "process": "SLA", "model_type": "600", "cabin_size": 600, "max_weight": 100, "status": "空闲"},
    {"id": "M0002", "process": "SLA", "model_type": "450", "cabin_size": 450, "max_weight": 50, "status": "空闲"},
]
_PARAMS = {"part_limit": 50, "weight_limit": 600, "emergency_reserve": 0.10,
           "solver_max_time_seconds": 60}


def _part(pid, oid, material="SLA", length=100, width=80, height=60, weight=2, quantity=1):
    return {"id": pid, "order_id": oid, "material": material,
            "length": length, "width": width, "height": height, "weight": weight, "quantity": quantity}


def _order(oid, due="2026-09-10", amount=100000, penalty_rate=0.005):
    return {"id": oid, "customer_id": "C001", "amount": amount, "urgent": 0,
            "priority": 0, "due_date": due, "status": "待排队", "penalty_rate": penalty_rate}


def _batch(bid, oid, start, end, post, mid="M0001", weight=2, qty=1):
    return {"id": bid, "order_ids": [oid],
            "parts": [_part(f"P{bid}", oid, weight=weight, quantity=qty)],
            "process": "SLA", "model_type": "600", "machine_id": mid,
            "start_time": start, "end_time": end, "post_process_end": post, "source": "整批"}


def _snap(parts, orders, machines=_MACHINES, params=_PARAMS):
    return {"parts": parts, "machines": machines, "orders": orders,
            "material": _MATERIAL, "params": params}


def _schedule(*batches):
    return {"batches": list(batches), "metrics": {}, "warnings": [], "conflicts": []}


@pytest.fixture(scope="module", autouse=True)
def seeded_mysql():
    seed_mod.reset()
    os.environ["DEMO_DATA_SOURCE"] = "mysql"
    yield
    os.environ["DEMO_DATA_SOURCE"] = "csv"


def test_metrics():
    """指标口径：准交率 = 按时完成/总订单；延期清单 = 订单+天数+金额；舱利用率 = Σ件重/Σ承重。"""
    orders = [_order("ORD001", "2026-09-10"), _order("ORD002", "2026-09-10")]
    snap = _snap([_part("P1", "ORD001"), _part("P2", "ORD002")], orders)
    sched = _schedule(
        _batch("B1", "ORD001", "2026-09-01 08:00:00", "2026-09-01 10:00:00", "2026-09-05 00:00:00"),
        _batch("B2", "ORD002", "2026-09-01 12:00:00", "2026-09-01 14:00:00", "2026-09-15 08:00:00"))
    m = solver.compute_metrics(sched, snap)
    assert m["on_time_rate"] == 0.5
    assert m["on_time"] == 1 and m["total_orders"] == 2
    d = {x["order_id"]: x for x in m["delay_list"]}
    # ORD002 完成 09-15 08:00 > due 09-10 23:59 -> 延期 5 天，金额 = 100000×0.005×5 = 2500
    assert d["ORD002"]["delay_days"] == 5
    assert d["ORD002"]["delay_amount"] == 2500
    # 舱利用率 = Σ(批重×占用时长)/(Σ机承重×跨度)：
    #   B1 2kg×88h + B2 2kg×332h = 840 kg·h；M0001 承重 100 × 跨度 336h = 33600
    assert m["cabin_utilization"] == round(840 / (100 * 336), 4)
    assert 0 < m["cabin_utilization"] < 1


def test_metrics_unmet_order_in_denominator():
    """无排程订单（超尺寸等）计入准交率分母，不算按时。"""
    orders = [_order("ORD001", "2026-09-10"), _order("ORD002", "2026-09-10")]
    snap = _snap([_part("P1", "ORD001"), _part("P2", "ORD002")], orders)
    sched = _schedule(_batch("B1", "ORD001", "2026-09-01 08:00:00",
                             "2026-09-01 10:00:00", "2026-09-05 00:00:00"))
    m = solver.compute_metrics(sched, snap)
    assert m["total_orders"] == 2
    assert m["on_time"] == 1


def test_persist_versions_and_batches():
    """persist：schedule_versions 增 1 行且 result_json 可解析；batches 行数=批次数，字段完整。"""
    orders = [_order("ORD001"), _order("ORD002")]
    snap = _snap([_part("P1", "ORD001"), _part("P2", "ORD002")], orders)
    sched = _schedule(
        _batch("B1", "ORD001", "2026-09-01 08:00:00", "2026-09-01 10:00:00", "2026-09-01 11:00:00"),
        _batch("B2", "ORD002", "2026-09-01 12:00:00", "2026-09-01 14:00:00", "2026-09-01 15:00:00"))
    sched["metrics"] = solver.compute_metrics(sched, snap)

    version_id = solver.persist(sched, snap, triggered_by="initial")
    assert version_id
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM schedule_versions WHERE id=%s", (version_id,))
            rows = _fetch(cur)
            assert len(rows) == 1
            row = rows[0]
            assert row["status"] == "待审核" and row["triggered_by"] == "initial"
            parsed = json.loads(row["result_json"])
            assert len(parsed["batches"]) == 2
            cur.execute("SELECT * FROM batches WHERE schedule_version_id=%s", (version_id,))
            rows = _fetch(cur)
            assert len(rows) == 2
            for b in rows:
                assert b["approval_status"] == "待审核"
                assert b["status"] == "前道"
                assert b["process"] in ("SLA", "MJS")
                assert b["machine_id"]
                assert b["start_time"] and b["post_process_end"]
                assert json.loads(b["parts_json"])
                assert b["source"] in ("整批", "拆批")
    finally:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM batches WHERE schedule_version_id=%s", (version_id,))
                cur.execute("DELETE FROM schedule_versions WHERE id=%s", (version_id,))
            conn.commit()


def test_span_record():
    """solve 内记录 solver:run_scheduling span，含 objective/timed_out。"""
    tracer.reset()
    orders = [_order("ORD001"), _order("ORD002")]
    snap = _snap([_part("P1", "ORD001"), _part("P2", "ORD002")], orders)
    solver.solve(snap)
    spans = [s for s in tracer._spans if s.name == "solver:run_scheduling"]
    assert spans, "solve 必须记录 solver:run_scheduling span"
    attrs = spans[0].attributes
    assert "objective" in attrs
    assert "timed_out" in attrs
    assert attrs["timed_out"] is False
