"""scheduler_tools.py 4 实装工具测试（M4a T4a.1，需 WSL MySQL）。

覆盖：run_scheduling 落库、query_schedule 最新/指定版本、query_sim_events
过滤、approve_schedule 通过/驳回/非法动作/版本不存在。
"""
import re

import pytest

from demo.scheduler.snapshot import load_snapshot
from demo.scheduler.solver import persist, solve
from demo.simulator import seed as seed_mod
from demo.tools import scheduler_tools
from demo.scheduler import assessment
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
    _exec("DELETE FROM preprocess_tasks WHERE batch_id LIKE %s", (f"{vid}-%",))
    _exec("DELETE FROM batches WHERE schedule_version_id=%s", (vid,))
    _exec("DELETE FROM schedule_versions WHERE id=%s", (vid,))
    # 还原 persist 原子锁定的订单（否则下一个 pending_version 触发 PersistConcurrentLockError）
    _exec("UPDATE orders SET status='待排队' WHERE id='ORD001'")


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
        _exec("DELETE FROM approvals WHERE schedule_version_id=%s", (v["id"],))
        _exec("DELETE FROM preprocess_tasks WHERE batch_id LIKE %s", (f"{v['id']}-%",))
        _exec("DELETE FROM batches WHERE schedule_version_id=%s", (v["id"],))
        _exec("DELETE FROM schedule_versions WHERE id=%s", (v["id"],))
    # 还原 persist 原子锁定的全部种子订单（否则后续 pending_version 触发 PersistConcurrentLockError）
    _exec("UPDATE orders SET status='待排队' WHERE status='已审核'")


def test_run_scheduling_exclude_keeps_pending():
    """run_scheduling(exclude_order_ids)：被排除订单不进求解、persist 不锁定（保持待排队）。"""
    import json

    # 复位全部订单待排队，保证可从种子取一批待排队
    _exec("UPDATE orders SET status='待排队' WHERE status != '完成'")
    snap = load_snapshot()
    assert snap["orders"], "种子须有待排队订单"
    keep_id = snap["orders"][0]["id"]  # 任意保留一单
    before = _rows("SELECT MAX(id) AS id FROM schedule_versions")[0]["id"] or 0
    out = scheduler_tools.run_scheduling(exclude_order_ids=[keep_id])
    assert "版本" in out, f"排除 1 单后其余应可求解建版，实际: {out}"
    # 新版本批次不含被排除订单
    after = _rows(
        "SELECT id FROM schedule_versions WHERE id > %s ORDER BY id DESC", (before,))
    for v in after:
        oids = [row["order_ids"] for row in _rows(
            "SELECT order_ids FROM batches WHERE schedule_version_id=%s", (v["id"],))]
        ids = {oid for raw in oids if raw for oid in json.loads(raw)}
        assert keep_id not in ids, f"被排除订单 {keep_id} 不得进批次"
    # 被排除订单保持待排队
    row = _rows("SELECT status FROM orders WHERE id=%s", (keep_id,))
    assert row and row[0]["status"] == "待排队", f"排除订单应保持待排队，实际 {row}"
    # 清理版本 + 还原订单
    for v in after:
        _exec("DELETE FROM approvals WHERE schedule_version_id=%s", (v["id"],))
        _exec("DELETE FROM preprocess_tasks WHERE batch_id LIKE %s", (f"{v['id']}-%",))
        _exec("DELETE FROM batches WHERE schedule_version_id=%s", (v["id"],))
        _exec("DELETE FROM schedule_versions WHERE id=%s", (v["id"],))
    _exec("UPDATE orders SET status='待排队' WHERE status='已审核'")


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


