"""assessment.py 计算核心测试（M4b T4b.2）。

覆盖口径（需求规格 §8 + §3.13/§3.15）：
  三区制边界（需求 vs 90%/100% 可用）、T 窗口消化（已腾出+当天腾出、打印中排除）、
  缺机器数（⌈缺口÷单台 T 窗口产能⌉ 按工艺）、前道净产能（45人·时/天）、
  前道任务时长（件数÷(人×件人效)+0.5h）、CTP（现有占用全排完+新单机时，max(设备,前道)）。

纯函数测试不连库；拼装层（load_assessment 等）连 MySQL。
"""
from datetime import datetime, timedelta

import pytest

from flex_fab_agent.scheduler import assessment
from flex_fab_agent.tools.data import get_connection


def test_zone_color_boundaries():
    """三区制边界：恰 90%→绿、恰 100%→黄、超 100%→红（§8）。"""
    assert assessment.zone_color(0.0, 100) == "绿"
    assert assessment.zone_color(90.0, 100) == "绿"    # 恰 90%
    assert assessment.zone_color(90.01, 100) == "黄"   # 90% 边线上界
    assert assessment.zone_color(100.0, 100) == "黄"   # 恰 100%
    assert assessment.zone_color(100.01, 100) == "红"  # 超 100%
    assert assessment.zone_color(50, 0) == "红"        # 无产能 → 红


def test_zone_color_rounding():
    """浮点误差不越界：90/100=0.9 判绿而非黄。"""
    assert assessment.zone_color(90.0 / 100.0 * 100, 100) == "绿"


def test_preprocess_net_capacity_h():
    """前道净产能：3班×8h − 3×30min换班 = 22.5h/天 = 45人·时（§8）。"""
    # 3班×8h=24h，减 3×0.5h 换班 = 22.5h
    assert assessment.preprocess_net_capacity_h(shifts=3, shift_hours=8,
                                                changeover_min=30, workers=6) == 45.0
    # 单班制无换班：8h × 6人 = 48人·时
    assert assessment.preprocess_net_capacity_h(shifts=1, shift_hours=8,
                                                changeover_min=0, workers=6) == 48.0


def test_preprocess_task_hours():
    """前道任务时长 = 件数÷(人×件人效) + 方案审核分摊（§8）。"""
    # 100 件 / (2人 × 15件/人·h) + 0.5h = 3.33 + 0.5 = 3.83h
    h = assessment.preprocess_task_hours(part_count=100, assigned_workers=2,
                                         per_part_eff=15, plan_review_hours=0.5)
    assert abs(h - (100 / 30 + 0.5)) < 1e-9
    # 前道完成 ≤ 打印开始：任务时长不含等待
    assert h > 0


def test_clear_eta_hours():
    """前道池清空日历小时 = 人·时 ÷ 日净产能 × 24h/天（CR：勿把总人·时当小时数）。"""
    assert assessment.clear_eta_hours(100, 45) == pytest.approx(100 * 24 / 45, rel=1e-9)  # 53.3h
    assert assessment.clear_eta_hours(45, 45) == pytest.approx(24, rel=1e-9)              # 1 天
    assert assessment.clear_eta_hours(10, 0) == 10  # 净产能未知回落原值


def test_t_window_availability():
    """T 窗口可用产能 = Σ(已腾出×T) + Σ(当天腾出×(T−预计腾出时间))；打印中排除了。"""
    now = datetime(2026, 9, 1, 8, 0, 0)
    t_window_h = 24
    machines = [
        {"id": "M1", "process": "SLA", "status": "空闲"},                       # 已腾出 → +24
        {"id": "M2", "process": "SLA", "status": "打印中", "current_batch_id": "B1"},  # 当天腾出(4h后) → +20
        {"id": "M3", "process": "SLA", "status": "打印中", "current_batch_id": "B2"},  # end 30h 后 > T → 排除
        {"id": "M4", "process": "MJS", "status": "空闲"},                       # +24
        {"id": "M5", "process": "SLM", "status": "维修中"},                     # 非空闲非打印 → 不算已腾出
    ]
    batches = [
        {"id": "B1", "machine_id": "M2", "end_time": now + timedelta(hours=4)},  # 4h 后腾出
        {"id": "B2", "machine_id": "M3", "end_time": now + timedelta(hours=30)},  # 超 T → 排除
    ]
    avail = assessment.t_window_availability(machines, batches, now, t_window_h)
    assert avail["SLA"] == pytest.approx(24 + (24 - 4), rel=1e-9)  # 24 + 20
    assert avail["MJS"] == pytest.approx(24, rel=1e-9)
    assert "SLM" not in avail or avail["SLM"] == 0  # 维修中不计


