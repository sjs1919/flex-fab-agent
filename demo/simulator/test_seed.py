"""seed.py 种子生成测试（M1 T1.3，需 WSL MySQL 可用）。

覆盖：reset 幂等、数量口径（7 设备/5 客户/30-50 订单/数百 part/10 库存）、
枚举合法、超尺寸样例（M2 预警验收预留）。
"""
from datetime import date, datetime

import demo.schema.migrate as mig
import demo.simulator.seed as seed_mod


def _query(sql, params=()):
    conn = seed_mod._connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def test_seed_reset_counts():
    """reset 后数量口径符合 todo T1.3 验收。"""
    seed_mod.reset()
    assert _query("SELECT COUNT(*) FROM customer")[0][0] == 5
    assert _query("SELECT COUNT(*) FROM machines")[0][0] == 7
    orders = _query("SELECT COUNT(*) FROM orders")[0][0]
    assert 20 <= orders <= 50  # 2026-08-28 从 30 调低：seed 订单 40→20（产能匹配）
    parts = _query("SELECT COUNT(*) FROM parts")[0][0]
    assert parts >= 100
    assert _query("SELECT COUNT(*) FROM inventory")[0][0] == 10
    assert _query("SELECT COUNT(*) FROM material")[0][0] == 3


def test_seed_valid_enum_and_amount():
    """每订单 status 合法枚举、amount>0；part.material 合法。"""
    conn = seed_mod._connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status, amount, urgent, priority, due_date FROM orders")
            for status, amount, urgent, priority, due_date in cur.fetchall():
                assert status in ("待排队", "已审核", "打印中", "完成")
                assert amount > 0
                assert urgent in (0, 1)
                assert priority >= 0
                assert due_date is not None
            cur.execute("SELECT material FROM parts")
            materials = {r[0] for r in cur.fetchall()}
            assert materials <= {"SLA", "MJS", "SLM"}
            assert materials  # 非空
    finally:
        conn.close()


def test_seed_oversize_sample():
    """至少 1 个 part 某边 >600mm（M2 超尺寸预警验收预留样例）。"""
    rows = _query("SELECT length, width, height FROM parts")
    assert any(max(r) > 600 for r in rows), "缺少超尺寸样例（某边>600）"


def test_seed_reset_idempotent():
    """reset 两次数据一致（幂等：先清后插）。"""
    seed_mod.reset()
    orders_a = _query("SELECT COUNT(*) FROM orders")[0][0]
    parts_a = _query("SELECT COUNT(*) FROM parts")[0][0]
    machines_a = _query("SELECT id FROM machines ORDER BY id")
    seed_mod.reset()
    assert _query("SELECT COUNT(*) FROM orders")[0][0] == orders_a
    assert _query("SELECT COUNT(*) FROM parts")[0][0] == parts_a
    assert _query("SELECT id FROM machines ORDER BY id") == machines_a


def test_seed_machines_spec():
    """设备构成符合 todo：SLA600×1+SLA450×2 / MJS600×1+MJS450×2 / SLM600×1。"""
    rows = _query("SELECT process, model_type, COUNT(*) FROM machines GROUP BY process, model_type ORDER BY process, model_type")
    spec = {(p, m): c for p, m, c in rows}
    assert spec[("SLA", "600")] == 1
    assert spec[("SLA", "450")] == 2
    assert spec[("MJS", "600")] == 1
    assert spec[("MJS", "450")] == 2
    assert spec[("SLM", "600")] == 1


# ---- M4b T4b.1：system_config 种子（产能/前道/路由） ----

def _config_rows():
    rows = _query("SELECT category, `key`, value FROM system_config ORDER BY category, `key`")
    return {(c, k): v for c, k, v in rows}


def test_seed_system_config_rows():
    """reset 后 system_config 含产能/前道/路由三类配置行（M4b T4b.1）。"""
    seed_mod.reset()
    cfg = _config_rows()
    assert cfg[("产能", "t_window_h")] == "24"
    assert cfg[("前道", "workers")] == "6"
    assert cfg[("前道", "shifts")] == "3"
    assert cfg[("前道", "shift_hours")] == "8"
    assert cfg[("前道", "changeover_min")] == "30"
    assert cfg[("前道", "per_part_eff_sla_mjs")] == "15"
    assert cfg[("前道", "per_part_eff_slm")] == "6"
    assert cfg[("前道", "per_part_eff_mix")] == "12"
    assert cfg[("前道", "plan_review_hours")] == "0.5"
    assert cfg[("路由", "routing_policy")].startswith("{")  # JSON 策略


