"""engine.py B 层事件触发 + 硬性不可行告警测试（M3 T3.5，需 WSL MySQL）。

覆盖：故障触发（设备中断在跑批次）、硬性不可行强告警、维修恢复、插单触发、
leave/back 人效、restock 库存、advance_tick 集成。
"""
import json
from datetime import datetime, timedelta

import pytest

from demo.simulator import engine, events
from demo.tools.data import get_connection

T0 = datetime(2026, 9, 1, 8, 0, 0)
PARAMS = dict(events.PARAMS_DEFAULT)


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
    """1 台设备 + 1 批次（打印中）+ 1 订单 + 人员复位。用后清理。"""
    _exec("DELETE FROM sim_events")
    _exec("DELETE FROM state_change_log WHERE entity_id LIKE 'T-%%'")
    _exec("DELETE FROM preprocess_tasks WHERE batch_id LIKE 'T-%%'")
    _exec("DELETE FROM batches WHERE id LIKE 'T-%%'")
    _exec("DELETE FROM schedule_versions WHERE triggered_by='test'")
    _exec("DELETE FROM orders WHERE id LIKE 'T-%%'")
    _exec("DELETE FROM parts WHERE order_id LIKE 'T-%%'")
    _exec("UPDATE machines SET status='空闲', current_batch_id=NULL WHERE id='M0001'")
    # 确保 personnel 存在（leave 测试依赖；单独跑无 seed 时幂等插入，见 seed_personnel）
    from demo.simulator.seed import seed_personnel
    with get_connection() as conn:
        with conn.cursor() as cur:
            seed_personnel(cur)
        conn.commit()
    _exec("UPDATE personnel SET status='上班'")  # leave 测试会改具体人状态，先复位
    _exec(
        "INSERT INTO orders (id, customer_id, amount, urgent, priority, due_date, status, tenant_id) "
        "VALUES ('T-ORD001', 'C001', 100000, 0, 40, '2026-09-10', '打印中', 'default')")
    _exec(
        "INSERT INTO schedule_versions (created_at, triggered_by, status) "
        "VALUES (NOW(), 'test', '已审核')")
    vid = _rows("SELECT MAX(id) AS id FROM schedule_versions WHERE triggered_by='test'")[0]["id"]
    _exec(
        "INSERT INTO batches (id, schedule_version_id, order_ids, process, model_type, "
        "machine_id, start_time, end_time, post_process_end, status, source) "
        "VALUES ('T-B0001', %s, '[\"T-ORD001\"]', 'SLA', '600', 'M0001', "
        "'2026-09-01 08:00:00', '2026-09-05 10:00:00', '2026-09-05 11:00:00', "
        "'打印中', '整批')", (vid,))
    _exec("UPDATE machines SET status='打印中', current_batch_id='T-B0001' WHERE id='M0001'")
    yield
    _exec("DELETE FROM sim_events")
    _exec("DELETE FROM state_change_log WHERE entity_id LIKE 'T-%%'")
    _exec("DELETE FROM preprocess_tasks WHERE batch_id LIKE 'T-%%'")
    _exec("DELETE FROM batches WHERE id LIKE 'T-%%'")
    _exec("DELETE FROM schedule_versions WHERE triggered_by='test'")
    _exec("DELETE FROM orders WHERE id LIKE 'T-%%'")
    _exec("DELETE FROM parts WHERE order_id LIKE 'T-%%'")
    _exec("UPDATE machines SET status='空闲', current_batch_id=NULL WHERE id='M0001'")
    _exec("UPDATE personnel SET status='上班'")  # 复位 leave 测试改过的具体人状态


def _fire(sim_time, monkeypatch=None):
    with get_connection() as conn:
        engine.advance_tick(conn, sim_time)
        conn.commit()


def test_fire_machine_failure_interrupts(sim_env, monkeypatch):
    """故障触发：设备故障->维修中；在跑批次中断退回待上机；事件 fired；
    并预排 repair_done + 该设备下一个故障。"""
    _exec(
        "INSERT INTO sim_events (sim_time, event_type, payload_json, status) "
        "VALUES ('2026-09-01 08:00:00', 'machine_failure', "
        "'{\"machine_id\": \"M0001\"}', 'scheduled')")
    _fire(datetime(2026, 9, 1, 9, 0, 0))
    m = _rows("SELECT status, current_batch_id FROM machines WHERE id='M0001'")[0]
    assert m["status"] == "维修中" and m["current_batch_id"] is None
    assert _rows("SELECT status FROM batches WHERE id='T-B0001'")[0]["status"] == "待上机"
    fired = _rows(
        "SELECT id FROM sim_events WHERE event_type='machine_failure' AND status='fired'")
    assert fired, "到点故障事件必须 fired"
    scheduled = _rows(
        "SELECT event_type FROM sim_events WHERE status='scheduled'")
    types = {r["event_type"] for r in scheduled}
    assert "repair_done" in types, "故障后必须预排维修完成"
    assert "machine_failure" in types, "触发后必须预排该设备下一个故障"
    logs = _rows("SELECT field, new_value FROM state_change_log WHERE entity_id='M0001'")
    assert any(l["field"] == "status" and l["new_value"] == "故障" for l in logs)


