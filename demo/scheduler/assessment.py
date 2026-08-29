"""产能/CTP/前道计算核心（M4b T4b.2）-- 5 个排产工具复用。

口径来源：需求规格 §8 计算口径 + §4.3 P1-4 + §6 C9。
只读聚合不写库；参数统一走 system_config（get_config，缺省回落常量）。

纯函数（zone_color / t_window_availability / compute_ctp 等）独立可测；
拼装层（load_assessment / preprocess_load / compute_ctp_from_db）连库读取后复用纯函数。
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta

from demo.config import get_config
from demo.tools.data import get_connection, load_orders, load_parts

# ── system_config 缺省常量（T4b.1 种子；缺行回落此值）──
DEFAULT_T_WINDOW_H = 24
DEFAULT_WORKERS = 6
DEFAULT_SHIFTS = 3
DEFAULT_SHIFT_HOURS = 8
DEFAULT_CHANGEOVER_MIN = 30
DEFAULT_PART_EFF = {"SLA": 15, "MJS": 15, "SLM": 6}
DEFAULT_PLAN_REVIEW_HOURS = 0.5
# 日可用产能 = 24h×90%（预留 10% 应急池，§8 C8）
DAILY_UTILIZATION = 0.9


def _cfg(category: str, key: str, default: str) -> str:
    try:
        return get_config(category, key, default)
    except Exception:
        return default


def _f(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_due_datetime(value) -> datetime | None:
    """交期统一为截止日 23:59（§4.3 P1-3）：date/datetime/str → datetime。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).replace(hour=23, minute=59)
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").replace(hour=23, minute=59)
    except ValueError:
        return None


# ────────────────────────────── 纯函数 ──────────────────────────────


def zone_color(demand_h: float, total_capacity_h: float) -> str:
    """三区制判定（§8）：满负荷 100% 判断——需求 ≤90% 可用→绿；≤100%→黄；>100%→红。"""
    if total_capacity_h <= 0:
        return "红"
    ratio = demand_h / total_capacity_h
    if ratio <= 0.9:
        return "绿"
    if ratio <= 1.0:
        return "黄"
    return "红"


def t_window_availability(machines: list[dict], batches: list[dict],
                          now: datetime, t_window_h: float) -> dict[str, float]:
    """T 窗口可用产能（§8）：Σ(已腾出×T) + Σ(当天腾出×(T−预计腾出时间))，按工艺分群。

    已腾出 = status='空闲'；当天腾出 = status='打印中' 且批次 end_time 落在 T 窗口内；
    正在打印且 end_time > now+T → 排除；维修/故障等不计。
    """
    batch_end = {b.get("id"): b.get("end_time") for b in batches}
    avail: dict[str, float] = {}
    for m in machines:
        p = m.get("process")
        if not p:  # csv 模式 machines.csv 无 process 列，跳过（无工艺无法分组）
            continue
        status = m.get("status")
        if status == "空闲":
            avail[p] = avail.get(p, 0.0) + t_window_h
        elif status == "打印中":
            end = batch_end.get(m.get("current_batch_id"))
            if end is None:
                continue
            hours_left = (end - now).total_seconds() / 3600.0
            if 0 < hours_left < t_window_h:  # T 窗口内能腾出
                avail[p] = avail.get(p, 0.0) + (t_window_h - hours_left)
            # hours_left >= t_window_h → 该机器排除
    return avail


def missing_machines(gap_h: float, t_window_h: float) -> int:
    """缺机器数 = ⌈缺口 ÷ 单台 T 窗口产能⌉（§8，按工艺分群）。"""
    if gap_h <= 0:
        return 0
    return math.ceil(gap_h / t_window_h)


def part_machine_hours(material: str, height_mm: float, rate_mm_h: float) -> float:
    """单件时长 = Z高 ÷ 工艺速率（§8）。"""
    return height_mm / rate_mm_h