def test_missing_machines():
    """缺机器数 = ⌈缺口 ÷ 单台 T 窗口产能⌉ 按工艺分群取整（§8）。"""
    assert assessment.missing_machines(gap_h=50, t_window_h=24) == 3   # 50/24=2.08 → 3
    assert assessment.missing_machines(gap_h=24, t_window_h=24) == 1   # 恰整除 → 1
    assert assessment.missing_machines(gap_h=0, t_window_h=24) == 0    # 无缺口
    assert assessment.missing_machines(gap_h=-5, t_window_h=24) == 0   # 富余 → 0


def test_part_machine_hours():
    """单件时长=Z高÷工艺速率；新单机时=件数×单件时长（§8）。"""
    h = assessment.part_machine_hours(material="SLA", height_mm=100, rate_mm_h=50)
    assert h == pytest.approx(100 / 50, rel=1e-9)  # 2h
    # SLM 15mm/h 更慢
    h = assessment.part_machine_hours(material="SLM", height_mm=100, rate_mm_h=15)
    assert h == pytest.approx(100 / 15, rel=1e-9)


def test_ctp_pure():
    """CTP = max(设备现有占用完成+新单机时, 前道占用完成+新单前道时长)（§8 保守不偏乐观）。"""
    ctp = assessment.compute_ctp(
        material="SLA", quantity=10, height_mm=100, rate_mm_h=50,
        preprocess_eff=15, plan_review_hours=0.5,
        machine_load_end=datetime(2026, 9, 5, 12, 0, 0),   # 该工艺现有占用完成
        preprocess_queue_end=datetime(2026, 9, 6, 0, 0, 0),  # 前道池完成
        assigned_workers=2,
    )
    # 新单机时 = 10件 × 2h = 20h → 设备侧 9/5 12:00 + 20h = 9/6 08:00
    # 前道时长 = 10件/(2人×15) + 0.5 = 0.333+0.5 = 0.833h → 前道侧 9/6 00:00 + 0.833h
    # CTP = max(9/6 08:00, 9/6 00:50) = 9/6 08:00
    assert ctp["machine_ctp"] == datetime(2026, 9, 6, 8, 0, 0)
    assert ctp["preprocess_ctp"] == datetime(2026, 9, 6, 0, 50, 0)
    assert ctp["ctp"] == datetime(2026, 9, 6, 8, 0, 0)
    assert ctp["bottleneck"] == "设备"


# ────────────── 拼装层集成测试（连库，reset 后验证结构） ──────────────


@pytest.fixture()
def seeded_mysql():
    """重建 MySQL 业务库 + 切 mysql 数据源（与 test_solver/test_snapshot 同款）。"""
    from flex_fab_agent.simulator import seed as seed_mod
    seed_mod.reset()
    import os
    os.environ["FLEX_FAB_AGENT_DATA_SOURCE"] = "mysql"
    yield
    os.environ.pop("FLEX_FAB_AGENT_DATA_SOURCE", None)


def test_load_assessment_structure(seeded_mysql):
    """reset 后 load_assessment 输出四段结构完整、三区制颜色合法、前道参数生效。"""
    a = assessment.load_assessment()
    assert a["t_window_h"] == 24
    assert set(a["distribution"].keys()) == {"在途", "排队", "完成"}
    assert isinstance(a["orders_eta"], list)
    assert isinstance(a["overdue_alerts"], list)
    assert isinstance(a["t_window"], dict)
    assert a["preprocess"]["workers"] == 6
    assert a["preprocess"]["net_capacity_h_per_day"] == pytest.approx(45.0, rel=1e-9)
    assert a["zone"], "至少一个工艺有三区制判定"
    assert all(z in ("绿", "黄", "红") for z in a["zone"].values())


