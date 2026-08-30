"""approve_schedule 驳回回退 + 并发守卫测试（定稿 §2.2/§3.C/§3.E，需 WSL MySQL）。

覆盖：通过不改订单；驳回回退订单 已审核→待排队（带 AND status='已审核' 守卫）；
驳回/通过后二次审批被「仅待审核」守卫拒绝（FOR UPDATE 串行化的可观测面）。
"""
import pytest

from flex_fab_agent.scheduler.solver import persist
from flex_fab_agent.tools import scheduler_tools
from flex_fab_agent.tools.data import get_connection

_ORDER_ID = "T-APV01"


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


def _snapshot(order_id=_ORDER_ID, status="待排队"):
    return {
        "parts": [{"id": "P-APV", "order_id": order_id, "material": "SLA",
                   "length": 100, "width": 80, "height": 60, "weight": 2, "quantity": 1}],
        "machines": [{"id": "M0001", "process": "SLA", "model_type": "600",
                      "cabin_size": 600, "max_weight": 100, "status": "空闲"}],
        "orders": [{"id": order_id, "customer_id": "C001", "amount": 100000, "urgent": 0,
                    "priority": 0, "due_date": "2026-09-10", "status": status,
                    "penalty_rate": 0.005}],
        "material": [{"process": "SLA", "rate_mm_h": 50, "post_process_hours": 1}],
        "params": {"part_limit": 50, "weight_limit": 600, "emergency_reserve": 0.10,
                   "solver_max_time_seconds": 60},
    }


def _schedule(order_id=_ORDER_ID):
    return {
        "batches": [{
            "id": "B1", "order_ids": [order_id],
            "parts": [{"part_id": "P-APV", "order_id": order_id, "material": "SLA",
                       "quantity": 1}],
            "process": "SLA", "model_type": "600", "machine_id": "M0001",
            "start_time": "2026-09-01 08:00:00", "end_time": "2026-09-01 10:00:00",
            "post_process_end": "2026-09-01 11:00:00", "source": "整批",
        }],
        "warnings": [], "conflicts": [],
        "metrics": {"status": "OPTIMAL", "objective": 1.0, "timed_out": False,
                    "solver_duration_ms": 1.0, "wall_duration_ms": 1.0,
                    "total_batches": 1, "total_parts": 1, "verify_violations": 0,
                    "on_time": 1, "total_orders": 1, "on_time_rate": 1.0,
                    "cabin_utilization": 0.1, "load_weight_hours": 1.0,
                    "capacity_weight": 100, "span_hours": 2.0, "delay_list": []},
    }


@pytest.fixture()
def pending_locked_order():
    """造 1 个待审核版本（persist 锁定订单→已审核），用后清理 + 还原订单。"""
    _exec("INSERT INTO orders (id, customer_id, amount, urgent, priority, due_date, status, "
          "tenant_id) VALUES (%s, 'C001', 100000, 0, 0, '2026-09-10', '待排队', 'default')",
          (_ORDER_ID,))
    vid = persist(_schedule(), _snapshot(), triggered_by="test-approve")
    yield vid
    _exec("DELETE FROM approvals WHERE schedule_version_id=%s", (vid,))
    _exec("DELETE FROM preprocess_tasks WHERE batch_id LIKE %s", (f"{vid}-%",))
    _exec("DELETE FROM batches WHERE schedule_version_id=%s", (vid,))
    _exec("DELETE FROM state_change_log WHERE entity_id=%s", (str(vid),))
    _exec("DELETE FROM schedule_versions WHERE id=%s", (vid,))
    _exec("DELETE FROM state_change_log WHERE entity_id=%s", (_ORDER_ID,))
    _exec("DELETE FROM orders WHERE id=%s", (_ORDER_ID,))


def test_pass_keeps_order_locked(pending_locked_order):
    """通过不改订单：审批通过后订单保持已审核（锁定），仅批次 approval_status→通过。"""
    vid = pending_locked_order
    out = scheduler_tools.approve_schedule(vid, "通过")
    assert "已审核" in out
    assert _rows("SELECT status FROM orders WHERE id=%s", (_ORDER_ID,))[0]["status"] == "已审核"
    b = _rows("SELECT approval_status FROM batches WHERE schedule_version_id=%s", (vid,))
    assert b and all(r["approval_status"] == "通过" for r in b)


def test_reject_reverts_order_to_pending(pending_locked_order):
    """驳回回退：订单 已审核→待排队（可重排），版本/批次已驳回。"""
    vid = pending_locked_order
    assert _rows("SELECT status FROM orders WHERE id=%s", (_ORDER_ID,))[0]["status"] == "已审核"
    out = scheduler_tools.approve_schedule(vid, "驳回")
    assert "已驳回" in out
    v = _rows("SELECT status FROM schedule_versions WHERE id=%s", (vid,))[0]
    assert v["status"] == "已驳回"
    b = _rows("SELECT approval_status FROM batches WHERE schedule_version_id=%s", (vid,))
    assert b and all(r["approval_status"] == "驳回" for r in b)
    assert _rows("SELECT status FROM orders WHERE id=%s", (_ORDER_ID,))[0]["status"] == "待排队"


def test_approve_after_reject_rejected(pending_locked_order):
    """守卫：驳回后再次通过被「仅待审核版本可审批」拒绝，不产生
    「订单待排队 + 版本已审核」撕裂态。"""
    vid = pending_locked_order
    scheduler_tools.approve_schedule(vid, "驳回")
    out = scheduler_tools.approve_schedule(vid, "通过")
    assert "❌" in out and "仅待审核" in out
    assert _rows("SELECT status FROM schedule_versions WHERE id=%s", (vid,))[0]["status"] == "已驳回"
    assert _rows("SELECT status FROM orders WHERE id=%s", (_ORDER_ID,))[0]["status"] == "待排队"


def test_reject_after_pass_rejected(pending_locked_order):
    """守卫：通过后再驳回同样被拒（已审核版本不可二次审批），批次保持通过。"""
    vid = pending_locked_order
    scheduler_tools.approve_schedule(vid, "通过")
    out = scheduler_tools.approve_schedule(vid, "驳回")
    assert "❌" in out and "仅待审核" in out
    assert _rows("SELECT status FROM schedule_versions WHERE id=%s", (vid,))[0]["status"] == "已审核"
    assert _rows("SELECT status FROM orders WHERE id=%s", (_ORDER_ID,))[0]["status"] == "已审核"
