"""M3 端到端验收（T3.7）-- 对照验收清单 M3 组 6 条 + 用户插单需求。

流程（module 级跑一次，6 个测试共享结果）：
  seed --reset -> 求解器落库批次 -> 造前道任务 -> init_clock ->
  开工预排事件 -> SimulatorRunner 线程跑 120 tick（= 120 sim 小时 = 5 天）->
  逐条断言验收清单 M3 组。

随机固定种子（random.seed(20260823)）保证可复现。
"""
import json
import random
import time as _time
from datetime import datetime, timedelta

import pytest

from demo.scheduler.snapshot import load_snapshot
from demo.scheduler.solver import persist, solve
from demo.simulator import clock, events, seed as seed_mod
from demo.simulator.runner import SimulatorRunner
from demo.tools.data import get_connection

T0 = datetime(2026, 9, 1, 8, 0, 0)
TICKS = 120  # 120 sim 小时 = 5 天


def _rows(sql, params=()):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


@pytest.fixture(scope="module")
def e2e():
    """全流程跑一次，返回汇总信息供各验收断言。"""
    random.seed(20260823)  # 可复现
    seed_mod.reset()  # ① seed --reset

    # 仅保留 5 订单：40 订单 166 批超 7 设备 5 天产能 → solver infeasible
    # （批次 start_time=None，模拟器无批次推进）。造产能内小数据让 solve 有解。
    # ⚠️ 依赖独立库（CI）：seed 修改影响共享库，全量跑需隔离环境。
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM orders ORDER BY id LIMIT 5")
        keep = [r[0] for r in cur.fetchall()]
        if keep:
            ph = ",".join(["%s"] * len(keep))
            cur.execute(f"DELETE FROM parts WHERE order_id NOT IN ({ph})", keep)
            cur.execute(f"DELETE FROM orders WHERE id NOT IN ({ph})", keep)
        conn.commit()

    # 清 M2/M3 中间产物（reset 只清业务表）
    for sql in ("DELETE FROM sim_events", "DELETE FROM state_change_log",
                "DELETE FROM preprocess_tasks", "DELETE FROM approvals",
                "DELETE FROM batches",
                "DELETE FROM schedule_versions"):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()

    # 求解器排产 + 落库（批次初始 前道）
    snapshot = load_snapshot()
    result = solve(snapshot, triggered_by="e2e-m3")
    version_id = persist(result, snapshot, triggered_by="e2e-m3")

    # 造前道任务：每批次错峰 2~26h 完成（让批次能推进到 待上机/打印中/完成）
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM batches WHERE schedule_version_id=%s "
                "ORDER BY id", (version_id,))
            bids = [r[0] for r in cur.fetchall()]
            for i, bid in enumerate(bids):
                cur.execute(
                    "INSERT INTO preprocess_tasks (batch_id, part_count, man_hours, "
                    "assigned_workers, start_time, end_time) "
                    "VALUES (%s, 5, 2.0, 1, %s, %s)",
                    (bid, T0, T0 + timedelta(hours=2 + i % 24)))
        conn.commit()

    # 时钟 + 开工预排 + 跑模拟器线程
    with get_connection() as conn:
        clock.init_clock(conn, T0)
        conn.commit()
    with get_connection() as conn:
        params = events.get_sim_params(conn)
        with conn.cursor() as cur:
            events.seed_schedule_events(cur, T0, params)
        conn.commit()

    runner = SimulatorRunner(tick_seconds=0.01)
    runner.start()
    deadline = _time.monotonic() + 180  # WSL 时序抖动容忍（曾差 9ms 超 120s）
    try:
        while runner.tick_count < TICKS:
            assert _time.monotonic() < deadline, "120 tick 未在 180s 内完成"
            assert runner.is_alive(), "模拟器线程异常退出"
            _time.sleep(0.05)
    finally:
        runner.stop()

    info = {
        "version_id": version_id,
        "n_batches": len(bids),
        "tick_count": runner.tick_count,
        "start": T0,
    }
    yield info
    # teardown：恢复共享库 seed（40 订单/6 人员），避免 module 级 seed_reset+删订单
    # 污染后续测试（全量顺序下 test_resources 等共享库断言受影响）。
    # 理想是 CI 独立库（本 demo 共享开发库折中恢复）。
    seed_mod.reset()

def test_1_events_visible(e2e):
    """验收 1：批次完成/故障/插单事件可见。"""
    fired = _rows("SELECT event_type, COUNT(*) AS n FROM sim_events "
                  "WHERE status='fired' GROUP BY event_type")
    by_type = {r["event_type"]: r["n"] for r in fired}
    assert by_type.get("machine_failure", 0) >= 1, "必须出现设备故障事件"
    assert by_type.get("new_order", 0) >= 1, "必须出现插单事件"
    done = _rows("SELECT COUNT(*) AS n FROM state_change_log "
                 "WHERE entity_type='batch' AND new_value='完成'")
    assert done[0]["n"] >= 1, "必须有批次推进到完成"


