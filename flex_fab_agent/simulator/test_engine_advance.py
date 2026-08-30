"""engine.py A 层批次推进测试（M3 T3.3，需 WSL MySQL）。

覆盖：批次打印->静置->完成->设备释放；待上机到点上机；前道推进（含班次
系数 22.5/24）；订单到期标记。
"""
from datetime import datetime, timedelta

import pytest

from flex_fab_agent.simulator import engine
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


@pytest.fixture()
def sim_env():
    """造 1 台设备 + 1 批次（打印中 08:00-10:00 静置至 11:00）+ 1 订单。用后清理。"""
    _exec("DELETE FROM sim_events")
    _exec("DELETE FROM state_change_log WHERE entity_id LIKE 'T-%%' OR entity_id='M0001'")
    _exec("DELETE FROM preprocess_tasks WHERE batch_id LIKE 'T-%%'")
    _exec("DELETE FROM batches WHERE id LIKE 'T-%%'")
    _exec("DELETE FROM schedule_versions WHERE triggered_by='test'")
    _exec("DELETE FROM orders WHERE id LIKE 'T-%%'")
    _exec("UPDATE machines SET status='空闲', current_batch_id=NULL WHERE id='M0001'")
    _exec(
        "INSERT INTO orders (id, customer_id, amount, urgent, priority, due_date, status, tenant_id) "
        "VALUES ('T-ORD001', 'C001', 100000, 0, 40, '2026-09-10', '打印中', 'default')")
    _exec(
        "INSERT INTO schedule_versions (created_at, triggered_by, status) "
        "VALUES (NOW(), 'test', '已审核')")
    vid = _rows("SELECT MAX(id) AS id FROM schedule_versions WHERE triggered_by='test'")[0]["id"]
    _exec(
        "INSERT INTO batches (id, schedule_version_id, order_ids, process, model_type, "
        "machine_id, start_time, end_time, post_process_end, status, approval_status, source) "
        "VALUES ('T-B0001', %s, '[\"T-ORD001\"]', 'SLA', '600', 'M0001', "
        "'2026-09-01 08:00:00', '2026-09-01 10:00:00', '2026-09-01 11:00:00', "
        "'打印中', '通过', '整批')", (vid,))
    _exec("UPDATE machines SET status='打印中', current_batch_id='T-B0001' WHERE id='M0001'")
    yield vid
    _exec("DELETE FROM state_change_log WHERE entity_id LIKE 'T-%%' OR entity_id='M0001'")
    _exec("DELETE FROM preprocess_tasks WHERE batch_id LIKE 'T-%%'")
    _exec("DELETE FROM batches WHERE id LIKE 'T-%%'")
    _exec("DELETE FROM schedule_versions WHERE triggered_by='test'")
    _exec("DELETE FROM orders WHERE id LIKE 'T-%%'")
    _exec("UPDATE machines SET status='空闲', current_batch_id=NULL WHERE id='M0001'")


def _tick(sim_time):
    with get_connection() as conn:
        engine.advance_tick(conn, sim_time)
        conn.commit()


def test_shift_factor():
    """班次/换班：3 班倒 8h + 3×30min 换班 -> 净 22.5h/天（验收 3 条）。"""
    assert engine.SHIFT_FACTOR == 22.5 / 24
    # 24 sim 小时 -> 22.5 有效人时（30min×3 无产出）
    assert engine.effective_man_hours(24) == 22.5


def test_advance_print_to_curing(sim_env):
    """打印中 -> 静置中：到 end_time（10:00）转静置，设备跟随静置仍占用（C6）。"""
    _tick(datetime(2026, 9, 1, 10, 30, 0))
    b = _rows("SELECT status, machine_id FROM batches WHERE id='T-B0001'")[0]
    m = _rows("SELECT status, current_batch_id FROM machines WHERE id='M0001'")[0]
    assert b["status"] == "静置中"
    assert m["status"] == "静置中" and m["current_batch_id"] == "T-B0001"


def test_advance_curing_to_done_releases_machine(sim_env):
    """静置中 -> 完成：到 post_process_end（11:00），设备释放（空闲 + current_batch_id=NULL）。"""
    _tick(datetime(2026, 9, 1, 11, 30, 0))
    b = _rows("SELECT status FROM batches WHERE id='T-B0001'")[0]
    m = _rows("SELECT status, current_batch_id FROM machines WHERE id='M0001'")[0]
    assert b["status"] == "完成"
    assert m["status"] == "空闲" and m["current_batch_id"] is None