def test_compute_ctp_from_db_structure(seeded_mysql):
    """compute_ctp_from_db 连库跑通，返回 ctp/瓶颈/机时；超尺寸与未知工艺报错。"""
    r = assessment.compute_ctp_from_db("SLA", 10, 100)
    assert "ctp" in r and "bottleneck" in r and "machine_hours" in r
    assert r["machine_hours"] == pytest.approx(10 * 100 / 50, rel=1e-9)  # 20h
    # 带交期：结构含 meet_due
    r2 = assessment.compute_ctp_from_db("SLM", 5, 50, due_date="2026-12-31")
    assert "meet_due" in r2
    with pytest.raises(ValueError):
        assessment.compute_ctp_from_db("CNC", 1, 100)  # 未知工艺
    with pytest.raises(ValueError):
        assessment.compute_ctp_from_db("SLA", 1, 650)  # 超尺寸


# ---- M5a T5a.7：预测校准 CTP ----

def test_ctp_calibrated_not_earlier(seeded_mysql):
    """calibrated_ctp ≥ 常规 ctp（预测预留只会推迟，不提前）。"""
    r = assessment.compute_ctp_from_db("SLA", 10, 100)
    assert r["forecast_reserved_days"] >= 0
    assert r["calibrated_ctp"] >= r["ctp"]
    assert (r["calibrated_ctp"] - r["ctp"]).days == r["forecast_reserved_days"]


def test_ctp_calibrated_no_forecast(seeded_mysql, monkeypatch):
    """预测机时=0（无历史）时 calibrated == 常规 ctp。"""
    from flex_fab_agent.forecast import forecaster
    empty = {"method": "exponential", "alpha": 0.3, "window": 5,
             "days": [], "materials": {}, "note": "无历史订单可聚合"}
    monkeypatch.setattr(forecaster, "forecast",
                        lambda n_days=None, tenant_id="": empty)
    r = assessment.compute_ctp_from_db("SLA", 10, 100)
    assert r["forecast_reserved_days"] == 0
    assert r["calibrated_ctp"] == r["ctp"]


def test_ctp_calibrated_known_reserved_days(seeded_mysql, monkeypatch):
    """已知预测机时 -> 预留天数 = ⌈机时 ÷ (设备数×24×0.9)⌉（SLA 3 台：64.8h/天）。"""
    from flex_fab_agent.forecast import forecaster
    fake = {"method": "exponential", "alpha": 0.3, "window": 5, "days": ["d"] * 5,
            "materials": {"SLA": [{"date": f"d{i}", "parts": 1, "hours": 65.0}
                                  for i in range(5)]}, "note": ""}
    monkeypatch.setattr(forecaster, "forecast",
                        lambda n_days=None, tenant_id="": fake)
    r = assessment.compute_ctp_from_db("SLA", 10, 100)
    # 5×65=325h，SLA 3 台 -> 64.8h/天 -> 325/64.8=5.01 -> ⌈⌉=6 天
    assert r["forecast_reserved_days"] == 6
    assert r["calibrated_ctp"] > r["ctp"]


# ---- 定稿 v1 §5/§6 T4.1/T4.2：读路径观测口径（落库 SUM + 多版本聚合） ----


def _insert_version(conn, status="待审核"):
    """插入排产版本（函数级 seeded_mysql 已清空链路表，测试数据自隔离）。"""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO schedule_versions (created_at, triggered_by, params_json, "
            "result_json, status) VALUES (NOW(), 'test', '{}', '{}', %s)", (status,))
        return cur.lastrowid


def _insert_batch(conn, bid, vid, status="前道", approval="通过",
                  process="SLA", start="2026-09-01 08:00:00",
                  end="2026-09-01 10:00:00"):
    """插入批次行（链到版本 vid）。"""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO batches (id, schedule_version_id, order_ids, parts_json, process, "
            "model_type, machine_id, start_time, end_time, post_process_end, status, "
            "approval_status, source) VALUES (%s, %s, '[\"ORD001\"]', '[]', %s, '600', "
            "'M0001', %s, %s, %s, %s, %s, '整批')",
            (bid, vid, process, start, end, end, status, approval))