def test_2_persistence_audit(e2e):
    """验收 2：sim_clock 单行推进 / sim_events scheduled->fired / 日志 source=simulator。"""
    clocks = _rows("SELECT id, current_sim_time FROM sim_clock")
    assert len(clocks) == 1 and clocks[0]["id"] == 1
    # stop() 前线程可能多跑一拍，以实际 tick 数为准（无丢拍/双拍）
    assert clocks[0]["current_sim_time"] == T0 + timedelta(hours=e2e["tick_count"])
    assert _rows("SELECT id FROM sim_events WHERE status='scheduled'")
    assert _rows("SELECT id FROM sim_events WHERE status='fired'")
    logs = _rows("SELECT DISTINCT source FROM state_change_log")
    assert {r["source"] for r in logs} == {"simulator"}


def test_3_a_layer_semantics(e2e):
    """验收 3：1 tick=1 sim 小时；批次推进->静置->设备释放；前道人效累积。"""
    assert e2e["tick_count"] >= TICKS  # stop() 前可能多跑一拍
    # 批次推进链：至少一条批次走过 静置中（设备 C6 占用后释放）
    curing = _rows("SELECT id FROM state_change_log "
                   "WHERE entity_type='batch' AND new_value='静置中'")
    assert curing, "必须有批次转静置"
    # 设备释放：完成批次的设备回到空闲或被下一批占用，current_batch_id 一致性
    busy = _rows("SELECT id, status, current_batch_id FROM machines "
                 "WHERE current_batch_id IS NOT NULL")
    for m in busy:
        assert m["status"] in ("打印中", "静置中"), f"{m['id']} 占用但状态 {m['status']}"
    # 前道人效日志（班次折算）
    assert _rows("SELECT id FROM state_change_log WHERE field='man_hours'")


def test_4_b_layer_distribution(e2e):
    """验收 4：MTBF/MTTR 指数 + 到达率预排，到点触发。"""
    # 故障->维修链路成立：有 repair_done 触发过（scheduled 可能已全部到点 fired）
    assert _rows("SELECT id FROM sim_events WHERE event_type='repair_done' "
                 "AND status='fired'"), "故障后必须有维修完成事件触发"
    # 触发过的事件类型覆盖（故障/插单/其余到达类至少各 1 类出现）
    fired_types = {r["event_type"] for r in _rows(
        "SELECT DISTINCT event_type FROM sim_events WHERE status='fired'")}
    assert {"machine_failure", "new_order"} <= fired_types
    assert len(fired_types) >= 3, f"到点触发事件类型过少：{fired_types}"


def test_5_hard_infeasibility(e2e):
    """验收 5：硬性不可行 -> 强「需重排」告警（确定性用例在 test_engine_events；
    E2E 记录实际出现条数，出现则 payload 口径完整）。"""
    alerts = _rows("SELECT payload_json FROM sim_events "
                   "WHERE payload_json LIKE '%%reschedule_alert%%'")
    for a in alerts:
        p = json.loads(a["payload_json"])
        assert p["alert"] == "需重排" and p["batch_id"] and p["machine_id"]
        assert p["repair_at"] > p["deadline"], "告警必须满足修不回交期"


def test_6_thread_concurrency_clean(e2e):
    """验收 6：模拟器线程与 MySQL 并发，串行 tick + 短事务 + 连接池，无脏状态。"""
    # 全部 tick 成功落库（时钟恰 = 实际 tick 数，无丢拍/双拍）
    t = _rows("SELECT current_sim_time FROM sim_clock WHERE id=1")[0]["current_sim_time"]
    assert t == T0 + timedelta(hours=e2e["tick_count"])
    # 无孤儿占用：current_batch_id 指向的批次必须存在且在占用态
    for m in _rows("SELECT current_batch_id FROM machines "
                   "WHERE current_batch_id IS NOT NULL"):
        b = _rows("SELECT status FROM batches WHERE id=%s",
                  (m["current_batch_id"],))
        assert b and b[0]["status"] in ("打印中", "静置中"), "出现孤儿设备占用"


def test_7_user_requirement_random_orders(e2e):
    """用户插单需求：new_order 触发实际插入 1~10 单，进入待排队参与后续排产。"""
    sim_orders = _rows(
        "SELECT id, status, due_date FROM orders WHERE id LIKE 'SIM%%'")
    assert sim_orders, "E2E 期间必须实际插单"
    assert all(o["status"] == "待排队" for o in sim_orders)
    end_date = (T0 + timedelta(hours=e2e["tick_count"])).date()
    for o in sim_orders:
        days = (o["due_date"] - end_date).days
        assert days > 0, "新插订单交期必须在未来"
    parts = _rows("SELECT material FROM parts WHERE id LIKE 'SIMP%%'")
    assert parts, "插单必须带零件"
    assert {p["material"] for p in parts} <= {"SLA", "MJS", "SLM"}
    created = _rows("SELECT COUNT(*) AS n FROM state_change_log "
                    "WHERE entity_type='order' AND field='created'")
    assert created[0]["n"] == len(sim_orders), "每笔插单须有 created 日志"