def test_query_ctp_calibrated_and_large_order(mysql_source):
    """M5a：文案含两档承诺（CTP + 承诺期含预测预留）；amount≥5 万大单标注。"""
    out = scheduler_tools.query_ctp(material="SLA", quantity=10, height_mm=100)
    assert "CTP（最短可交付）" in out
    assert "承诺期（含预测预留）" in out
    assert "90% 日产能" in out
    assert "大单" not in out  # 未传金额不标注
    out2 = scheduler_tools.query_ctp(material="SLA", quantity=10, height_mm=100,
                                     amount=80000)
    assert "大单标注" in out2 and "承诺期" in out2
    out3 = scheduler_tools.query_ctp(material="SLA", quantity=10, height_mm=100,
                                     amount=10000)
    assert "大单" not in out3  # 低于阈值不标注


# ---- M5a T5a.8：query_kpi 坏件口径（bad_parts 优先，回落 sim_events） ----

def _scrap_count_in_kpi(out: str) -> int:
    m = re.search(r"坏件 (\d+) / 完工", out)
    assert m, f"良率行未找到坏件计数：{out}"
    return int(m.group(1))


def test_query_kpi_scrap_from_bad_parts(mysql_source):
    """query_kpi 良率与 bad_parts 计数一致（SUM(part_count)）。"""
    _exec("DELETE FROM bad_parts")
    _exec("DELETE FROM sim_events WHERE event_type='scrap'")
    _exec("INSERT INTO bad_parts (batch_id, machine_id, material, part_count, sim_time) "
          "VALUES ('TESTKPI1', 'M0001', 'SLA', 7, '2026-08-23 10:00:00')")
    try:
        out = scheduler_tools.query_kpi()
        assert _scrap_count_in_kpi(out) == 7
    finally:
        _exec("DELETE FROM bad_parts")


def test_query_kpi_scrap_falls_back_to_sim_events(mysql_source):
    """空 bad_parts 回落 sim_events 口径（COUNT scrap 事件，兼容旧库）。"""
    _exec("DELETE FROM bad_parts")
    _exec("DELETE FROM sim_events WHERE event_type='scrap'")
    _exec("INSERT INTO sim_events (sim_time, event_type, payload_json, status) "
          "VALUES ('2026-08-23 10:00:00', 'scrap', '{}', 'fired')")
    _exec("INSERT INTO sim_events (sim_time, event_type, payload_json, status) "
          "VALUES ('2026-08-23 11:00:00', 'scrap', '{}', 'fired')")
    try:
        out = scheduler_tools.query_kpi()
        assert _scrap_count_in_kpi(out) == 2
    finally:
        _exec("DELETE FROM sim_events WHERE event_type='scrap' AND payload_json='{}'")


# ---- M5a T5a.6：query_forecast 实装 ----

def test_query_forecast_seed_5days(mysql_source):
    """seed 后输出 5 天预测表（分材料件数/机时）+ 口径说明。"""
    seed_mod.reset()
    out = scheduler_tools.query_forecast()
    assert "预测" in out and "指数平滑" in out and "窗口 5 天" in out and "α=0.3" in out
    assert "order_date" in out  # 口径说明
    for m in ("SLA", "MJS", "SLM"):  # seed 三材料全覆盖
        assert f"【{m}】" in out
    assert "日期" in out and "件数" in out and "机时(h)" in out
    # 默认 5 天：任一材料段含 5 行数据（表头+分隔线后 5 个日期行）
    sla = out.split("【SLA】")[1].split("【")[0]
    dates = [ln for ln in sla.splitlines() if ln.startswith("| 2026-")]
    assert len(dates) == 5


def test_query_forecast_days_override(mysql_source, monkeypatch):
    """days 可改窗口；非法输入回落配置值（None）。"""
    real = scheduler_tools.forecaster.forecast
    captured = {}

    def _spy(n_days=None, tenant_id=""):
        captured["n_days"] = n_days
        return real(n_days=n_days, tenant_id=tenant_id)

    monkeypatch.setattr(scheduler_tools.forecaster, "forecast", _spy)
    scheduler_tools.query_forecast(days="3")
    assert captured["n_days"] == 3
    scheduler_tools.query_forecast(days="abc")   # 非法 -> 回落配置窗口
    assert captured["n_days"] is None
    scheduler_tools.query_forecast(days="-1")    # 负数 -> 回落配置窗口
    assert captured["n_days"] is None
    scheduler_tools.query_forecast()             # 空 -> 配置窗口
    assert captured["n_days"] is None


