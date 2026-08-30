"""model.py 贪心装箱测试（M2 T2.3）。

覆盖：无 part 丢失、C2 容量不超、超尺寸预警、整批优先/超舱拆批 source。
"""
import os

import pytest

import flex_fab_agent.simulator.seed as seed_mod
from flex_fab_agent.scheduler import model
from flex_fab_agent.scheduler.snapshot import load_snapshot

_MATERIAL = [
    {"process": "SLA", "rate_mm_h": 50, "post_process_hours": 1},
    {"process": "MJS", "rate_mm_h": 25, "post_process_hours": 3},
    {"process": "SLM", "rate_mm_h": 15, "post_process_hours": 12},
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


def _order(oid, due="2026-09-10", priority=0):
    return {"id": oid, "amount": 100000, "due_date": due, "priority": priority, "status": "待排队"}


def _snap(parts, orders, machines=_MACHINES):
    return {"parts": parts, "machines": machines, "orders": orders,
            "material": _MATERIAL, "params": _PARAMS}


@pytest.fixture(scope="module", autouse=True)
def seeded_mysql():
    seed_mod.reset()
    os.environ["DEMO_DATA_SOURCE"] = "mysql"
    yield
    os.environ["DEMO_DATA_SOURCE"] = "csv"


def test_pack_no_loss():
    """seed 数据：可装件全部入批，无丢失（预警件不入批；超舱行按件数计）。"""
    snap = load_snapshot()
    batches, warnings = model.pack_parts(snap)
    packed_qty = sum(p["quantity"] for b in batches for p in b["parts"])
    warned_qty = sum(w["quantity"] if "quantity" in w else 1 for w in warnings)
    total_qty = sum(p["quantity"] for p in snap["parts"])
    assert packed_qty == total_qty - warned_qty, \
        f"装箱丢失：{packed_qty} != {total_qty} - {warned_qty}"
    assert packed_qty >= 340  # 大部分零件成功装箱


def test_pack_oversize_warning():
    """seed 超尺寸样例 PART00001 入预警，不入批。"""
    snap = load_snapshot()
    batches, warnings = model.pack_parts(snap)
    w_ids = {w["part_id"] for w in warnings}
    assert "PART00001" in w_ids
    assert "PART00001" not in {p["part_id"] for b in batches for p in b["parts"]}


def test_pack_capacity():
    """C2 容量：每批单边/件数/件重不超对应机型（(process, model_type)）。"""
    snap = load_snapshot()
    batches, _ = model.pack_parts(snap)
    cap = {}
    for m in snap["machines"]:
        cap.setdefault((m["process"], m["model_type"]),
                       {"cabin_size": m["cabin_size"], "max_weight": m["max_weight"]})
    for b in batches:
        c = cap[(b["process"], b["model_type"])]
        for p in b["parts"]:
            assert max(p["length"], p["width"], p["height"]) <= c["cabin_size"]
        assert sum(p["weight"] * p["quantity"] for p in b["parts"]) <= c["max_weight"]
        assert sum(p["quantity"] for p in b["parts"]) <= snap["params"]["part_limit"]


def test_pack_same_order_preferred():
    """整批优先：同订单 5 个小 part 全进同一批（容量够，不拆）。"""
    parts = [_part(f"P{i}", "ORD001", weight=1) for i in range(1, 6)]
    snap = _snap(parts, [_order("ORD001")])
    batches, _ = model.pack_parts(snap)
    assert len(batches) == 1
    assert len(batches[0]["parts"]) == 5
    assert batches[0]["source"] == "整批"


def test_pack_split_source():
    """超舱可拆：单件重 30，SLA450 承重 50 → 每件一批，后续批 source='拆批'。"""
    parts = [_part(f"P{i}", "ORD001", weight=30) for i in range(1, 4)]
    snap = _snap(parts, [_order("ORD001")])
    batches, _ = model.pack_parts(snap)
    assert len(batches) >= 2
    assert any(b["source"] == "拆批" for b in batches)
    assert all(p["order_id"] == "ORD001" for b in batches for p in b["parts"])