def preprocess_net_capacity_h(shifts: int, shift_hours: int,
                              changeover_min: int, workers: int) -> float:
    """前道人工净产能（§8）：(班次×班时长 − 班次×换班分钟/60) × 每班人数。

    每班人数 = workers/shifts（6 人 3 班 → 每班 2 人）：3×8−1.5=22.5h × 2 = 45人·时/天。
    """
    per_shift = workers / shifts if shifts > 0 else workers
    return (shifts * shift_hours - shifts * changeover_min / 60.0) * per_shift


def preprocess_task_hours(part_count: int, assigned_workers: int,
                          per_part_eff: float, plan_review_hours: float,
                          n_batches: int | None = None) -> float:
    """前道任务时长（§8 C9）= 件数÷(人×件人效) + 方案审核分摊。

    方案审核分摊按版本平摊（定稿 §3.A）：n_batches 给定时每批
    share = round(plan_review_hours / n_batches, 4)；n_batches=None（存量调用）
    维持平加全量，兼容既有调用方。
    """
    review = (round(plan_review_hours / n_batches, 4)
              if n_batches else plan_review_hours)
    if assigned_workers <= 0 or per_part_eff <= 0:
        return review
    return part_count / (assigned_workers * per_part_eff) + review


def clear_eta_hours(remaining_man_hours: float, net_capacity_h_per_day: float) -> float:
    """前道池清空所需日历小时 = 人·时 ÷ (人·时/天) × 24h/天。

    直接用「总人·时」当小时数会低估产能（45 人·时/天 → 100 人·时只需 53.3h 而非 100h），
    把清空时刻推后约 2 倍。净产能未知时回落原值。
    """
    if net_capacity_h_per_day <= 0:
        return remaining_man_hours
    return remaining_man_hours * 24.0 / net_capacity_h_per_day


def compute_ctp(material: str, quantity: int, height_mm: float, rate_mm_h: float,
                preprocess_eff: float, plan_review_hours: float,
                machine_load_end: datetime, preprocess_queue_end: datetime,
                assigned_workers: int) -> dict:
    """CTP（§8）：新单排在现有占用之后，取 max(设备序列完成, 前道人池完成)。

    设备侧：该工艺现有占用完成时刻 + 新单机时（quantity × 单件时长，串行追加=保守）。
    前道侧：前道池排队完成时刻 + 新单前道时长。双瓶颈取大，防偏乐观。
    """
    per_part = part_machine_hours(material, height_mm, rate_mm_h)
    machine_hours = quantity * per_part
    machine_ctp = machine_load_end + timedelta(hours=machine_hours)

    prep_hours = preprocess_task_hours(quantity, assigned_workers,
                                       preprocess_eff, plan_review_hours)
    preprocess_ctp = preprocess_queue_end + timedelta(hours=prep_hours)

    if machine_ctp >= preprocess_ctp:
        return {"machine_ctp": machine_ctp, "preprocess_ctp": preprocess_ctp,
                "ctp": machine_ctp, "bottleneck": "设备",
                "machine_hours": machine_hours, "preprocess_hours": prep_hours}
    return {"machine_ctp": machine_ctp, "preprocess_ctp": preprocess_ctp,
            "ctp": preprocess_ctp, "bottleneck": "前道",
            "machine_hours": machine_hours, "preprocess_hours": prep_hours}


# ────────────────────────────── 拼装层（连库） ──────────────────────────────


def _now() -> datetime:
    """当前 sim 时间（sim_clock）；未初始化回落 datetime.now()。"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_sim_time FROM sim_clock WHERE id=1")
                row = cur.fetchone()
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    return datetime.now()


def _rates() -> dict[str, float]:
    """工艺速率表：{process: rate_mm_h}（material 表）。"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT process, rate_mm_h FROM material")
            return {r[0]: float(r[1]) for r in cur.fetchall()}