# ---- M5a T5a.9：query_yield（良率下钻 + LLM 改善建议） ----

@pytest.fixture()
def yield_bad_rows():
    """构造两台设备不同坏件量（M0001=5, M0002=2）+ M0001 一次 MTBF 故障。用后清理。"""
    _exec("DELETE FROM bad_parts")
    _exec("DELETE FROM sim_events WHERE event_type='machine_failure'")
    _exec("INSERT INTO bad_parts (batch_id, machine_id, material, part_count, sim_time) "
          "VALUES ('YB1', 'M0001', 'SLA', 3, '2026-08-23 10:00:00'), "
          "('YB1', 'M0001', 'SLA', 2, '2026-08-23 11:00:00'), "
          "('YB2', 'M0002', 'MJS', 2, '2026-08-23 12:00:00')")
    _exec("INSERT INTO sim_events (sim_time, event_type, payload_json, status) "
          "VALUES ('2026-08-23 09:00:00', 'machine_failure', "
          "'{\"machine_id\": \"M0001\"}', 'fired')")
    yield
    _exec("DELETE FROM bad_parts")
    _exec("DELETE FROM sim_events WHERE event_type='machine_failure'")


def test_query_yield_drilldown_order_and_rate(mysql_source, yield_bad_rows, monkeypatch):
    """设备下钻坏件降序（坏件多者在前）；良率 = 1−坏件/完工；MTBF 故障列在表头。"""
    monkeypatch.setattr(scheduler_tools, "_done_parts_by_machine",
                        lambda: {"M0001": 50, "M0002": 10})
    out = scheduler_tools.query_yield()
    assert "总览" in out and "坏件 7 件 / 完工 60 件" in out
    # 设备下钻坏件降序：M0001(5) 在 M0002(2) 之前
    assert out.index("M0001") < out.index("M0002")
    # 批次下钻同样坏件降序：YB1(5) 在 YB2(2) 之前
    assert out.index("YB1") < out.index("YB2")
    # 良率计算：M0001=1−5/50=90.00%，M0002=1−2/10=80.00%
    assert "90.00%" in out and "80.00%" in out
    assert "MTBF故障" in out


def test_query_yield_llm_advice_includes_summary(mysql_source, yield_bad_rows, monkeypatch):
    """LLM 建议：归因摘要（良率/设备下钻）进 prompt；有内容时直接返回。"""
    import types
    monkeypatch.setattr(scheduler_tools, "_done_parts_by_machine",
                        lambda: {"M0001": 50, "M0002": 10})
    captured = {}
    msg = types.SimpleNamespace(content="建议：M0001 优先检修，核查曝光参数。")
    fake_resp = types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

    def _fake_llm(system_prompt, user_prompt, **_kwargs):
        captured["prompt"] = user_prompt
        return fake_resp

    monkeypatch.setattr("demo.core.llm_client.call_llm_simple", _fake_llm)
    out = scheduler_tools.query_yield()
    assert "检修" in out and "核查曝光参数" in out  # LLM 内容直接返回
    assert captured["prompt"], "LLM prompt 须含归因摘要"
    assert "良率" in captured["prompt"] and "坏件" in captured["prompt"]
    assert "M0001" in captured["prompt"]  # 设备下钻摘要进 prompt