def test_advance_not_yet(sim_env):
    """未到 end_time：批次保持打印中。"""
    _tick(datetime(2026, 9, 1, 9, 30, 0))
    b = _rows("SELECT status FROM batches WHERE id='T-B0001'")[0]
    assert b["status"] == "打印中"


def test_wait_until_start_boards(sim_env):
    """待上机：未到 start_time 不动；到点且设备空闲 -> 打印中 + 设备占用。"""
    _exec("UPDATE batches SET status='待上机' WHERE id='T-B0001'")
    _exec("UPDATE machines SET status='空闲', current_batch_id=NULL WHERE id='M0001'")
    _tick(datetime(2026, 9, 1, 7, 30, 0))
    assert _rows("SELECT status FROM batches WHERE id='T-B0001'")[0]["status"] == "待上机"
    _tick(datetime(2026, 9, 1, 8, 0, 0))
    b = _rows("SELECT status FROM batches WHERE id='T-B0001'")[0]
    m = _rows("SELECT status, current_batch_id FROM machines WHERE id='M0001'")[0]
    assert b["status"] == "打印中"
    assert m["status"] == "打印中" and m["current_batch_id"] == "T-B0001"


def test_advance_preprocess(sim_env):
    """前道推进：任务到 end_time -> 批次前道->待上机；未到不变（含班次人效日志）。"""
    _exec("UPDATE batches SET status='前道', machine_id=NULL WHERE id='T-B0001'")
    _exec("UPDATE machines SET status='空闲', current_batch_id=NULL WHERE id='M0001'")
    vid = sim_env
    _exec(
        "INSERT INTO preprocess_tasks (batch_id, part_count, man_hours, assigned_workers, "
        "start_time, end_time) VALUES ('T-B0001', 10, 1.0, 1, "
        "'2026-09-01 08:00:00', '2026-09-01 09:00:00')")
    _tick(datetime(2026, 9, 1, 8, 30, 0))
    assert _rows("SELECT status FROM batches WHERE id='T-B0001'")[0]["status"] == "前道"
    _tick(datetime(2026, 9, 1, 9, 30, 0))
    assert _rows("SELECT status FROM batches WHERE id='T-B0001'")[0]["status"] == "待上机"
    logs = _rows("SELECT field, new_value FROM state_change_log "
                 "WHERE entity_id='T-B0001' AND field='man_hours'")
    assert logs, "前道完成须记录累积人时（班次折算）"


def test_mark_overdue_orders(sim_env):
    """订单到期：过交期截止且未完成 -> 逾期标记；未到不变。"""
    _exec("UPDATE orders SET due_date='2026-08-31' WHERE id='T-ORD001'")
    _tick(datetime(2026, 9, 1, 8, 0, 0))
    logs = _rows("SELECT field, new_value FROM state_change_log "
                 "WHERE entity_id='T-ORD001' AND field='overdue'")
    assert logs and logs[0]["new_value"] == "1"
    # 交期未到的订单不产生逾期日志
    _exec("UPDATE orders SET due_date='2026-09-10' WHERE id='T-ORD001'")
    _exec("DELETE FROM state_change_log WHERE entity_id='T-ORD001'")
    _tick(datetime(2026, 9, 1, 9, 0, 0))
    assert not _rows("SELECT id FROM state_change_log WHERE entity_id='T-ORD001' "
                     "AND field='overdue'")


# ---- M5a T5a.8：scrap 落 bad_parts ----

def test_scrap_writes_bad_parts(sim_env):
    """tick 触发 scrap（scrap_rate=1）后 bad_parts 有记录：
    设备/批次/材料/件数齐全，related_event_id 关联 sim_events scrap 事件。"""
    _exec("DELETE FROM bad_parts WHERE batch_id='T-B0001'")
    _exec("DELETE FROM parts WHERE id='T-P0001'")
    _exec(
        "INSERT INTO parts (id, order_id, product_id, name, quantity, material, "
        "length, width, height, weight, tenant_id) VALUES "
        "('T-P0001', 'T-ORD001', 'P-T', '测试件', 3, 'SLA', 100, 100, 100, 1, 'default')")
    try:
        with get_connection() as conn:
            engine.advance_tick(conn, datetime(2026, 9, 1, 11, 30, 0),
                                {"scrap_rate": 1.0})
            conn.commit()
        rows = _rows("SELECT batch_id, machine_id, material, part_count, related_event_id "
                     "FROM bad_parts WHERE batch_id='T-B0001'")
        assert len(rows) == 1
        r = rows[0]
        assert r["machine_id"] == "M0001"
        assert r["material"] == "SLA"
        assert r["part_count"] == 3  # T-ORD001 关联 parts 量合计
        evs = _rows("SELECT id FROM sim_events WHERE event_type='scrap' "
                    "AND payload_json LIKE '%%T-B0001%%'")
        assert evs and evs[0]["id"] == r["related_event_id"]
    finally:
        _exec("DELETE FROM bad_parts WHERE batch_id='T-B0001'")
        _exec("DELETE FROM parts WHERE id='T-P0001'")


