"""states.py 状态机 + state_change_log 统一写入（M3 T3.2）。

状态机（v1 §5.4）：
  批次：前道 -> 待上机 -> 打印中 -> 静置中 -> 完成；打印中 -> 待上机（设备故障中断回退）
  设备：空闲 -> 打印中 -> 静置中(C6) -> 空闲；任意运行态 -> 故障 -> 维修中 -> 空闲

所有状态变更同事务写 state_change_log（source=simulator，审计主体）。
conn/cur 由调用方传入（并入单事务 tick）。
"""
from __future__ import annotations

BATCH_TRANSITIONS = {
    ("前道", "待上机"),
    ("待上机", "打印中"),
    ("打印中", "静置中"),
    ("静置中", "完成"),
    ("打印中", "待上机"),  # 设备故障中断，退回待上机重排
}

MACHINE_TRANSITIONS = {
    ("空闲", "打印中"),
    ("打印中", "静置中"),
    ("静置中", "空闲"),
    ("空闲", "故障"),
    ("打印中", "故障"),
    ("静置中", "故障"),
    ("故障", "维修中"),
    ("维修中", "空闲"),
}

# 订单状态机（定稿 §2.1）：待排队→已审核（persist 原子锁定，不经守卫）→打印中
# （engine 上机）→完成（拆批全完成）；已审核→待排队（approve_schedule 驳回回退）。
ORDER_TRANSITIONS = {
    ("待排队", "已审核"),
    ("已审核", "打印中"),
    ("打印中", "完成"),
    ("已审核", "待排队"),  # 版本驳回回退（approve_schedule）
}

# no-op 自环（§2.2 幂等约定）：同订单多批同 tick 陆续上机/完成时，第二次写
# 不抛错、不重插 log（否则会使整个 tick 事务回滚）。
ORDER_NOOP_TRANSITIONS = {("打印中", "打印中"), ("完成", "完成")}

_TRANSITIONS = {"batch": BATCH_TRANSITIONS, "machine": MACHINE_TRANSITIONS,
                "order": ORDER_TRANSITIONS}


def assert_transition(entity_kind: str, old: str, new: str) -> None:
    """校验流转合法，非法抛 ValueError（含当前合法去向提示）。"""
    allowed = _TRANSITIONS[entity_kind]
    if (old, new) not in allowed:
        outs = ", ".join(sorted({b for a, b in allowed if a == old}))
        raise ValueError(
            f"非法状态流转：{entity_kind} {old} -> {new}（合法去向：{outs or '无（终态）'}）")


def log_state_change(cur, sim_time, entity_type: str, entity_id: str,
                     field: str, old_value, new_value,
                     source: str = "simulator") -> None:
    """统一写 state_change_log（同事务）。值统一转 str 存 VARCHAR。"""
    cur.execute(
        "INSERT INTO state_change_log "
        "(sim_time, real_time, entity_type, entity_id, `field`, old_value, new_value, source) "
        "VALUES (%s, NOW(), %s, %s, %s, %s, %s, %s)",
        (sim_time, entity_type, entity_id, field,
         str(old_value) if old_value is not None else None,
         str(new_value) if new_value is not None else None,
         source),
    )


def set_batch_status(conn, cur, sim_time, batch_id: str, new_status: str) -> None:
    """推进批次状态 + 写日志。流转非法抛错（事务回滚归调用方）。"""
    cur.execute("SELECT status FROM batches WHERE id=%s", (batch_id,))
    row = cur.fetchone()
    if not row:
        raise ValueError(f"批次不存在：{batch_id}")
    old = row[0]
    assert_transition("batch", old, new_status)
    cur.execute("UPDATE batches SET status=%s WHERE id=%s", (new_status, batch_id))
    log_state_change(cur, sim_time, "batch", batch_id, "status", old, new_status)


def set_machine_status(conn, cur, sim_time, machine_id: str, new_status: str) -> None:
    """推进设备状态 + 写日志。"""
    cur.execute("SELECT status FROM machines WHERE id=%s", (machine_id,))
    row = cur.fetchone()
    if not row:
        raise ValueError(f"设备不存在：{machine_id}")
    old = row[0]
    assert_transition("machine", old, new_status)
    cur.execute("UPDATE machines SET status=%s WHERE id=%s", (new_status, machine_id))
    log_state_change(cur, sim_time, "machine", machine_id, "status", old, new_status)


def set_order_status(conn, cur, sim_time, order_id: str, new_status: str) -> bool:
    """推进订单状态 + 写日志。no-op 自环（打印中→打印中、完成→完成）幂等跳过
    （§2.2），返回 False 不写；其余非法流转抛 ValueError（事务回滚归调用方）。

    注：persist 的待排队→已审核走条件 UPDATE 原子锁定、不经此守卫（§3.C）；
    approve_schedule 驳回的已审核→待排队走条件 UPDATE + source=agent 日志（§3.C）。
    """
    cur.execute("SELECT status FROM orders WHERE id=%s", (order_id,))
    row = cur.fetchone()
    if not row:
        raise ValueError(f"订单不存在：{order_id}")
    old = row[0]
    if old == new_status and (old, new_status) in ORDER_NOOP_TRANSITIONS:
        return False  # 幂等：同订单多批同 tick 陆续流转，第二次不重插 log
    assert_transition("order", old, new_status)
    cur.execute("UPDATE orders SET status=%s WHERE id=%s", (new_status, order_id))
    log_state_change(cur, sim_time, "order", order_id, "status", old, new_status)
    return True


def set_machine_batch(cur, sim_time, machine_id: str, old_batch_id, new_batch_id) -> None:
    """设备占用批次变更 + 写日志（current_batch_id，None 表示释放）。"""
    cur.execute("UPDATE machines SET current_batch_id=%s WHERE id=%s",
                (new_batch_id, machine_id))
    log_state_change(cur, sim_time, "machine", machine_id, "current_batch_id",
                     old_batch_id, new_batch_id)
