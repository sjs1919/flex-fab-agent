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


# ---- M4b T4b.3：query_load_assessment / query_ctp 实装 ----

@pytest.fixture()
def mysql_source():
    """切 MySQL 数据源（评估读业务库）。"""
    import os
    os.environ["DEMO_DATA_SOURCE"] = "mysql"
    yield
    os.environ.pop("DEMO_DATA_SOURCE", None)


def test_query_load_assessment_four_sections(mysql_source):
    """query_load_assessment 输出含四段 + 三区制颜色 + 前道人池。"""
    out = scheduler_tools.query_load_assessment()
    for marker in ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"):
        assert marker in out
    assert "三区制" in out
    assert any(c in out for c in ("绿", "黄", "红"))
    assert "前道人池" in out and "净产能" in out
    assert "T 窗口" in out


def test_query_ctp_params_and_response(mysql_source):
    """query_ctp：缺参报错；有效参数返回承诺交期；超尺寸/未知工艺直接预警。"""
    out = scheduler_tools.query_ctp()
    assert "❌" in out and "参数不完整" in out
    out = scheduler_tools.query_ctp(material="SLA", quantity=10, height_mm=100)
    assert "CTP" in out and "瓶颈" in out
    out2 = scheduler_tools.query_ctp(material="SLA", quantity=10, height_mm=100,
                                     due_date="2026-12-31")
    assert "满足交期" in out2 or "无法满足交期" in out2
    out3 = scheduler_tools.query_ctp(material="SLA", quantity=1, height_mm=650)
    assert "超尺寸" in out3
    out4 = scheduler_tools.query_ctp(material="CNC", quantity=1, height_mm=100)
    assert "未知工艺" in out4


# ---- M4b T4b.4：query_order_tracking / query_preprocess_load 实装 ----

def _extract_ahead(out):
    """解析"前面单据"表格数据行 → [(订单, 交期)]，用于顺序断言。"""
    rows, in_table = [], False
    for line in out.splitlines():
        if line.startswith("⏳") or line.startswith("前面单据"):
            in_table = True
            continue
        if in_table:
            if line.startswith("|") and "ORD" in line:
                cells = [c.strip() for c in line.strip("|").split("|")]
                rows.append(cells[:2])
            else:
                break
    return rows