# ---- 定稿 v1 §2.1/§3.E：订单流转 + 审批门禁 ----

def test_order_advances_to_printing_on_board(sim_env):
    """订单流转：批次上机（待上机→打印中）时订单 已审核→打印中（§2.1）。"""
    _exec("UPDATE batches SET status='待上机' WHERE id='T-B0001'")
    _exec("UPDATE machines SET status='空闲', current_batch_id=NULL WHERE id='M0001'")
    _exec("UPDATE orders SET status='已审核' WHERE id='T-ORD001'")
    _tick(datetime(2026, 9, 1, 8, 0, 0))
    assert _rows("SELECT status FROM orders WHERE id='T-ORD001'")[0]["status"] == "打印中"


def test_order_completes_on_all_batches_done(sim_env):
    """订单流转：批次完成（静置中→完成）时订单 打印中→完成（§2.1）。"""
    _tick(datetime(2026, 9, 1, 11, 30, 0))
    assert _rows("SELECT status FROM orders WHERE id='T-ORD001'")[0]["status"] == "完成"


def test_gate_unapproved_not_board(sim_env):
    """E 门禁：approval_status≠通过 的待上机批次不上机（到点且设备空闲也不动）。"""
    _exec("UPDATE batches SET status='待上机', approval_status='待审核' WHERE id='T-B0001'")
    _exec("UPDATE machines SET status='空闲', current_batch_id=NULL WHERE id='M0001'")
    _tick(datetime(2026, 9, 1, 8, 0, 0))
    assert _rows("SELECT status FROM batches WHERE id='T-B0001'")[0]["status"] == "待上机"
    assert _rows("SELECT status FROM machines WHERE id='M0001'")[0]["status"] == "空闲"


def test_gate_unapproved_no_preprocess_advance(sim_env):
    """E 门禁：approval_status≠通过 的前道任务不推进（不释放人时）。"""
    _exec("UPDATE batches SET status='前道', approval_status='待审核', "
          "machine_id=NULL WHERE id='T-B0001'")
    _exec("UPDATE machines SET status='空闲', current_batch_id=NULL WHERE id='M0001'")
    _exec(
        "INSERT INTO preprocess_tasks (batch_id, part_count, man_hours, assigned_workers, "
        "start_time, end_time) VALUES ('T-B0001', 10, 1.0, 1, "
        "'2026-09-01 08:00:00', '2026-09-01 09:00:00')")
    _tick(datetime(2026, 9, 1, 9, 30, 0))
    assert _rows("SELECT status FROM batches WHERE id='T-B0001'")[0]["status"] == "前道"


def test_order_not_complete_when_other_batch_in_transit(sim_env):
    """拆批完成判定：订单最新版本全部「通过+start_time 非空」批次完成后才置完成；
    仍有批次在途时不提前完成。"""
    vid = sim_env
    _exec("UPDATE machines SET status='空闲', current_batch_id=NULL WHERE id='M0002'")
    _exec(
        "INSERT INTO batches (id, schedule_version_id, order_ids, process, model_type, "
        "machine_id, start_time, end_time, post_process_end, status, approval_status, source) "
        "VALUES ('T-B0002', %s, '[\"T-ORD001\"]', 'SLA', '600', 'M0002', "
        "'2026-09-01 08:00:00', '2026-09-01 12:00:00', '2026-09-01 13:00:00', "
        "'打印中', '通过', '整批')", (vid,))
    _exec("UPDATE machines SET status='打印中', current_batch_id='T-B0002' WHERE id='M0002'")
    try:
        # 11:30：T-B0001 完成（静置 11:00），T-B0002 仍打印中（end 12:00）→ 订单不完成
        _tick(datetime(2026, 9, 1, 11, 30, 0))
        assert _rows("SELECT status FROM orders WHERE id='T-ORD001'")[0]["status"] == "打印中", \
            "仍有批次在途，订单不应提前完成"
        # 13:30：T-B0002 也完成 → 订单完成
        _tick(datetime(2026, 9, 1, 13, 30, 0))
        assert _rows("SELECT status FROM orders WHERE id='T-ORD001'")[0]["status"] == "完成"
    finally:
        _exec("UPDATE machines SET status='空闲', current_batch_id=NULL WHERE id='M0002'")
        _exec("DELETE FROM batches WHERE id='T-B0002'")
