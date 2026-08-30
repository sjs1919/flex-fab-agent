"""solver.py 求解入口测试（M2 T2.5，纯函数不连库）。

覆盖：样例求解 part 全覆盖 + verify 0 违规；R-D1 预算耗尽返次优 + timed_out；
无可行解输出冲突订单清单（不静默空结果）。
"""
import time

import pytest

import flex_fab_agent.simulator.seed as seed_mod
from flex_fab_agent.scheduler import model, solver, verify
from flex_fab_agent.scheduler.snapshot import load_snapshot

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


def _snap(parts, orders, machines=_MACHINES, params=_PARAMS):
    return {"parts": parts, "machines": machines, "orders": orders,
            "material": _MATERIAL, "params": params}


@pytest.fixture(scope="module", autouse=True)
def seeded_mysql():
    seed_mod.reset()
    os_environ = dict(__import__("os").environ)
    __import__("os").environ["FLEX_FAB_AGENT_DATA_SOURCE"] = "mysql"
    yield
    __import__("os").environ.clear()
    __import__("os").environ.update(os_environ)


def test_solve_sample():
    """小样例：solve -> part 全覆盖 + verify 0 违规 + meta 齐全。"""
    parts = [_part(f"P{i}", "ORD001") for i in range(1, 4)] + \
            [_part(f"Q{i}", "ORD002") for i in range(1, 4)]
    orders = [
        {"id": "ORD001", "amount": 100000, "due_date": "2026-09-10", "priority": 0, "status": "待排队"},
        {"id": "ORD002", "amount": 50000, "due_date": "2026-09-12", "priority": 0, "status": "待排队"},
    ]
    result = solver.solve(_snap(parts, orders))
    packed = {p["part_id"] for b in result["batches"] for p in b["parts"]}
    assert packed == {f"P{i}" for i in range(1, 4)} | {f"Q{i}" for i in range(1, 4)}
    assert verify.verify(result, _snap(parts, orders)) == []
    m = result["metrics"]
    assert m["status"] in ("OPTIMAL", "FEASIBLE")
    assert m["timed_out"] is False
    assert m["solver_duration_ms"] > 0
    assert m["total_batches"] >= 1


def test_solve_seed_full_coverage():
    """seed 数据：可装 part 全进批次 + verify 0 硬违规（与 158 批全量验证对齐）。"""
    snap = load_snapshot()
    result = solver.solve(snap)
    packed_qty = sum(p["quantity"] for b in result["batches"] for p in b["parts"])
    warned_qty = sum(w.get("quantity", 1) for w in result["warnings"])
    total_qty = sum(p["quantity"] for p in snap["parts"])
    assert packed_qty == total_qty - warned_qty
    assert verify.verify(result, snap) == []
    # 20s 预算（2026-08-27 性能优化）下 CP-SAT 可能 UNKNOWN，贪心兜底解已覆盖全 + verify 空
    # （质量由上面两条断言保证）；OPTIMAL/FEASIBLE 为 CP-SAT 收敛。
    assert result["metrics"]["status"] in ("OPTIMAL", "FEASIBLE", "UNKNOWN")


def test_solve_timed_out():
    """R-D1：max_time_in_seconds=1 + 大批次集 -> 次优可行解 + timed_out=true，不抛错。"""
    # part_limit=2 -> 每批 2 件；2 订单各 qty=60 -> 60 批，1s 内无法证明最优
    parts = [_part("P1", "ORD001", weight=2, quantity=60),
             _part("P2", "ORD002", weight=2, quantity=60)]
    orders = [
        {"id": "ORD001", "amount": 100000, "due_date": "2026-09-10", "priority": 0, "status": "待排队"},
        {"id": "ORD002", "amount": 50000, "due_date": "2026-09-15", "priority": 0, "status": "待排队"},
    ]
    snap = _snap(parts, orders, params=dict(_PARAMS, part_limit=2, solver_max_time_seconds=1))
    t0 = time.perf_counter()
    result = solver.solve(snap)
    wall = time.perf_counter() - t0
    m = result["metrics"]
    assert m["status"] == "FEASIBLE"
    assert m["timed_out"] is True
    assert m["solver_duration_ms"] >= 1000
    assert wall < 120  # 预算耗尽立即返回，不无限等
    assert verify.verify(result, snap) == []


def test_solve_infeasible_conflicts():
    """无可行解：无可用设备 -> 冲突订单清单非空，不静默空结果。"""
    parts = [_part("P1", "ORD001"), _part("P2", "ORD002")]
    orders = [
        {"id": "ORD001", "amount": 100000, "due_date": "2026-09-10", "priority": 0, "status": "待排队"},
        {"id": "ORD002", "amount": 50000, "due_date": "2026-09-12", "priority": 0, "status": "待排队"},
    ]
    result = solver.solve(_snap(parts, orders, machines=[]))
    assert result["batches"] == []
    assert result["conflicts"], "无可行解必须输出冲突清单，不得静默空结果"
    order_ids = {oid for c in result["conflicts"] for oid in c["order_ids"]}
    assert order_ids == {"ORD001", "ORD002"}
    # 预警清单同步可见（不静默）
    assert result["warnings"]


def test_solve_oversize_conflict():
    """超尺寸零件：入预警 + 冲突清单含其订单，不入排产表。"""
    parts = [_part("P1", "ORD001"), _part("P_BIG", "ORD001", length=650, width=200, height=150)]
    orders = [{"id": "ORD001", "amount": 100000, "due_date": "2026-09-10", "priority": 0, "status": "待排队"}]
    snap = _snap(parts, orders)
    result = solver.solve(snap)
    in_schedule = {p["part_id"] for b in result["batches"] for p in b["parts"]}
    assert "P_BIG" not in in_schedule
    assert any(w["part_id"] == "P_BIG" for w in result["warnings"])
    assert "ORD001" in {oid for c in result["conflicts"] for oid in c["order_ids"]}