def _purge_order_batches(oid):
    """删订单关联批次及其前道任务（跨测试残留批次会让结构断言不稳）。"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM batches WHERE order_ids LIKE %s", (f"%{oid}%",))
            for (bid,) in cur.fetchall():
                cur.execute("DELETE FROM preprocess_tasks WHERE batch_id=%s", (bid,))
                cur.execute("DELETE FROM batches WHERE id=%s", (bid,))
            conn.commit()


def test_query_order_tracking_not_found(mysql_source):
    """不存在订单返回明确提示。"""
    out = scheduler_tools.query_order_tracking("ORD999")
    assert "❌" in out and "不存在" in out


def test_query_order_tracking_structure(mysql_source):
    """排队订单：状态/工艺 + 未排入批次提示 + 前面单据清单（交期升序）。"""
    _purge_order_batches("ORD001")
    out = scheduler_tools.query_order_tracking("ORD001")
    assert "ORD001" in out and "工艺" in out
    assert "未排入批次" in out
    assert "前面" in out
    dates = [d for _, d in _extract_ahead(out)]
    assert dates == sorted(dates), "前面单据交期须升序"


def test_query_order_tracking_in_transit(mysql_source):
    """在途订单：关联批次打印中，预计完成 = post_process_end。"""
    _exec("INSERT INTO schedule_versions (id, created_at, triggered_by, status) "
          "VALUES (999000, '2026-09-01 08:00:00', 'test', '已审核')")
    try:
        _exec("INSERT INTO batches (id, schedule_version_id, order_ids, process, machine_id, "
              "start_time, end_time, post_process_end, status, approval_status) "
              "VALUES ('BT', 999000, '[\"ORD001\"]', 'SLA', 'M0001', "
              "'2026-09-01 08:00:00', '2026-09-01 10:00:00', '2026-09-01 12:00:00', "
              "'打印中', '通过')")
        out = scheduler_tools.query_order_tracking("ORD001")
        assert "打印中" in out
        assert "2026-09-01 12:00" in out, "预计完成须取 post_process_end"
    finally:
        _exec("DELETE FROM batches WHERE schedule_version_id=999000")
        _exec("DELETE FROM schedule_versions WHERE id=999000")


def test_query_preprocess_load_structure(mysql_source):
    """query_preprocess_load：池占用率 / 预计清空 / 瓶颈标记齐全。"""
    out = scheduler_tools.query_preprocess_load()
    assert "前道人池" in out and "净产能" in out
    assert "占用率" in out
    assert "预计清空" in out
    assert "瓶颈" in out


# ---- M4b T4b.5：query_kpi（纯函数数值 + 集成结构） ----

def test_kpi_on_time():
    """准交率分子/分母：按期 vs 逾期判定（截止日 23:59）。"""
    from datetime import datetime
    orders = {"ORD001": {"due_date": "2026-09-10"},
              "ORD002": {"due_date": "2026-09-05"}}
    completion = {"ORD001": datetime(2026, 9, 8, 10, 0),   # 按期
                  "ORD002": datetime(2026, 9, 7, 10, 0)}   # 逾期
    assert scheduler_tools._kpi_on_time(completion, orders) == (1, 2)


def test_kpi_delay_total_decimal():
    """延期金额 = 金额×日费率×天数，Decimal 精度。"""
    from datetime import datetime
    from decimal import Decimal
    orders = {"ORD002": {"customer_id": "C002", "amount": "100000.00",
                         "due_date": "2026-09-05"}}
    customers = {"C002": {"penalty_rate": "0.003"}}
    completion = {"ORD002": datetime(2026, 9, 8, 10, 0)}  # 截止 9/5 23:59 后 2 天 10h → days=2
    assert scheduler_tools._kpi_delay_total(completion, orders, customers) \
        == Decimal("600.00")
    # 按期订单不计违约金
    completion_ok = {"ORD002": datetime(2026, 9, 5, 12, 0)}
    assert scheduler_tools._kpi_delay_total(completion_ok, orders, customers) \
        == Decimal("0.00")


def test_kpi_cabin_utilization():
    """舱利用率 = Σ投影/Σ舱底。"""
    batches = [{"machine_id": "M0001", "order_ids": '["ORD001"]', "status": "打印中"}]
    parts_by_order = {"ORD001": [{"length": 100, "width": 50, "quantity": 2}]}
    machines = {"M0001": {"cabin_size": 100}}  # 舱底 100×100
    assert scheduler_tools._kpi_cabin_utilization(batches, parts_by_order, machines) \
        == pytest.approx(1.0)
    # 无批次/无舱底 → 0（不除零）
    assert scheduler_tools._kpi_cabin_utilization([], parts_by_order, machines) == 0.0


def test_kpi_yield_rate():
    """良率 = 1 − 坏件/完工；无完工返回 None（不除零）。"""
    assert scheduler_tools._kpi_yield_rate(0, 100) == 1.0
    assert scheduler_tools._kpi_yield_rate(5, 100) == pytest.approx(0.95)
    assert scheduler_tools._kpi_yield_rate(0, 0) is None


def test_query_kpi_structure(mysql_source):
    """query_kpi 输出 5 项指标；空数据友好不除零。"""
    out = scheduler_tools.query_kpi()
    for k in ("准交率", "延期金额", "舱利用率", "良率", "前道瓶颈占用"):
        assert k in out, k
    assert "暂无完工数据" in out or "%" in out
    assert "暂无完工批次" in out or "%" in out