def _insert_task(conn, bid, man_hours, part_count=5):
    """插入前道任务（链到批次 bid）。"""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO preprocess_tasks (batch_id, part_count, man_hours, "
            "assigned_workers, start_time, end_time) VALUES (%s, %s, %s, 1, "
            "'2026-09-01 06:00:00', '2026-09-01 08:00:00')", (bid, part_count, man_hours))


def test_preprocess_load_reads_persisted_sum(seeded_mysql):
    """T4.1：preprocess_load 读数=落库 SUM(man_hours)（含分摊），联批次过滤
    status='前道' AND approval_status='通过'——SLA/SLM 各一任务入池，
    待审核批次任务不入池（待审窗口假空闲）。"""
    conn = get_connection()
    try:
        vid = _insert_version(conn)
        _insert_batch(conn, f"{vid}-B1", vid, approval="通过", process="SLA")
        _insert_batch(conn, f"{vid}-B2", vid, approval="通过", process="SLM")
        _insert_batch(conn, f"{vid}-B3", vid, approval="待审核", process="SLA")
        _insert_task(conn, f"{vid}-B1", 0.83)
        _insert_task(conn, f"{vid}-B2", 1.00)
        _insert_task(conn, f"{vid}-B3", 9.99)  # 待审核批次任务：不入池
        conn.commit()
    finally:
        conn.close()
    pp = assessment.preprocess_load()
    assert pp["pending_tasks"] == 2
    assert pp["remaining_man_hours"] == pytest.approx(0.83 + 1.00, abs=0.01)
    assert pp["workers"] == 6
    assert pp["net_capacity_h_per_day"] == pytest.approx(45.0, rel=1e-9)
    assert pp["bottleneck"] is False
    assert pp["eta_clear"]  # 有剩余人·时 → 预计清空时刻非空


def test_preprocess_load_released_on_上机(seeded_mysql):
    """T4.1：批次前道→待上机（E 门禁通过后推进）即释放池——remaining_man_hours 下降、
    pending_tasks 减一，不重复计在途人工。"""
    conn = get_connection()
    try:
        vid = _insert_version(conn)
        _insert_batch(conn, f"{vid}-B1", vid, approval="通过", process="SLA")
        _insert_batch(conn, f"{vid}-B2", vid, approval="通过", process="SLA")
        _insert_task(conn, f"{vid}-B1", 0.83)
        _insert_task(conn, f"{vid}-B2", 1.00)
        conn.commit()
    finally:
        conn.close()
    assert assessment.preprocess_load()["remaining_man_hours"] == pytest.approx(1.83, abs=0.01)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE batches SET status='待上机' WHERE id=%s", (f"{vid}-B1",))
        conn.commit()
    finally:
        conn.close()
    after = assessment.preprocess_load()
    assert after["remaining_man_hours"] == pytest.approx(1.00, abs=0.01)
    assert after["pending_tasks"] == 1


def test_latest_batches_aggregates_active_versions(seeded_mysql):
    """T4.2：_latest_batches 弃 MAX(id) 聚合所有含未完成批次且非「已驳回」版本——
    插单后旧版本在途订单可跟踪；驳回版本批次不入聚合；全完成版本退出。"""
    conn = get_connection()
    try:
        v1 = _insert_version(conn, "待审核")
        _insert_batch(conn, f"{v1}-B1", v1, status="打印中", approval="通过")
        v2 = _insert_version(conn, "待审核")
        _insert_batch(conn, f"{v2}-B2", v2, status="前道", approval="通过")
        v3 = _insert_version(conn, "已驳回")           # 驳回版本：不入聚合
        _insert_batch(conn, f"{v3}-B3", v3, status="前道", approval="通过")
        v4 = _insert_version(conn, "待审核")           # 全完成版本：退出聚合
        _insert_batch(conn, f"{v4}-B4", v4, status="完成", approval="通过")
        conn.commit()
    finally:
        conn.close()
    ids = {b["id"] for b in assessment._latest_batches()}
    assert f"{v1}-B1" in ids and f"{v2}-B2" in ids  # 两活动版本并存，旧版本在途不漏
    assert f"{v3}-B3" not in ids                    # 驳回版本批次不入
    assert f"{v4}-B4" not in ids                    # 全完成版本退出
