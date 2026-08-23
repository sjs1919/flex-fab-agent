"""engine.py 模拟器引擎（M3 T3.3 A 层推进 / T3.5 B 层触发）。

A 层每 tick（v1 §5.2，单事务由调用方管理）：
  1. 推进批次：打印中->静置中（C6 仍占用）->完成（设备释放，按坏件率抽检）；
     待上机->打印中（到 start_time 且设备空闲）
  2. 推进前道：preprocess_tasks 到 end_time -> 批次前道->待上机
     （人效按班次系数 22.5/24 折算：3 班倒 8h×3 - 3×30min 换班 = 净 22.5h/天）
  3. 订单到期：过交期截止（当天 23:59）且未完成 -> 逾期标记（去重）

B 层事件触发（T3.5，v1 §5.3/§5.5）：到点 scheduled 事件 -> fired -> 分派
handler；machine_failure 触发硬性不可行检测（修不回交期 -> 强「需重排」
告警 sim_events，agent 经 query_sim_events 可见）；软扰动不自动重排。
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta

from demo.simulator import events, states

# 班次/换班：3 班倒 × 8h，每班换班 30min 无产出 -> 净 22.5h/天
SHIFT_FACTOR = 22.5 / 24


def effective_man_hours(sim_hours: float, workers: int = 1) -> float:
    """sim 时长折算有效人时（班次系数：换班 30min×3 无产出）。"""
    return round(sim_hours * workers * SHIFT_FACTOR, 2)


def advance_batches(conn, cur, sim_time: datetime, params: dict | None = None) -> int:
    """推进批次状态机，返回状态变更数。顺序：转静置 -> 完成释放 -> 上机
    （同 tick 内批次可连走两步：打印中->静置中->完成；释放的设备可立即
    被待上机批次占用）。完成时按坏件率抽检（v1 §5.3 scrap）。"""
    p = params or events.PARAMS_DEFAULT
    changed = 0

    # 1. 打印中 -> 静置中（设备仍占用 C6）
    cur.execute(
        "SELECT id, machine_id FROM batches "
        "WHERE status='打印中' AND end_time <= %s", (sim_time,))
    for bid, mid in cur.fetchall():
        states.set_batch_status(conn, cur, sim_time, bid, "静置中")
        if mid:
            cur.execute("SELECT status FROM machines WHERE id=%s", (mid,))
            row = cur.fetchone()
            if row and row[0] == "打印中":
                states.set_machine_status(conn, cur, sim_time, mid, "静置中")
        changed += 1

    # 2. 静置中 -> 完成，设备释放
    cur.execute(
        "SELECT id, machine_id FROM batches "
        "WHERE status='静置中' AND post_process_end <= %s", (sim_time,))
    for bid, mid in cur.fetchall():
        states.set_batch_status(conn, cur, sim_time, bid, "完成")
        _scrap_inspect(cur, sim_time, bid, p)
        if mid:
            cur.execute("SELECT status, current_batch_id FROM machines WHERE id=%s", (mid,))
            row = cur.fetchone()
            if row and row[1] == bid:
                if row[0] == "静置中":
                    states.set_machine_status(conn, cur, sim_time, mid, "空闲")
                states.set_machine_batch(cur, sim_time, mid, bid, None)
        changed += 1

    # 3. 待上机 -> 打印中（到 start_time 且设备空闲）。
    #    先取空闲设备集再匹配批次（避免对每个待上机批次各查一次设备）。
    cur.execute(
        "SELECT id FROM machines WHERE status='空闲' AND current_batch_id IS NULL")
    idle = {r[0] for r in cur.fetchall()}
    if idle:
        cur.execute(
            "SELECT id, machine_id FROM batches "
            "WHERE status='待上机' AND start_time <= %s AND machine_id IN "
            f"({','.join(['%s'] * len(idle))}) ORDER BY start_time, id",
            (sim_time, *idle))
        for bid, mid in cur.fetchall():
            if mid not in idle:
                continue  # 循环内已被其他批次占用
            states.set_batch_status(conn, cur, sim_time, bid, "打印中")
            states.set_machine_status(conn, cur, sim_time, mid, "打印中")
            states.set_machine_batch(cur, sim_time, mid, None, bid)
            idle.discard(mid)
            changed += 1
    return changed


def _scrap_inspect(cur, sim_time: datetime, batch_id: str, params: dict) -> None:
    """批次完成抽检（v1 §5.3）：按坏件率触发 scrap 事件（即时 fired）。
    重打批次生成留 M4（工具层），此处仅事件 + 日志提示。"""
    if random.random() >= params.get("scrap_rate", 0.05):
        return
    cur.execute(
        "INSERT INTO sim_events (sim_time, event_type, payload_json, status) "
        "VALUES (%s, 'scrap', %s, 'fired')",
        (sim_time, json.dumps({"batch_id": batch_id, "hint": "坏件需重打"},
                              ensure_ascii=False)))
    states.log_state_change(cur, sim_time, "batch", batch_id, "scrap", "完成", "坏件需重打")


def advance_preprocess(conn, cur, sim_time: datetime) -> int:
    """前道推进：任务到 end_time -> 批次前道->待上机，写累积人时日志（班次折算）。"""
    cur.execute(
        "SELECT pt.batch_id, pt.man_hours, pt.assigned_workers, pt.start_time "
        "FROM preprocess_tasks pt JOIN batches b ON b.id = pt.batch_id "
        "WHERE b.status='前道' AND pt.end_time <= %s", (sim_time,))
    done = cur.fetchall()
    for bid, man_hours, workers, start in done:
        elapsed = (sim_time - start).total_seconds() / 3600 if start else man_hours / SHIFT_FACTOR
        states.set_batch_status(conn, cur, sim_time, bid, "待上机")
        states.log_state_change(
            cur, sim_time, "preprocess", bid, "man_hours",
            0, f"{min(man_hours, effective_man_hours(elapsed, workers))}"
            f"（班次系数{SHIFT_FACTOR:.4f}折算）")
    return len(done)


def mark_overdue_orders(conn, cur, sim_time: datetime) -> int:
    """订单到期标记：sim 日期 > 交期日期（当天 23:59 截止）且未完成 -> 逾期日志（去重）。"""
    cur.execute(
        "SELECT id FROM orders "
        "WHERE status != '完成' AND due_date < %s", (sim_time.date(),))
    overdue = [r[0] for r in cur.fetchall()]
    if not overdue:
        return 0
    placeholders = ",".join(["%s"] * len(overdue))
    cur.execute(
        f"SELECT DISTINCT entity_id FROM state_change_log "
        f"WHERE field='overdue' AND entity_id IN ({placeholders})",
        tuple(overdue))
    marked_ids = {r[0] for r in cur.fetchall()}
    marked = 0
    for oid in overdue:
        if oid in marked_ids:
            continue
        states.log_state_change(cur, sim_time, "order", oid, "overdue", "0", "1")
        marked += 1
    return marked


def advance_tick(conn, sim_time: datetime, params: dict | None = None) -> dict:
    """单 tick 推进组装（A 层 + B 层触发）。返回各步计数。"""
    if params is None:
        params = events.get_sim_params(conn)
    with conn.cursor() as cur:
        stats = {
            "batches": advance_batches(conn, cur, sim_time, params),
            "preprocess": advance_preprocess(conn, cur, sim_time),
            "overdue": mark_overdue_orders(conn, cur, sim_time),
            "events_fired": fire_events(conn, cur, sim_time, params),
        }
    return stats


# ---- B 层事件触发（T3.5）----

def fire_events(conn, cur, sim_time: datetime, params: dict) -> int:
    """触发到点事件：scheduled 且 sim_time >= 预排时刻 -> fired -> 分派 handler。"""
    cur.execute(
        "SELECT id, event_type, payload_json FROM sim_events "
        "WHERE status='scheduled' AND sim_time <= %s ORDER BY sim_time, id",
        (sim_time,))
    due = cur.fetchall()
    fired = 0
    for eid, event_type, payload_json in due:
        payload = json.loads(payload_json) if payload_json else {}
        handler = _HANDLERS.get(event_type)
        if handler is not None:
            handler(conn, cur, sim_time, params, payload)
        cur.execute("UPDATE sim_events SET status='fired' WHERE id=%s", (eid,))
        fired += 1
    return fired


def check_hard_infeasibility(conn, cur, sim_time: datetime, machine_id: str,
                             batch_id: str, repair_at: datetime) -> bool:
    """硬性不可行检测（v1 §5.5）：故障设备维修完成时刻晚于批次交期
    （关联订单最晚 due 当天 23:59）-> 强「需重排」告警 sim_events（fired，
    agent 经 query_sim_events 可见）+ 日志。返回是否生成告警。"""
    cur.execute("SELECT order_ids FROM batches WHERE id=%s", (batch_id,))
    row = cur.fetchone()
    if not row or not row[0]:
        return False
    order_ids = json.loads(row[0])
    if not order_ids:
        return False
    placeholders = ",".join(["%s"] * len(order_ids))
    cur.execute(f"SELECT MAX(due_date) FROM orders WHERE id IN ({placeholders})",
                tuple(order_ids))
    due_row = cur.fetchone()
    if not due_row or not due_row[0]:
        return False
    deadline = datetime(due_row[0].year, due_row[0].month, due_row[0].day, 23, 59, 59)
    if repair_at <= deadline:
        return False
    payload = {"type": "reschedule_alert", "alert": "需重排", "batch_id": batch_id,
               "machine_id": machine_id,
               "repair_at": repair_at.strftime("%Y-%m-%d %H:%M:%S"),
               "deadline": deadline.strftime("%Y-%m-%d %H:%M:%S"),
               "reason": "设备故障且维修无法在批次交期前恢复"}
    cur.execute(
        "INSERT INTO sim_events (sim_time, event_type, payload_json, status) "
        "VALUES (%s, 'machine_failure', %s, 'fired')",
        (sim_time, json.dumps(payload, ensure_ascii=False)))
    states.log_state_change(cur, sim_time, "batch", batch_id, "reschedule_alert",
                            "受影响", "需重排")
    return True


def _fire_machine_failure(conn, cur, sim_time: datetime, params: dict,
                          payload: dict) -> None:
    """设备故障：中断在跑批次（打印中->待上机）；故障即开始维修；预排
    repair_done + 该设备下一个故障；硬性不可行检测。"""
    mid = payload.get("machine_id")
    if not mid:
        return
    cur.execute("SELECT status, current_batch_id FROM machines WHERE id=%s", (mid,))
    row = cur.fetchone()
    if not row:
        return
    status, cur_batch = row
    interrupted = None
    if status in ("空闲", "打印中", "静置中"):
        states.set_machine_status(conn, cur, sim_time, mid, "故障")
        if cur_batch:
            cur.execute("SELECT status FROM batches WHERE id=%s", (cur_batch,))
            brow = cur.fetchone()
            if brow and brow[0] == "打印中":
                interrupted = cur_batch
                states.set_batch_status(conn, cur, sim_time, cur_batch, "待上机")
            states.set_machine_batch(cur, sim_time, mid, cur_batch, None)
        states.set_machine_status(conn, cur, sim_time, mid, "维修中")
    elif status == "故障":
        states.set_machine_status(conn, cur, sim_time, mid, "维修中")

    repair_payload = {"machine_id": mid}
    if interrupted:
        repair_payload["affected_batch"] = interrupted
    repair_at = events.schedule_next(cur, "repair_done", sim_time, params,
                                     payload=repair_payload)
    if interrupted:
        check_hard_infeasibility(conn, cur, sim_time, mid, interrupted, repair_at)
    events.schedule_next(cur, "machine_failure", sim_time, params,
                         payload={"machine_id": mid})


def _fire_repair_done(conn, cur, sim_time: datetime, params: dict,
                      payload: dict) -> None:
    """维修完成：维修中->空闲（可再分配；中断批次已退待上机，将随 tick 重新上机）。"""
    mid = payload.get("machine_id")
    if not mid:
        return
    cur.execute("SELECT status FROM machines WHERE id=%s", (mid,))
    row = cur.fetchone()
    if row and row[0] == "维修中":
        states.set_machine_status(conn, cur, sim_time, mid, "空闲")


def _fire_new_order(conn, cur, sim_time: datetime, params: dict,
                    payload: dict) -> None:
    """随机插单（用户需求）：1~10 单 -> 待排队；触发后预排下一个 new_order。"""
    events.generate_new_order(conn, cur, sim_time, params)
    events.schedule_next(cur, "new_order", sim_time, params)


def _fire_order_change(conn, cur, sim_time: datetime, params: dict,
                       payload: dict) -> None:
    """订单变更（M3 范围：改交期；撤单/数量留 M4）；预排下一个。"""
    oid = payload.get("order_id")
    if not oid:
        cur.execute("SELECT id FROM orders WHERE status != '完成' "
                    "ORDER BY RAND() LIMIT 1")
        row = cur.fetchone()
        oid = row[0] if row else None
    if not oid:
        events.schedule_next(cur, "order_change", sim_time, params)
        return
    cur.execute("SELECT due_date FROM orders WHERE id=%s", (oid,))
    old_due = cur.fetchone()[0]
    delta = random.choice([-3, -2, -1, 1, 2, 3, 5, 7, 10])
    new_due = old_due + timedelta(days=delta)
    cur.execute("UPDATE orders SET due_date=%s WHERE id=%s", (new_due, oid))
    states.log_state_change(cur, sim_time, "order", oid, "due_date", old_due, new_due)
    events.schedule_next(cur, "order_change", sim_time, params)


def _fire_leave(conn, cur, sim_time: datetime, params: dict, payload: dict) -> None:
    """前道工人请假/回岗（6 人池动态人数）：absence 请假 + 预排回岗（kind=back）
    + 预排下一个 absence；back 回岗恢复人效。"""
    if payload.get("kind") == "back":
        states.log_state_change(cur, sim_time, "personnel", "前道工人池",
                                "status", "请假", "在岗")
        return
    states.log_state_change(cur, sim_time, "personnel", "前道工人池",
                            "status", "在岗", "请假")
    return_at = sim_time + timedelta(days=random.randint(1, 3))
    cur.execute(
        "INSERT INTO sim_events (sim_time, event_type, payload_json, status) "
        "VALUES (%s, 'leave', %s, 'scheduled')",
        (return_at, json.dumps({"kind": "back"}, ensure_ascii=False)))
    events.schedule_next(cur, "leave", sim_time, params)


def _fire_restock(conn, cur, sim_time: datetime, params: dict,
                  payload: dict) -> None:
    """材料到货：随机材料库存增加 + 日志；预排下一个。"""
    cur.execute("SELECT id, `库存量` FROM inventory ORDER BY RAND() LIMIT 1")
    row = cur.fetchone()
    if row:
        inv_id, old_qty = row
        add = round(random.uniform(10, 50), 2)
        new_qty = float(old_qty) + add
        cur.execute("UPDATE inventory SET `库存量` = `库存量` + %s WHERE id=%s",
                    (add, inv_id))
        states.log_state_change(cur, sim_time, "inventory", inv_id, "库存量",
                                old_qty, new_qty)
    events.schedule_next(cur, "restock", sim_time, params)


_HANDLERS = {
    "machine_failure": _fire_machine_failure,
    "repair_done": _fire_repair_done,
    "new_order": _fire_new_order,
    "order_change": _fire_order_change,
    "leave": _fire_leave,
    "restock": _fire_restock,
}
