"""snapshot.py 读一致性快照测试（M2 T2.1，需 WSL MySQL + seed 数据）。

覆盖：快照字段完整、system_config 空时默认参数、仅空闲设备进可用集。
"""
import os

import pytest

import flex_fab_agent.simulator.seed as seed_mod
from flex_fab_agent.scheduler import snapshot


@pytest.fixture(scope="module", autouse=True)
def seeded_mysql():
    seed_mod.reset()
    os.environ["DEMO_DATA_SOURCE"] = "mysql"
    yield
    os.environ["DEMO_DATA_SOURCE"] = "csv"


def test_snapshot_load_fields():
    """快照字段完整：orders 含 amount/due_date/penalty_rate；parts 含三边/件重/材料。"""
    snap = snapshot.load_snapshot()
    assert snap["orders"], "快照无订单"
    o = snap["orders"][0]
    assert {"id", "customer_id", "amount", "urgent", "priority", "due_date", "status", "penalty_rate"}.issubset(o)
    p = snap["parts"][0]
    assert {"id", "order_id", "material", "length", "width", "height", "weight", "quantity"}.issubset(p)
    m = snap["machines"][0]
    assert {"id", "process", "model_type", "cabin_size", "max_weight"}.issubset(m)
    mat = snap["material"][0]
    assert {"process", "rate_mm_h", "post_process_hours"}.issubset(mat)


def test_snapshot_params_default():
    """system_config 空表 → 4 个默认参数生效。"""
    params = snapshot.get_solver_params()
    assert params["solver_max_time_seconds"] == 20
    assert params["emergency_reserve"] == 0.10
    assert params["part_limit"] == 50
    assert params["weight_limit"] == 600


def test_snapshot_machines_filter():
    """仅 status='空闲' 进可用集（非空闲被排除）。"""
    raw = [
        {"id": "M0001", "status": "空闲", "process": "SLA"},
        {"id": "M0002", "status": "打印中", "process": "MJS"},
        {"id": "M0003", "status": "故障", "process": "SLM"},
        {"id": "M0004", "status": "维修中", "process": "SLA"},
    ]
    available = snapshot._normalize_machines(raw)
    ids = {m["id"] for m in available}
    assert ids == {"M0001"}
    assert all(m["status"] == "空闲" for m in available)


def test_snapshot_available_machine_count():
    """seed 全空闲 → 7 台设备全部可用。"""
    snap = snapshot.load_snapshot()
    assert len(snap["machines"]) == 7
    assert {m["id"] for m in snap["machines"]} == {f"M000{i}" for i in range(1, 8)}


# ---- 定稿 v1 §3.D 幂等：仅待排队订单（+其零件）进快照 ----

def test_snapshot_excludes_non_queueing_orders():
    """D 幂等：status='待排队' 之外订单不进快照，且其零件被排除——
    防 persist 锁定后旧订单/零件再被 pack_parts 打包进后续版本（重复打印）。"""
    conn = seed_mod._connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM orders ORDER BY id LIMIT 1")
            oid = cur.fetchone()[0]
            cur.execute("UPDATE orders SET status='已审核' WHERE id=%s", (oid,))
            cur.execute("SELECT COUNT(*) FROM parts WHERE order_id=%s", (oid,))
            part_count = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    try:
        snap = snapshot.load_snapshot()
        assert {o["id"] for o in snap["orders"]} != {oid} and oid not in {o["id"] for o in snap["orders"]}
        assert oid not in {p["order_id"] for p in snap["parts"]}
    finally:
        conn = seed_mod._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE orders SET status='待排队' WHERE id=%s", (oid,))
            conn.commit()
        finally:
            conn.close()
    assert part_count > 0  # 防误判：该订单确有零件，过滤生效才非空
