"""snapshot.py 读一致性快照测试（M2 T2.1，需 WSL MySQL + seed 数据）。

覆盖：快照字段完整、system_config 空时默认参数、仅空闲设备进可用集。
"""
import os

import pytest

import demo.simulator.seed as seed_mod
from demo.scheduler import snapshot


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
    assert params["solver_max_time_seconds"] == 60
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
