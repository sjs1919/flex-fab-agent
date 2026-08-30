"""solver.py 输出写库/指标/solver span 测试（M2 T2.6 + 定稿 v1 §5/§6 persist 行）。

persist 测试需 WSL MySQL + seed；指标/span 测试纯函数。
"""
import json
import os
from datetime import datetime

import pytest

import flex_fab_agent.simulator.seed as seed_mod
from flex_fab_agent.observability.tracer import tracer
from flex_fab_agent.scheduler import solver
from flex_fab_agent.scheduler.snapshot import _fetch
from flex_fab_agent.scheduler.solver import PersistConcurrentLockError
from flex_fab_agent.simulator.clock import init_clock
from flex_fab_agent.tools.data import get_connection

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
_T0 = datetime(2026, 9, 1, 0, 0, 0)  # sim 起始时刻（建版锚点断言基准）


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


def _fresh():
    """persist 测试前置（spec §6 文末约定）：seed 全量重建（联动清排产链路表，
    还原订单为待排队）+ 初始化 sim 时钟 T0——每个 persist 用例自隔离，不留跨用例污染。"""
    seed_mod.reset()
    conn = seed_mod._connect()
    try:
        init_clock(conn, _T0)
        conn.commit()
    finally:
        conn.close()


def _version_count() -> int:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM schedule_versions")
        return cur.fetchone()[0]


@pytest.fixture(scope="module", autouse=True)
def seeded_mysql():
    seed_mod.reset()
    conn = seed_mod._connect()
    try:
        init_clock(conn, _T0)
        conn.commit()
    finally:
        conn.close()
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
    """persist：schedule_versions 增 1 行且 result_json 可解析；batches 行数=批次数，字段完整；
    订单被原子锁定为已审核；每有解批次生成 1 条 preprocess_tasks（C9 + 分摊）。"""
    _fresh()
    orders = [_order("ORD001"), _order("ORD002")]
    snap = _snap([_part("P1", "ORD001"), _part("P2", "ORD002")], orders)
    sched = _schedule(
        _batch("B1", "ORD001", "2026-09-01 08:00:00", "2026-09-01 10:00:00", "2026-09-01 11:00:00"),
        _batch("B2", "ORD002", "2026-09-01 12:00:00", "2026-09-01 14:00:00", "2026-09-01 15:00:00"))
    sched["metrics"] = solver.compute_metrics(sched, snap)

    version_id = solver.persist(sched, snap, triggered_by="initial")
    assert version_id
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
        batch_start = {b["id"]: b["start_time"] for b in rows}
        for b in rows:
            assert b["approval_status"] == "待审核"
            assert b["status"] == "前道"
            assert b["process"] in ("SLA", "MJS")
            assert b["machine_id"]
            assert b["start_time"] and b["post_process_end"]
            assert json.loads(b["parts_json"])
            assert b["source"] in ("整批", "拆批")
        # 前道任务：行数=有解批次行数；man_hours 含 share=round(0.5/2,4)=0.25（非 0.5/批次）；
        # end_time=批次 start_time（C9）、start_time=end−日历时长折算、assigned_workers=1
        cur.execute("SELECT * FROM preprocess_tasks WHERE batch_id IN "
                    "(SELECT id FROM batches WHERE schedule_version_id=%s)", (version_id,))
        ptasks = _fetch(cur)
        assert len(ptasks) == 2
        for pt in ptasks:
            assert pt["assigned_workers"] == 1
            assert pt["start_time"] and pt["end_time"]
            assert pt["end_time"] == batch_start[pt["batch_id"]]  # C9：前道完成=打印开始
            assert pt["start_time"] < pt["end_time"]
            # 件数=1、SLA 件人效 15 → 1/15 + 0.25 = 0.3167 → DECIMAL(8,2)=0.32
            assert round(float(pt["man_hours"]), 2) == 0.32
        # 订单锁定：persist 事务开头条件 UPDATE 待排队→已审核
        cur.execute("SELECT status FROM orders WHERE id IN ('ORD001','ORD002')")
        assert {r[0] for r in cur.fetchall()} == {"已审核"}


