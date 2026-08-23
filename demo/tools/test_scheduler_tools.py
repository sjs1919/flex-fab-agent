"""scheduler_tools.py 4 实装工具测试（M4a T4a.1，需 WSL MySQL）。

覆盖：run_scheduling 落库、query_schedule 最新/指定版本、query_sim_events
过滤、approve_schedule 通过/驳回/非法动作/版本不存在。
"""
import pytest

from demo.scheduler.snapshot import load_snapshot
from demo.scheduler.solver import persist, solve
from demo.simulator import seed as seed_mod
from demo.tools import scheduler_tools
from demo.tools.data import get_connection

_MATERIAL = [
    {"process": "SLA", "rate_mm_h": 50, "post_process_hours": 1},
]
_MACHINES = [
    {"id": "M0001", "process": "SLA", "model_type": "600", "cabin_size": 600,
     "max_weight": 100, "status": "空闲"},
]


def _rows(sql, params=()):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def _exec(sql, params=()):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    """本模块测试依赖种子订单可求解。"""
    seed_mod.reset()


@pytest.fixture()
def pending_version():
    """造一个 待审核 排产版本（persist 单事务），用后清理。"""
    snapshot = {
        "parts": [{"id": "PART00001", "order_id": "ORD001", "material": "SLA",
                   "length": 100, "width": 80, "height": 60, "weight": 2, "quantity": 1}],
        "machines": _MACHINES,
        "orders": [{"id": "ORD001", "customer_id": "C001", "amount": 100000, "urgent": 0,
                    "priority": 0, "due_date": "2026-09-10", "status": "待排队",
                    "penalty_rate": 0.005}],
        "material": _MATERIAL,
        "params": {"part_limit": 50, "weight_limit": 600, "emergency_reserve": 0.10,
                   "solver_max_time_seconds": 60},
    }
    schedule = {
        "batches": [{
            "id": "B1", "order_ids": ["ORD001"],
            "parts": [{"part_id": "PART00001", "order_id": "ORD001", "material": "SLA",
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
    vid = persist(schedule, snapshot, triggered_by="test-m4a")
    yield vid
    _exec("DELETE FROM approvals WHERE schedule_version_id=%s", (vid,))
    _exec("DELETE FROM batches WHERE schedule_version_id=%s", (vid,))
    _exec("DELETE FROM schedule_versions WHERE id=%s", (vid,))


def test_run_scheduling_persists():
    """run_scheduling：求解 + 落库（triggered_by=agent），返回版本号与指标。"""
    before = _rows("SELECT MAX(id) AS id FROM schedule_versions")[0]["id"] or 0
    out = scheduler_tools.run_scheduling()
    assert "版本" in out and "待审核" in out
    after = _rows(
        "SELECT id, triggered_by FROM schedule_versions WHERE id > %s ORDER BY id DESC",
        (before,))
    assert after, "必须落库新版本"
    assert after[0]["triggered_by"] == "agent"
    # 清理（版本号由 after 携带）
    for v in after:
        _exec("DELETE FROM batches WHERE schedule_version_id=%s", (v["id"],))
        _exec("DELETE FROM schedule_versions WHERE id=%s", (v["id"],))


def test_query_schedule_latest_and_specific(pending_version):
    """query_schedule：默认返回最新版本；指定 version_id 返回对应批次。"""
    out = scheduler_tools.query_schedule()
    assert "|" in out and "版本" in out, "排产表须以 Markdown 表格返回"
    out2 = scheduler_tools.query_schedule(version_id=pending_version)
    assert str(pending_version) in out2
    assert "M0001" in out2, "批次行须含设备"


def test_query_sim_events_filter():
    """query_sim_events：按 event_type/status 过滤。"""
    _exec("DELETE FROM sim_events")
    _exec("INSERT INTO sim_events (sim_time, event_type, payload_json, status) "
          "VALUES ('2026-09-01 08:00:00', 'new_order', '{}', 'fired'), "
          "('2026-09-02 08:00:00', 'machine_failure', '{}', 'scheduled')")
    out = scheduler_tools.query_sim_events(event_type="new_order")
    assert "new_order" in out and "machine_failure" not in out
    out2 = scheduler_tools.query_sim_events(status="scheduled")
    assert "machine_failure" in out2 and "new_order" not in out2
    _exec("DELETE FROM sim_events")


def test_approve_schedule_pass(pending_version):
    """审批通过：版本已审核 + 批次通过 + approvals 行。"""
    out = scheduler_tools.approve_schedule(pending_version, "通过", approver="张三")
    assert "已审核" in out
    v = _rows("SELECT status FROM schedule_versions WHERE id=%s", (pending_version,))[0]
    assert v["status"] == "已审核"
    b = _rows("SELECT approval_status FROM batches WHERE schedule_version_id=%s",
              (pending_version,))
    assert b and all(r["approval_status"] == "通过" for r in b)
    a = _rows("SELECT approver, action FROM approvals WHERE schedule_version_id=%s",
              (pending_version,))
    assert a and a[0]["approver"] == "张三" and a[0]["action"] == "通过"


def test_approve_schedule_reject(pending_version):
    """驳回：版本已驳回 + 批次驳回 + approvals 行。"""
    out = scheduler_tools.approve_schedule(pending_version, "驳回")
    assert "已驳回" in out
    v = _rows("SELECT status FROM schedule_versions WHERE id=%s", (pending_version,))[0]
    assert v["status"] == "已驳回"
    b = _rows("SELECT approval_status FROM batches WHERE schedule_version_id=%s",
              (pending_version,))
    assert b and all(r["approval_status"] == "驳回" for r in b)


def test_approve_schedule_invalid_action(pending_version):
    """非法动作：报错且不改状态。"""
    out = scheduler_tools.approve_schedule(pending_version, "乱写")
    assert "❌" in out
    v = _rows("SELECT status FROM schedule_versions WHERE id=%s", (pending_version,))[0]
    assert v["status"] == "待审核"


def test_approve_schedule_not_found():
    """版本不存在：报错。"""
    out = scheduler_tools.approve_schedule(999999, "通过")
    assert "❌" in out