def test_query_yield_llm_failure_falls_back_to_rules(mysql_source, yield_bad_rows, monkeypatch):
    """LLM 抛异常降级规则模板：设备检修 + 材料参数提示，不中断工具。"""
    monkeypatch.setattr(scheduler_tools, "_done_parts_by_machine",
                        lambda: {"M0001": 50, "M0002": 10})

    def _boom(*_args, **_kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr("demo.core.llm_client.call_llm_simple", _boom)
    out = scheduler_tools.query_yield()
    assert "检修" in out                      # 设备 M0001 坏件最多 -> 检修建议
    assert "SLA" in out and "曝光" in out      # 材料 SLA 建议（曝光参数）
    assert "MJS" in out and "喷射头" in out    # 材料 MJS 建议（喷射头）


def test_query_yield_no_bad_parts_friendly(mysql_source):
    """无坏件数据：返回友好提示（良率 100%，无需归因），不报错。"""
    _exec("DELETE FROM bad_parts")
    try:
        out = scheduler_tools.query_yield()
        assert "良率 100%" in out and "暂无坏件" in out
    finally:
        _exec("DELETE FROM bad_parts")


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
    _exec("DELETE FROM batches WHERE id='BT'")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(id) FROM schedule_versions")
            vid = (cur.fetchone()[0] or 0) + 1  # 运行时取 max+1，防历史残留版本覆盖
    _exec(f"INSERT INTO schedule_versions (id, created_at, triggered_by, status) "
          f"VALUES ({vid}, '2026-09-01 08:00:00', 'test', '已审核')")
    try:
        _exec(f"INSERT INTO batches (id, schedule_version_id, order_ids, process, machine_id, "
              f"start_time, end_time, post_process_end, status, approval_status) "
              f"VALUES ('BT', {vid}, '[\"ORD001\"]', 'SLA', 'M0001', "
              f"'2026-09-01 08:00:00', '2026-09-01 10:00:00', '2026-09-01 12:00:00', "
              f"'打印中', '通过')")
        out = scheduler_tools.query_order_tracking("ORD001")
        assert "打印中" in out
        assert "2026-09-01 12:00" in out, "预计完成须取 post_process_end"
    finally:
        _exec(f"DELETE FROM approvals WHERE schedule_version_id={vid}")
        _exec(f"DELETE FROM batches WHERE schedule_version_id={vid}")
        _exec(f"DELETE FROM schedule_versions WHERE id={vid}")


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


# ---- M5b T5b.2：kpi_metrics 结构化抽取（与 query_kpi 同源） ----

def test_kpi_metrics_fields(mysql_source):
    """kpi_metrics 返回全字段结构化指标；on_time_rate 与分子分母自洽。"""
    m = scheduler_tools.kpi_metrics()
    assert set(m) >= {"generated_at", "on_time", "sample", "on_time_rate", "delay_total",
                      "cabin_utilization", "batch_count", "done_parts", "scrap",
                      "yield_rate", "preprocess"}
    assert set(m["preprocess"]) == {"utilization", "remaining_man_hours",
                                    "net_capacity_h_per_day", "bottleneck"}
    if m["sample"]:
        assert m["on_time_rate"] == round(m["on_time"] / m["sample"], 4)
    else:
        assert m["on_time_rate"] is None


def test_kpi_metrics_consistent_with_query_kpi(mysql_source):
    """口径一致：kpi_metrics 数值与 query_kpi 格式化输出互相印证。"""
    m = scheduler_tools.kpi_metrics()
    out = scheduler_tools.query_kpi()
    assert f"¥{m['delay_total']:.2f}" in out
    if m["on_time_rate"] is not None:
        assert f"{m['on_time_rate'] * 100:.1f}%" in out
        assert f"（{m['on_time']}/{m['sample']} 单按期）" in out
    if m["yield_rate"] is not None:
        assert f"{m['yield_rate'] * 100:.1f}%" in out
    assert f"（1 − 坏件 {m['scrap']} / 完工 {m['done_parts']} 件）" in out


def test_kpi_metrics_json_serializable(mysql_source):
    """metrics dict 可 json.dumps（看板落盘 metrics_json 前提）。"""
    import json
    s = json.dumps(scheduler_tools.kpi_metrics(), default=str)
    assert "on_time_rate" in s and "preprocess" in s


# ---- M6 T6.1：csv 模式优雅降级（存量 bug：machines.csv 无 id/cabin_size 列） ----

def test_kpi_metrics_csv_mode_degrades(monkeypatch):
    """csv 模式下 cabin_utilization 降级 None，不抛 KeyError 'id'。"""
    monkeypatch.setenv("DEMO_DATA_SOURCE", "csv")
    m = scheduler_tools.kpi_metrics()
    assert m["cabin_utilization"] is None


def test_query_kpi_csv_mode_no_crash(monkeypatch):
    """csv 模式 query_kpi 输出完整（舱利用率行显示暂无提示），不抛错。"""
    monkeypatch.setenv("DEMO_DATA_SOURCE", "csv")
    out = scheduler_tools.query_kpi()
    assert "📈 排产 KPI" in out
    assert "暂无设备数据" in out


def test_query_load_assessment_csv_mode_no_crash(monkeypatch):
    """csv 模式 load_assessment 不抛 KeyError 'process'；旧枚举归一后排队分布可读。"""
    monkeypatch.setenv("DEMO_DATA_SOURCE", "csv")
    a = assessment.load_assessment()
    assert "ORD005" in a["distribution"]["排队"]   # 排期中→待排队
    out = scheduler_tools.query_load_assessment()
    assert "📊 产能负载评估" in out
    assert "❌" not in out


# ---- M5a T5a.12：KPI tick 联动 E2E ----

def _insert_kpi_version_row(vid):
    """新建排产版本（显式 id）。"""
    _exec(f"INSERT INTO schedule_versions (id, created_at, triggered_by, status) "
          f"VALUES ({vid}, '2026-09-01 08:00:00', 'test', '已审核')")


def _insert_kpi_batch(bid, vid, oid, machine):
    """版本下新增批次（打印中）+ 设备占用。"""
    _exec("INSERT INTO batches (id, schedule_version_id, order_ids, process, model_type, "
          "machine_id, start_time, end_time, post_process_end, status, approval_status) "
          "VALUES (%s, %s, %s, 'SLA', '600', %s, "
          "'2026-09-01 08:00:00', '2026-09-01 10:00:00', '2026-09-01 11:00:00', "
          "'打印中', '通过')", (bid, vid, f'["{oid}"]', machine))
    _exec("UPDATE machines SET status='打印中', current_batch_id=%s WHERE id=%s",
          (bid, machine))


def _max_version_id():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(id) FROM schedule_versions")
            return (cur.fetchone()[0] or 0) + 1


@pytest.fixture()
def kpi_tick_env(mysql_source):
    """KPI tick 联动环境：T-ORD001 已排产（V1，T-B0001 打印中）+ T-ORD002 新到未排产。
    清基线保证 KPI 数值仅由本环境数据驱动；用后清理。"""
    _exec("DELETE FROM sim_events")
    _exec("DELETE FROM bad_parts")
    _exec("DELETE FROM state_change_log WHERE entity_id LIKE 'T-%%' OR entity_id LIKE 'M000%%'")
    _exec("DELETE FROM preprocess_tasks WHERE batch_id LIKE 'T-%%'")
    # 残留在途批次（含其前道任务）清空：保证 tick 只推进本环境批次、scrap 计数确定
    _exec("DELETE FROM preprocess_tasks WHERE batch_id IN "
          "(SELECT id FROM batches WHERE status IN ('打印中','静置中','待上机','前道'))")
    _exec("DELETE FROM batches WHERE status IN ('打印中','静置中','待上机','前道')")
    _exec("DELETE FROM approvals WHERE schedule_version_id IN "
          "(SELECT id FROM schedule_versions WHERE triggered_by='test')")
    _exec("DELETE FROM schedule_versions WHERE triggered_by='test'")
    _exec("DELETE FROM parts WHERE id LIKE 'T-%%'")    # 先删 parts（引用 orders）
    _exec("DELETE FROM orders WHERE id LIKE 'T-%%'")
    _exec("UPDATE machines SET status='空闲', current_batch_id=NULL WHERE id IN ('M0001','M0002')")
    _exec("INSERT INTO orders (id, customer_id, amount, urgent, priority, due_date, status, tenant_id) "
          "VALUES ('T-ORD001', 'C001', 100000, 0, 40, '2026-09-10', '打印中', 'default'), "
          "('T-ORD002', 'C001', 60000, 0, 20, '2026-09-08', '打印中', 'default')")
    _exec("INSERT INTO parts (id, order_id, product_id, name, quantity, material, "
          "length, width, height, weight, tenant_id) VALUES "
          "('T-P0001', 'T-ORD001', 'P-T1', '测试件1', 3, 'SLA', 100, 100, 100, 1, 'default'), "
          "('T-P0002', 'T-ORD002', 'P-T2', '测试件2', 5, 'SLA', 100, 100, 100, 1, 'default')")
    v1 = _max_version_id()
    _insert_kpi_version_row(v1)
    _insert_kpi_batch("T-B0001", v1, "T-ORD001", "M0001")
    yield {"v1": v1}
    _exec("DELETE FROM state_change_log WHERE entity_id LIKE 'T-%%' OR entity_id LIKE 'M000%%'")
    _exec("DELETE FROM preprocess_tasks WHERE batch_id LIKE 'T-%%'")
    _exec("DELETE FROM bad_parts WHERE batch_id LIKE 'T-%%'")
    _exec("DELETE FROM batches WHERE id LIKE 'T-%%'")
    _exec("DELETE FROM approvals WHERE schedule_version_id IN "
          "(SELECT id FROM schedule_versions WHERE triggered_by='test')")
    _exec("DELETE FROM schedule_versions WHERE triggered_by='test'")
    _exec("DELETE FROM parts WHERE id LIKE 'T-%%'")    # 先删 parts（引用 orders）
    _exec("DELETE FROM orders WHERE id LIKE 'T-%%'")
    _exec("DELETE FROM sim_events")
    _exec("UPDATE machines SET status='空闲', current_batch_id=NULL WHERE id IN ('M0001','M0002')")


def _kpi_sample(out):
    """解析准交率样本（on_time/sample）。"""
    for ln in out.splitlines():
        if "单按期" in ln:
            m = re.search(r"(\d+)/(\d+)", ln)
            assert m, f"未找到准交率样本: {out}"
            return int(m.group(1)), int(m.group(2))
    assert False, f"未找到准交率样本: {out}"


def test_kpi_tick_linkage(kpi_tick_env):
    """T5a.12：KPI 随 tick 联动——新订单入排产后 准交率分母 +1；
    有 scrap 时良率下降（空态 -> 数值 <100%）；前后 KPI 数值确有变化。"""
    from datetime import datetime

    from demo.simulator import engine

    out1 = scheduler_tools.query_kpi()
    _, sample1 = _kpi_sample(out1)
    assert "暂无完工批次" in out1, "KPI#1 无已完成批次 -> 良率空态"
    assert _scrap_count_in_kpi(out1) == 0, "KPI#1 应无坏件"

    # 新排产版本 V2（MAX+1）取代 V1：删旧批次 T-B0001 后重建，并纳入 T-ORD002
    _exec("DELETE FROM batches WHERE id='T-B0001'")
    v2 = _max_version_id()
    _insert_kpi_version_row(v2)
    _insert_kpi_batch("T-B0001", v2, "T-ORD001", "M0001")
    _insert_kpi_batch("T-B0002", v2, "T-ORD002", "M0002")
    # tick 快进：两批 打印中 -> 静置中 -> 完成（scrap_rate=1 全坏）
    with get_connection() as conn:
        engine.advance_tick(conn, datetime(2026, 9, 1, 11, 30), {"scrap_rate": 1.0})
        conn.commit()

    out2 = scheduler_tools.query_kpi()
    _, sample2 = _kpi_sample(out2)
    assert sample2 == sample1 + 1, f"准交率分母应随 T-ORD002 入排产 +1: {sample1} -> {sample2}"
    assert _scrap_count_in_kpi(out2) == 8, "两批全坏(3+5)应落 bad_parts"
    yr = next((ln for ln in out2.splitlines() if "良率" in ln), "")
    m = re.search(r"([\d.]+)%", yr)
    assert m, f"KPI#2 应输出数值良率: {out2}"
    assert float(m.group(1)) < 100.0, "坏件存在 -> 良率应 < 100%"
    assert out1 != out2, "前后两次 query_kpi 数值应有变化"