def test_seed_system_config_idempotent():
    """reset 两次 system_config 行数不变（不在 SEED_TABLES 清空列表，INSERT IGNORE 幂等）。"""
    seed_mod.reset()
    n1 = len(_config_rows())
    seed_mod.reset()  # system_config 不清表 → INSERT IGNORE 跳过已存在行
    assert len(_config_rows()) == n1


def test_seed_system_config_readable_via_get_config():
    """get_config 可读到种子配置；缺行回落 default（M4b T4b.1 验收）。"""
    seed_mod.reset()
    from demo.config import get_config
    assert get_config("产能", "t_window_h") == "24"
    assert get_config("前道", "workers") == "6"
    assert get_config("产能", "no_such_key", "42") == "42"


# ---- M5a T5a.2：order_date 种子 + 预测配置 ----

def test_seed_order_date_filled_and_before_due():
    """reset 后 orders.order_date 全部非空且早于 due_date（预测聚合维度，M5a）。"""
    seed_mod.reset()
    rows = _query("SELECT order_date, due_date FROM orders")
    assert rows, "orders 为空"
    for ordered, due in rows:
        assert ordered is not None
        assert ordered < due


def test_seed_order_date_history_depth():
    """order_date 分布在 sim 起始日（2026-09-01）前 30 天内 -> 有历史供预测聚合。"""
    rows = _query("SELECT MIN(order_date), MAX(order_date) FROM orders")
    lo, hi = rows[0]
    assert hi < date(2026, 9, 1)
    assert lo >= date(2026, 8, 2)  # 9/1 前 30 天


def test_seed_forecast_config_rows():
    """预测配置 4 行可读（M5a T5a.2 用户确认口径：exponential/5 天/5 万/α0.3）。"""
    seed_mod.reset()
    cfg = _config_rows()
    assert cfg[("预测", "forecast_method")] == "exponential"
    assert cfg[("预测", "forecast_window")] == "5"
    assert cfg[("预测", "large_order_amount")] == "50000"
    assert cfg[("预测", "smoothing_alpha")] == "0.3"
    from demo.config import get_config
    assert get_config("预测", "forecast_window") == "5"


# ---- 定稿 v1 §5 seed 行：reset 联动清理排产链路表 ----

def _insert_scheduler_rows():
    """造 1 组排产链路行：版本→批次→前道任务→审批→sim 时钟（FK 无 CASCADE）。"""
    conn = seed_mod._connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO schedule_versions (created_at, triggered_by, params_json, result_json, status) "
                "VALUES (NOW(), 'test', '{}', '{}', '待审核')")
            vid = cur.lastrowid
            cur.execute(
                "INSERT INTO batches (id, schedule_version_id, order_ids, parts_json, process, model_type) "
                "VALUES (%s, %s, '[\"ORD001\"]', '[]', 'SLA', '600')",
                (f"{vid}-1", vid))
            cur.execute(
                "INSERT INTO preprocess_tasks (batch_id, part_count, man_hours, assigned_workers) "
                "VALUES (%s, 1, 0.5, 1)", (f"{vid}-1",))
            cur.execute(
                "INSERT INTO approvals (schedule_version_id, approver, action, time, note) "
                "VALUES (%s, 'test', '通过', NOW(), 'test')", (vid,))
            cur.execute(
                "INSERT INTO sim_clock (id, current_sim_time, real_ratio, running) "
                "VALUES (1, NOW(), 1, 0)")
        conn.commit()
    finally:
        conn.close()


def test_seed_reset_clears_scheduler_tables():
    """reset 联动清空排产链路表（FK 无 CASCADE）：升级/重跑后旧轮版本残留、
    其批次 order_ids 与重灌订单同号 → 跨轮重复打印（违反「同一订单只打印一次」）。"""
    seed_mod.reset()
    _insert_scheduler_rows()
    assert _query("SELECT COUNT(*) FROM schedule_versions")[0][0] == 1
    assert _query("SELECT COUNT(*) FROM batches")[0][0] == 1
    assert _query("SELECT COUNT(*) FROM preprocess_tasks")[0][0] == 1
    assert _query("SELECT COUNT(*) FROM approvals")[0][0] == 1
    assert _query("SELECT COUNT(*) FROM sim_clock")[0][0] == 1

    seed_mod.reset()

    assert _query("SELECT COUNT(*) FROM schedule_versions")[0][0] == 0
    assert _query("SELECT COUNT(*) FROM batches")[0][0] == 0
    assert _query("SELECT COUNT(*) FROM preprocess_tasks")[0][0] == 0
    assert _query("SELECT COUNT(*) FROM approvals")[0][0] == 0
    assert _query("SELECT COUNT(*) FROM sim_clock")[0][0] == 0
    # 重灌订单全为待排队（无旧版本残留锁定可被跨轮误通过）
    assert _query("SELECT COUNT(*) FROM orders WHERE status != '待排队'")[0][0] == 0