def test_persist_concurrent_double():
    """并发双 persist（顺序连调两次确定性写法，spec §6 文末约定）：第二次待锁定订单已非
    待排队 → 受影响 0 行 → 整事务回滚、版本数/批次/前道行数不变、无半写。"""
    _fresh()
    snap = _snap([_part("P1", "ORD001")], [_order("ORD001")])
    sched = _schedule(
        _batch("B1", "ORD001", "2026-09-01 08:00:00", "2026-09-01 10:00:00", "2026-09-01 11:00:00"))
    assert solver.persist(sched, snap)
    with pytest.raises(PersistConcurrentLockError):
        solver.persist(sched, snap)  # ORD001 已已审核 → 受影响 0 < 1 → ROLLBACK
    assert _version_count() == 1
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM batches")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT COUNT(*) FROM preprocess_tasks")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT status FROM orders WHERE id='ORD001'")
        assert cur.fetchone()[0] == "已审核"


def test_persist_partial_solved():
    """工艺组级部分成功（u-d-1，手工混合有解+无解批次 result）：建版本只含有解批次，
    无解批次订单不锁定、保持待排队下轮重排。"""
    _fresh()
    snap = _snap([_part("P1", "ORD001"), _part("P2", "ORD002")],
                 [_order("ORD001"), _order("ORD002")])
    solved = _batch("B1", "ORD001", "2026-09-01 08:00:00", "2026-09-01 10:00:00", "2026-09-01 11:00:00")
    unsolved = _batch("B2", "ORD002", None, None, None)  # start_time 为空（不可行组残留）
    version_id = solver.persist(_schedule(solved, unsolved), snap)
    assert version_id
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM batches WHERE schedule_version_id=%s", (version_id,))
        batch_ids = [r[0] for r in cur.fetchall()]
        assert len(batch_ids) == 1 and batch_ids[0].endswith("-B1")
        cur.execute("SELECT status FROM orders WHERE id='ORD001'")
        assert cur.fetchone()[0] == "已审核"  # 有解订单锁定
        cur.execute("SELECT status FROM orders WHERE id='ORD002'")
        assert cur.fetchone()[0] == "待排队"  # 无解订单保持待排队


def test_persist_all_infeasible_skips_version():
    """全不可行（result['batches'] 全无 start_time）：不建版本、版本数不随轮次增长、
    相关订单全部保持待排队。"""
    _fresh()
    snap = _snap([_part("P1", "ORD001")], [_order("ORD001")])
    sched = _schedule(_batch("B1", "ORD001", None, None, None))
    assert solver.persist(sched, snap) is None
    assert _version_count() == 0
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT status FROM orders WHERE id='ORD001'")
        assert cur.fetchone()[0] == "待排队"


def test_persist_empty_pool_returns_none():
    """空订单池（result['batches'] 为空）：跳过建版本返回 None、schedule_versions 行数不变。"""
    _fresh()
    assert solver.persist(_schedule(), _snap([], [])) is None
    assert _version_count() == 0


def test_persist_sim_anchor_written():
    """建版 sim 时刻快照写入 state_change_log（entity_type='version'/field='created'/
    source='solver'，FIFO 计龄锚点唯一通道）。"""
    _fresh()
    snap = _snap([_part("P1", "ORD001")], [_order("ORD001")])
    sched = _schedule(
        _batch("B1", "ORD001", "2026-09-01 08:00:00", "2026-09-01 10:00:00", "2026-09-01 11:00:00"))
    version_id = solver.persist(sched, snap)
    assert version_id
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT sim_time, entity_type, entity_id, `field`, source "
                    "FROM state_change_log WHERE entity_type='version' AND entity_id=%s",
                    (str(version_id),))
        rows = _fetch(cur)
        assert len(rows) == 1
        assert rows[0]["field"] == "created"
        assert rows[0]["source"] == "solver"
        assert rows[0]["sim_time"] == _T0  # init_clock(T0) 快照即锚点


def test_persist_sim_clock_missing_skips_anchor():
    """sim_clock 未初始化（无行）：persist 不抛错、跳过写锚点、版本照常建立。"""
    _fresh()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM sim_clock")
        conn.commit()
    snap = _snap([_part("P1", "ORD001")], [_order("ORD001")])
    sched = _schedule(
        _batch("B1", "ORD001", "2026-09-01 08:00:00", "2026-09-01 10:00:00", "2026-09-01 11:00:00"))
    version_id = solver.persist(sched, snap)
    assert version_id
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM state_change_log "
                    "WHERE entity_type='version' AND entity_id=%s", (str(version_id),))
        assert cur.fetchone()[0] == 0  # 无锚点但不抛错


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