def _latest_batches() -> list[dict]:
    """全部活动版本（含未完成批次且版本非「已驳回」）的批次行（定稿 §5/§3.B/§3.E 聚合口径）。

    弃 MAX(id)：多活动版本并存时 MAX(id) 只取最新版本，旧版本在途批次被漏报——
    _kpi_done_parts/完成跟踪/舱利用率/前道联表全基于此批次集，漏报会致已完成
    批次订单被重复计入 KPI。驳回版本批次被 E 门禁永久卡在前道，不入聚合；
    全完成版本订单已收口，不再跟踪。返回含已完成批次（_kpi_done_parts 口径需要）。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT b.id, b.order_ids, b.process, b.machine_id, b.start_time, b.end_time, "
                "b.post_process_end, b.status, b.approval_status "
                "FROM batches b JOIN schedule_versions s ON s.id = b.schedule_version_id "
                "WHERE s.status != '已驳回' "
                "AND EXISTS (SELECT 1 FROM batches b2 WHERE b2.schedule_version_id = s.id "
                "            AND b2.status != '完成') "
                "ORDER BY s.id, b.start_time, b.id")
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def _completed_batches() -> list[dict]:
    """所有非「已驳回」版本的已完成批次（KPI 良率/完工件数口径，全完成版本也计入）。

    良率 = 1 − 坏件/完工件数是历史质量口径，不能随「全完成版本退出读路径」
    （_latest_batches 活动版本跟踪口径）而清零——这里独立查询完成批次，与
    _latest_batches 解耦。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT b.id, b.order_ids, b.machine_id, b.status "
                "FROM batches b JOIN schedule_versions s ON s.id = b.schedule_version_id "
                "WHERE s.status != '已驳回' AND b.status = '完成'")
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def _preprocess_params() -> dict:
    """前道参数（system_config，缺省回落常量）。"""
    return {
        "workers": _i(_cfg("前道", "workers", "6"), DEFAULT_WORKERS),
        "shifts": _i(_cfg("前道", "shifts", "3"), DEFAULT_SHIFTS),
        "shift_hours": _i(_cfg("前道", "shift_hours", "8"), DEFAULT_SHIFT_HOURS),
        "changeover_min": _i(_cfg("前道", "changeover_min", "30"), DEFAULT_CHANGEOVER_MIN),
        "plan_review_hours": _f(_cfg("前道", "plan_review_hours", "0.5"), DEFAULT_PLAN_REVIEW_HOURS),
    }


def _per_part_eff(process: str) -> float:
    """件人效（§8）：SLA/MJS 15、SLM 6；综合 12 用于混合。"""
    key = {"SLA": "per_part_eff_sla_mjs", "MJS": "per_part_eff_sla_mjs",
           "SLM": "per_part_eff_slm"}.get(process, "per_part_eff_mix")
    default = DEFAULT_PART_EFF.get(process, 12)
    return _f(_cfg("前道", key, str(default)), default)


def preprocess_load() -> dict:
    """前道人池负载（§3.15 + 定稿 §3.B/§3.E）：任务排队/在途、池占用率、预计清空、是否成瓶颈。

    观测口径改读落库 SUM(man_hours)（含方案审核分摊），联 batches 过滤
    「status='前道' 且 approval_status='通过'」（未完成 + 已通过）——前道→待上机即释放，
    驳回/待审核版本任务不入池（待审窗口假空闲，乐观偏差 ≤ FIFO_AGE_TIMEOUT）。
    """
    pp = _preprocess_params()
    workers = pp["workers"]
    net_capacity_h = preprocess_net_capacity_h(pp["shifts"], pp["shift_hours"],
                                               pp["changeover_min"], workers)
    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(SUM(pt.man_hours), 0), COUNT(*) "
                "FROM preprocess_tasks pt JOIN batches b ON b.id = pt.batch_id "
                "WHERE b.status='前道' AND b.approval_status='通过'")
            row = cur.fetchone()
    total_remaining_h = float(row[0]) if row else 0.0
    pending_tasks = int(row[1]) if row else 0
    utilization = total_remaining_h / net_capacity_h if net_capacity_h > 0 else 1.0
    return {
        "workers": workers,
        "shifts": pp["shifts"],
        "shift_hours": pp["shift_hours"],
        "changeover_min": pp["changeover_min"],
        "net_capacity_h_per_day": net_capacity_h,
        "pending_tasks": pending_tasks,
        "remaining_man_hours": round(total_remaining_h, 2),
        "utilization": round(min(utilization, 9.99), 2),
        "bottleneck": utilization > 1.0,
        "eta_clear": (now + timedelta(hours=clear_eta_hours(total_remaining_h,
                                                            net_capacity_h))
                      if total_remaining_h else None),
    }


