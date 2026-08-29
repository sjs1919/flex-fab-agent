"""states.py 状态机 + 审计日志测试（M3 T3.2，需 WSL MySQL）。

覆盖：合法/非法流转、set_* 更新 + state_change_log 落库（source=simulator）。
"""
from datetime import datetime

import pytest

from demo.simulator import states
from demo.tools.data import get_connection

SIM_T = datetime(2026, 9, 1, 8, 0, 0)


@pytest.fixture()
def test_batch():
    """造 1 个测试批次（挂在临时 schedule_version 下，用后清理）。"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO schedule_versions (created_at, triggered_by, status) "
                "VALUES (NOW(), 'test', '待审核')")
            vid = cur.lastrowid
            cur.execute(
                "INSERT INTO batches (id, schedule_version_id, process, model_type, "
                "machine_id, start_time, end_time, post_process_end, status, source) "
                "VALUES ('T-B0001', %s, 'SLA', '600', 'M0001', "
                "'2026-09-01 08:00:00', '2026-09-01 10:00:00', "
                "'2026-09-01 11:00:00', '打印中', '整批')", (vid,))
        conn.commit()
    yield "T-B0001"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM state_change_log WHERE entity_id IN "
                        "('T-B0001', 'M0001')")
            cur.execute("DELETE FROM batches WHERE id='T-B0001'")
            cur.execute("DELETE FROM schedule_versions WHERE id=%s", (vid,))
        conn.commit()


def test_legal_batch_transitions():
    """v1 §5.4 批次链：前道->待上机->打印中->静置中->完成 全合法。"""
    for a, b in [("前道", "待上机"), ("待上机", "打印中"), ("打印中", "静置中"),
                 ("静置中", "完成"), ("打印中", "待上机")]:
        states.assert_transition("batch", a, b)


def test_legal_machine_transitions():
    """v1 §5.4 设备链：空闲->打印中->静置中->空闲；任意运行态->故障->维修中->空闲。"""
    for a, b in [("空闲", "打印中"), ("打印中", "静置中"), ("静置中", "空闲"),
                 ("空闲", "故障"), ("打印中", "故障"), ("静置中", "故障"),
                 ("故障", "维修中"), ("维修中", "空闲")]:
        states.assert_transition("machine", a, b)


def test_illegal_transition_raises():
    """非法流转（空闲->完成 / 完成->打印中）抛 ValueError。"""
    with pytest.raises(ValueError):
        states.assert_transition("machine", "空闲", "完成")
    with pytest.raises(ValueError):
        states.assert_transition("batch", "完成", "打印中")


def test_set_batch_status_logs(test_batch):
    """set_batch_status：批次状态更新 + state_change_log 增行（source=simulator）。"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM state_change_log WHERE entity_id='T-B0001'")
        conn.commit()
        with conn.cursor() as cur:
            states.set_batch_status(conn, cur, SIM_T, "T-B0001", "静置中")
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM batches WHERE id='T-B0001'")
            assert cur.fetchone()[0] == "静置中"
            cur.execute(
                "SELECT entity_type, entity_id, field, old_value, new_value, source "
                "FROM state_change_log WHERE entity_id='T-B0001' ORDER BY id DESC")
            row = cur.fetchone()
    assert row == ("batch", "T-B0001", "status", "打印中", "静置中", "simulator")


def test_set_machine_status_logs():
    """set_machine_status：设备状态更新 + 日志（old_value 取自当前行）。"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM state_change_log WHERE entity_id='M0001'")
            cur.execute("UPDATE machines SET status='空闲', current_batch_id=NULL "
                        "WHERE id='M0001'")
        conn.commit()
        with conn.cursor() as cur:
            states.set_machine_status(conn, cur, SIM_T, "M0001", "故障")
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM machines WHERE id='M0001'")
            assert cur.fetchone()[0] == "故障"
            cur.execute(
                "SELECT field, old_value, new_value, source FROM state_change_log "
                "WHERE entity_id='M0001' ORDER BY id DESC")
            row = cur.fetchone()
    assert row == ("status", "空闲", "故障", "simulator")
    # 还原设备，避免污染其他测试
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE machines SET status='空闲' WHERE id='M0001'")
            cur.execute("DELETE FROM state_change_log WHERE entity_id='M0001'")
        conn.commit()


# ---- 定稿 v1 §2.1/§2.2：订单状态机 + no-op 幂等 ----

def test_legal_order_transitions():
    """订单链：待排队→已审核→打印中→完成 + 驳回回退 已审核→待排队 全合法。"""
    for a, b in [("待排队", "已审核"), ("已审核", "打印中"),
                 ("打印中", "完成"), ("已审核", "待排队")]:
        states.assert_transition("order", a, b)


def test_illegal_order_transition_raises():
    """非法订单流转（待排队→完成 / 待排队→打印中 / 完成→待排队）抛 ValueError。"""
    for a, b in [("待排队", "完成"), ("待排队", "打印中"), ("完成", "待排队")]:
        with pytest.raises(ValueError):
            states.assert_transition("order", a, b)


def test_order_noop_transitions():
    """no-op 自环（打印中→打印中 / 完成→完成）定义存在，幂等不抛错（§2.2）。"""
    assert ("打印中", "打印中") in states.ORDER_NOOP_TRANSITIONS
    assert ("完成", "完成") in states.ORDER_NOOP_TRANSITIONS


def test_set_order_status_noop_returns_false():
    """set_order_status no-op 自环返回 False 且不重插 log（幂等 §2.2）。"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO orders (id, customer_id, amount, urgent, priority, due_date, "
                "status, tenant_id) VALUES ('T-NOOP', 'C001', 1, 0, 0, '2026-09-10', "
                "'打印中', 'default')")
        conn.commit()
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                assert states.set_order_status(conn, cur, SIM_T, "T-NOOP",
                                               "打印中") is False
                cur.execute("SELECT COUNT(*) FROM state_change_log "
                            "WHERE entity_id='T-NOOP' AND field='status'")
                assert cur.fetchone()[0] == 0
            conn.commit()
    finally:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM orders WHERE id='T-NOOP'")
                cur.execute("DELETE FROM state_change_log WHERE entity_id='T-NOOP'")
            conn.commit()


def test_set_order_status_advance_logs():
    """set_order_status 合法流转（打印中→完成）返回 True + 写日志（source=simulator）。"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO orders (id, customer_id, amount, urgent, priority, due_date, "
                "status, tenant_id) VALUES ('T-ADV', 'C001', 1, 0, 0, '2026-09-10', "
                "'打印中', 'default')")
        conn.commit()
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                assert states.set_order_status(conn, cur, SIM_T, "T-ADV",
                                               "完成") is True
                cur.execute("SELECT status FROM orders WHERE id='T-ADV'")
                assert cur.fetchone()[0] == "完成"
                cur.execute("SELECT field, old_value, new_value, source FROM state_change_log "
                            "WHERE entity_id='T-ADV' AND field='status'")
                assert cur.fetchone() == ("status", "打印中", "完成", "simulator")
            conn.commit()
    finally:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM orders WHERE id='T-ADV'")
                cur.execute("DELETE FROM state_change_log WHERE entity_id='T-ADV'")
            conn.commit()