def test_hard_infeasibility_alert(sim_env, monkeypatch):
    """硬性不可行：维修完成时刻晚于批次交期 -> 强「需重排」告警 sim_events
    （agent 经 query_sim_events 可见，验收 5 条）。"""
    # 订单交期 9-10；mock MTTR = 600h（25 天）-> 修不回交期
    monkeypatch.setattr(events.random, "expovariate", lambda lam: 600.0 if lam < 1 else 1 / lam)
    _exec(
        "INSERT INTO sim_events (sim_time, event_type, payload_json, status) "
        "VALUES ('2026-09-01 08:00:00', 'machine_failure', "
        "'{\"machine_id\": \"M0001\"}', 'scheduled')")
    _fire(datetime(2026, 9, 1, 9, 0, 0))
    alerts = _rows(
        "SELECT payload_json FROM sim_events WHERE event_type='machine_failure' "
        "AND payload_json LIKE '%%reschedule%%'")
    assert alerts, "修不回交期必须生成强「需重排」告警"
    payload = json.loads(alerts[0]["payload_json"])
    assert payload["alert"] == "需重排"
    assert payload["batch_id"] == "T-B0001"
    assert payload["machine_id"] == "M0001"


def test_no_alert_when_repairable(sim_env, monkeypatch):
    """维修能赶上交期 -> 不生成告警。"""
    monkeypatch.setattr(events.random, "expovariate", lambda lam: 2.0 if lam < 1 else 1 / lam)
    _exec(
        "INSERT INTO sim_events (sim_time, event_type, payload_json, status) "
        "VALUES ('2026-09-01 08:00:00', 'machine_failure', "
        "'{\"machine_id\": \"M0001\"}', 'scheduled')")
    _fire(datetime(2026, 9, 1, 9, 0, 0))
    assert not _rows(
        "SELECT id FROM sim_events WHERE payload_json LIKE '%%reschedule%%'")


def test_repair_done_recovers(sim_env):
    """repair_done 到点：设备维修中->空闲（可再分配）。"""
    _exec("UPDATE machines SET status='维修中', current_batch_id=NULL WHERE id='M0001'")
    _exec(
        "INSERT INTO sim_events (sim_time, event_type, payload_json, status) "
        "VALUES ('2026-09-01 08:00:00', 'repair_done', "
        "'{\"machine_id\": \"M0001\"}', 'scheduled')")
    _fire(datetime(2026, 9, 1, 9, 0, 0))
    assert _rows("SELECT status FROM machines WHERE id='M0001'")[0]["status"] == "空闲"


def test_fire_new_order_and_reschedule(sim_env):
    """new_order 到点：实际插入订单（orders 增加）+ 预排下一个 new_order。"""
    before = _rows("SELECT COUNT(*) AS n FROM orders WHERE id LIKE 'SIM%%'")[0]["n"]
    _exec(
        "INSERT INTO sim_events (sim_time, event_type, payload_json, status) "
        "VALUES ('2026-09-01 08:00:00', 'new_order', NULL, 'scheduled')")
    _fire(datetime(2026, 9, 1, 9, 0, 0))
    after = _rows("SELECT COUNT(*) AS n FROM orders WHERE id LIKE 'SIM%%'")[0]["n"]
    assert after - before >= 1, "new_order 触发必须实际插单"
    assert _rows(
        "SELECT id FROM sim_events WHERE event_type='new_order' "
        "AND status='scheduled'"), "触发后必须预排下一个 new_order"


def test_fire_leave_and_back(sim_env):
    """leave 到点：personnel 请假日志 + 预排回岗（kind=back）；回岗到点：恢复上班日志。"""
    _exec(
        "INSERT INTO sim_events (sim_time, event_type, payload_json, status) "
        "VALUES ('2026-09-01 08:00:00', 'leave', NULL, 'scheduled')")
    _fire(datetime(2026, 9, 1, 9, 0, 0))
    logs = _rows(
        "SELECT new_value FROM state_change_log WHERE entity_type='personnel' "
        "AND field='status'")
    assert any(l["new_value"] == "请假" for l in logs)
    back = _rows(
        "SELECT payload_json FROM sim_events WHERE event_type='leave' "
        "AND status='scheduled'")
    assert back and "back" in back[0]["payload_json"], "请假后必须预排回岗"
    # 回岗触发（回岗时间由 leave handler 随机预排，直接把 scheduled 改到点）
    _exec("UPDATE sim_events SET sim_time='2026-09-01 09:00:00' "
          "WHERE event_type='leave' AND status='scheduled'")
    _fire(datetime(2026, 9, 1, 10, 0, 0))
    logs = _rows(
        "SELECT new_value FROM state_change_log WHERE entity_type='personnel' "
        "AND field='status'")
    assert any(l["new_value"] == "上班" for l in logs)


def test_fire_restock(sim_env):
    """restock 到点：某材料库存增加 + 日志 + 预排下一个。"""
    before = _rows("SELECT SUM(库存量) AS s FROM inventory")[0]["s"]
    _exec(
        "INSERT INTO sim_events (sim_time, event_type, payload_json, status) "
        "VALUES ('2026-09-01 08:00:00', 'restock', NULL, 'scheduled')")
    _fire(datetime(2026, 9, 1, 9, 0, 0))
    after = _rows("SELECT SUM(库存量) AS s FROM inventory")[0]["s"]
    assert after > before, "restock 必须实际增加库存"
    assert _rows("SELECT id FROM state_change_log WHERE entity_type='inventory'")


def test_fire_order_change(sim_env):
    """order_change 到点：改交期（更新 due_date）+ 日志 + 预排下一个。"""
    _exec(
        "INSERT INTO sim_events (sim_time, event_type, payload_json, status) "
        "VALUES ('2026-09-01 08:00:00', 'order_change', "
        "'{\"order_id\": \"T-ORD001\"}', 'scheduled')")
    _fire(datetime(2026, 9, 1, 9, 0, 0))
    logs = _rows(
        "SELECT field, old_value, new_value FROM state_change_log "
        "WHERE entity_id='T-ORD001' AND field='due_date'")
    assert logs, "改交期必须写日志"
    assert logs[0]["old_value"] != logs[0]["new_value"]