def _demand_machine_hours() -> dict[str, float]:
    """排队需求产能（§8）= Σ 未完成订单所需机时，按工艺分群（批次模型粗算）。"""
    orders = {o["id"]: o for o in load_orders()}
    rates = _rates()
    demand: dict[str, float] = {}
    for p in load_parts():
        o = orders.get(p.get("order_id"))
        if o is None or o.get("status") == "完成":
            continue
        process = p.get("material")
        rate = rates.get(process, 50.0)
        hours = part_machine_hours(process, _f(p.get("height"), 100), rate) \
            * _i(p.get("quantity"), 1)
        demand[process] = demand.get(process, 0.0) + hours
    return demand


def load_assessment() -> dict:
    """产能负载评估四段报告（§3.13 + §8）：分布→预计完成→预警→T 窗口→三区制→前道。

    各订单预计完成：按目标函数顺序（交期升序→priority 降序）满负荷粗算累计完成。
    """
    now = _now()
    t_window_h = _f(_cfg("产能", "t_window_h", "24"), DEFAULT_T_WINDOW_H)
    orders = {o["id"]: o for o in load_orders()}
    batches = _latest_batches()
    rates = _rates()

    # 1. 在途/排队分布（§4.3：待排队含未审核）
    dist = {"在途": [], "排队": [], "完成": []}
    for oid, o in orders.items():
        if o.get("status") in ("打印中",):
            dist["在途"].append(oid)
        elif o.get("status") in ("待排队", "已审核"):
            dist["排队"].append(oid)
        else:
            dist["完成"].append(oid)

    # 零件按订单分组（一次遍历，避免每订单全表扫描）
    parts_by_order: dict[str, list[dict]] = {}
    for part in load_parts():
        parts_by_order.setdefault(part.get("order_id"), []).append(part)

    # 2. 各订单预计完成（满负荷粗算：每工艺队列 + 机器并行数推进）
    from demo.tools.data import load_machines
    machine_count: dict[str, int] = {}
    for m in load_machines():
        p = m.get("process")
        if p:  # csv 模式 machines.csv 无 process 列 -> 缺工艺不分群，n 回落 1
            machine_count[p] = machine_count.get(p, 0) + 1
    pending = [o for o in orders.values() if o.get("status") in ("待排队", "已审核")]
    pending.sort(key=lambda o: (_to_due_datetime(o.get("due_date")) or datetime.max,
                                -int(o.get("priority") or 0)))
    cursor_time: dict[str, datetime] = {}
    orders_eta = []
    for o in pending:
        oid = o.get("id")
        oparts = parts_by_order.get(oid, [])
        proc = oparts[0].get("material") if oparts else "SLA"
        hours = 0.0
        for part in oparts:
            rate = rates.get(part.get("material"), 50.0)
            hours += part_machine_hours(part.get("material"),
                                        _f(part.get("height"), 100), rate) \
                * _i(part.get("quantity"), 1)
        n = max(machine_count.get(proc, 1), 1)
        base = cursor_time.get(proc, now)
        eta = base + timedelta(hours=hours / n)
        cursor_time[proc] = eta
        due = _to_due_datetime(o.get("due_date"))
        on_time = eta <= due if due else True
        orders_eta.append({
            "order_id": oid, "process": proc, "due_date": o.get("due_date"),
            "eta": eta, "on_time": on_time,
            "delay_days": max((eta - due).days, 0) if due and not on_time else 0,
        })

    # 3. 满负荷超期预警（排队 + 在途批次）
    alerts = [e for e in orders_eta if not e["on_time"]]
    for b in batches:
        if b.get("status") == "打印中" and b.get("end_time"):
            try:
                oids = json.loads(b.get("order_ids") or "[]")
            except (TypeError, ValueError):
                oids = []
            for oid in oids:
                o = orders.get(oid)
                if not o:
                    continue
                due = _to_due_datetime(o.get("due_date"))
                if due and b["end_time"] > due:
                    alerts.append({"order_id": oid, "process": b.get("process"),
                                   "due_date": o.get("due_date"), "eta": b.get("end_time"),
                                   "on_time": False,
                                   "delay_days": max((b["end_time"] - due).days, 0)})

    # 4. T 窗口消化 + 缺机器数（按工艺）
    avail = t_window_availability(load_machines(), batches, now, t_window_h)
    demand = _demand_machine_hours()
    t_window = {}
    for proc in set(list(avail.keys()) + list(demand.keys())):
        a, d = avail.get(proc, 0.0), demand.get(proc, 0.0)
        gap = d - a
        t_window[proc] = {
            "available_h": round(a, 2), "demand_h": round(d, 2),
            "surplus_h": round(-gap, 2) if gap < 0 else 0.0,
            "gap_h": round(gap, 2) if gap > 0 else 0.0,
            "missing_machines": missing_machines(gap, t_window_h),
            "digestible": gap <= 0,
        }

    # 5. 三区制（需求 vs 满负荷可用 = 机器数 × T）
    zone = {}
    for proc, d in demand.items():
        total_cap = machine_count.get(proc, 0) * t_window_h
        zone[proc] = zone_color(d, total_cap)

    return {
        "generated_at": now,
        "t_window_h": t_window_h,
        "distribution": dist,
        "orders_eta": orders_eta,
        "overdue_alerts": alerts,
        "t_window": t_window,
        "zone": zone,
        "preprocess": preprocess_load(),
    }


def _forecast_reserved_days(material: str) -> float:
    """预测校准（M5a）：预测窗口机时按 90% 日产能折算预留天数。

    口径（用户 2026-08-23 确认）：预测占用只在常规 CTP 之上追加预留，
    不扰动已下单订单的排产；大单（≥5 万）承诺期按含预留档报给客户。
    延迟 import forecast（forecast 不 import assessment，防循环依赖）。
    """
    from demo.forecast import forecaster

    out = forecaster.forecast()
    rows = out.get("materials", {}).get(material)
    if not rows:
        return 0.0
    forecast_hours = sum(r["hours"] for r in rows)
    if forecast_hours <= 0:
        return 0.0
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM machines WHERE process=%s", (material,))
            machine_count = cur.fetchone()[0]
    if not machine_count:
        return 0.0
    daily_effective_h = machine_count * 24 * 0.9  # 90% 日产能
    return math.ceil(forecast_hours / daily_effective_h)


def compute_ctp_from_db(material: str, quantity: int, height_mm: float,
                        due_date: str = "") -> dict:
    """query_ctp 拼装：读库取现有占用完成/前道池完成 → compute_ctp。"""
    rate = {"SLA": 50.0, "MJS": 25.0, "SLM": 15.0}.get(material)
    if rate is None:
        raise ValueError(f"未知工艺：{material}（仅支持 SLA/MJS/SLM）")
    if height_mm > 600:
        raise ValueError(f"零件高 {height_mm}mm > 600，超尺寸无法装舱")
    batches = _latest_batches()
    ends = [b["end_time"] for b in batches
            if b.get("process") == material and b.get("end_time")]
    machine_load_end = max(ends) if ends else _now()
    pp = _preprocess_params()
    prep = preprocess_load()
    preprocess_queue_end = prep.get("eta_clear") or _now()

    result = compute_ctp(
        material, int(quantity), height_mm, rate,
        _per_part_eff(material), pp["plan_review_hours"],
        machine_load_end, preprocess_queue_end, pp["workers"],
    )
    reserved = _forecast_reserved_days(material)
    result["forecast_reserved_days"] = reserved
    result["calibrated_ctp"] = result["ctp"] + timedelta(days=reserved)
    result["due_date"] = due_date
    if due_date:
        due = _to_due_datetime(due_date)
        result["meet_due"] = result["ctp"] <= due if due else None
    return result
