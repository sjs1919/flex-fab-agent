"""scheduler_tools.py 排产工具集（M4a T4a.1）-- 11 工具中 4 个实装。

实装（复用 M2 求解器 + M3 模拟器事件表）：
  run_scheduling      求解 + 落库（triggered_by=agent），返回版本号与指标
  query_schedule      查最新（或指定）排产版本 + 批次表
  query_sim_events    查模拟器事件（类型/状态过滤）
  approve_schedule    排版人审批：待审核 -> 已审核/已驳回（单事务含 approvals）

实装（M4b）：query_load_assessment / query_ctp / query_order_tracking /
query_preprocess_load / query_kpi。
占位（M5 实装，注册保证工具数 18）：query_forecast / query_yield。

审计在 registry 治理层统一落（写工具执行入审计），handler 保持纯业务。
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

from demo.config import get_config
from demo.forecast import forecaster
from demo.scheduler import assessment
from demo.scheduler.snapshot import load_snapshot
from demo.scheduler.solver import persist, solve
from demo.tools.data import (format_table, get_connection, load_customers,
                             load_machines, load_orders, load_parts,
                             transaction)

_PLACEHOLDER_M4B = ()
_PLACEHOLDER_M5 = ()


def run_scheduling(triggered_by: str = "agent") -> str:
    """触发一轮排产求解并落库（写工具，需 reviewer 审批后生效）。"""
    snapshot = load_snapshot()
    result = solve(snapshot, triggered_by=triggered_by)
    version_id = persist(result, snapshot, triggered_by=triggered_by)
    m = result["metrics"]
    lines = [
        f"✅ 排产完成：版本 {version_id}（待审核）",
        f"求解状态 {m['status']} | 批次 {m['total_batches']} | 零件 {m['total_parts']} 件",
        f"目标值 {m['objective']} | 准交率 {m['on_time_rate']}"
        f"（{m['on_time']}/{m['total_orders']}）| 延期 {len(m['delay_list'])} 单",
        f"timed_out={m['timed_out']} | 求解耗时 {m['solver_duration_ms']:.0f}ms",
    ]
    if result["warnings"]:
        lines.append(f"⚠️ 预警 {len(result['warnings'])} 条（超尺寸/超承重，详见 query_schedule）")
    if result["conflicts"]:
        for c in result["conflicts"]:
            lines.append(f"❌ 冲突：{c['reason']}")
    return "\n".join(lines)


def query_schedule(version_id: int = 0) -> str:
    """查排产表。version_id=0 返回最新版本，否则返回指定版本。"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            if version_id:
                cur.execute("SELECT id, created_at, triggered_by, status "
                            "FROM schedule_versions WHERE id=%s", (version_id,))
            else:
                cur.execute("SELECT id, created_at, triggered_by, status "
                            "FROM schedule_versions ORDER BY id DESC LIMIT 1")
            vrow = cur.fetchone()
            if not vrow:
                return "（暂无排产版本，可先调 run_scheduling）"
            vid = vrow[0]
            cur.execute(
                "SELECT id, order_ids, process, model_type, machine_id, start_time, "
                "end_time, post_process_end, status, approval_status "
                "FROM batches WHERE schedule_version_id=%s ORDER BY start_time, id",
                (vid,))
            cols = [d[0] for d in cur.description]
            batches = [dict(zip(cols, r)) for r in cur.fetchall()]
    header = (f"排产版本 {vrow[0]} | 创建 {vrow[1]} | 触发 {vrow[2]} | "
              f"审批状态 {vrow[3]} | 批次 {len(batches)}")
    return header + "\n" + format_table(batches)


def query_sim_events(event_type: str = "", status: str = "", limit: int = 50) -> str:
    """查模拟器事件表。event_type/status 可选过滤（空=全部）。"""
    conds, params = [], []
    if event_type:
        conds.append("event_type=%s")
        params.append(event_type)
    if status:
        conds.append("status=%s")
        params.append(status)
    where = f"WHERE {' AND '.join(conds)}" if conds else ""
    params.append(max(1, min(limit, 200)))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT sim_time, event_type, status, payload_json FROM sim_events "
                f"{where} ORDER BY sim_time DESC, id DESC LIMIT %s", tuple(params))
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    if not rows:
        return "（无匹配事件）"
    return format_table(rows)


def approve_schedule(version_id: int, action: str, note: str = "",
                     approver: str = "") -> str:
    """排版人审批排产版本：action=通过|驳回（写工具，reviewer 专属）。

    单事务：schedule_versions.status + batches.approval_status + approvals 行。
    """
    if action not in ("通过", "驳回"):
        return f"❌ 非法审批动作：{action}（仅支持 通过/驳回）"
    version_status = "已审核" if action == "通过" else "已驳回"
    try:
        with transaction() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT status FROM schedule_versions WHERE id=%s",
                            (version_id,))
                row = cur.fetchone()
                if not row:
                    return f"❌ 排产版本不存在：{version_id}"
                if row[0] != "待审核":
                    return f"❌ 版本 {version_id} 状态为 {row[0]}，仅待审核版本可审批"
                cur.execute("UPDATE schedule_versions SET status=%s WHERE id=%s",
                            (version_status, version_id))
                cur.execute("UPDATE batches SET approval_status=%s "
                            "WHERE schedule_version_id=%s", (action, version_id))
                cur.execute(
                    "INSERT INTO approvals (schedule_version_id, approver, action, "
                    "time, note) VALUES (%s, %s, %s, %s, %s)",
                    (version_id, approver or "reviewer", action, datetime.now(),
                     note or None))
    except Exception as e:  # noqa: BLE001 - 审批失败需给调用方明确反馈
        return f"❌ 审批失败（已回滚）：{type(e).__name__}: {e}"
    return f"✅ 版本 {version_id} 审批{action}（{version_status}），批次同步更新"


def _fmt(value) -> str:
    """datetime/date → 展示字符串（MySQL DATE 返回 date 对象，datetime 带微秒）。"""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def query_load_assessment() -> str:
    """产能负载评估（M4b 实装）：四段报告——订单分布 → 各订单预计完成 →
    满负荷超期预警 → T 窗口消化 + 三区制 + 前道人池。只读，无参数。"""
    a = assessment.load_assessment()
    lines = [f"📊 产能负载评估（生成 {_fmt(a['generated_at'])}，T 窗口 {a['t_window_h']:.0f}h）"]

    dist = a["distribution"]
    lines.append(f"1️⃣ 订单分布：在途 {len(dist['在途'])} | 排队 {len(dist['排队'])} | 完成 {len(dist['完成'])}")

    eta_rows = [{
        "订单": e["order_id"], "工艺": e["process"], "交期": _fmt(e["due_date"]),
        "预计完成": _fmt(e["eta"]),
        "状态": "✅ 按期" if e["on_time"] else f"⚠️ 延期 {e['delay_days']} 天",
    } for e in a["orders_eta"]]
    lines.append("2️⃣ 各订单预计完成（满负荷粗算，交期升序→优先级降序）：")
    lines.append(format_table(eta_rows) if eta_rows else "（无排队订单）")

    lines.append("3️⃣ 满负荷超期预警：")
    if a["overdue_alerts"]:
        alert_rows = [{
            "订单": x["order_id"], "工艺": x["process"], "交期": _fmt(x["due_date"]),
            "预计完成": _fmt(x["eta"]), "延期": f"{x['delay_days']} 天",
        } for x in a["overdue_alerts"]]
        lines.append(format_table(alert_rows))
    else:
        lines.append("（无，当前负荷可在 T 窗口内消化）")

    tw_rows = [{
        "工艺": proc, "三区制": a["zone"].get(proc, "—"),
        "T窗口可用(h)": t["available_h"], "排队需求(h)": t["demand_h"],
        "缺口(h)": t["gap_h"], "缺机器数": t["missing_machines"],
    } for proc, t in sorted(a["t_window"].items())]
    lines.append("4️⃣ T 窗口消化 + 三区制（绿=≤90%可用 黄=≤100% 红=>100%）：")
    lines.append(format_table(tw_rows) if tw_rows else "（无工艺数据）")

    pp = a["preprocess"]
    cap = (f"{pp['workers']} 人 {pp['shifts']}班×{pp['shift_hours']}h"
           f"（换班 {pp['changeover_min']}min）→ 净产能 {pp['net_capacity_h_per_day']:.1f} 人·时/天")
    load = (f"待处理 {pp['pending_tasks']} 任务 / {pp['remaining_man_hours']:.1f} 人·时"
            f"（占用率 {pp['utilization'] * 100:.0f}%）")
    clear = f"预计清空 {_fmt(pp['eta_clear'])}" if pp["eta_clear"] else "暂无排队任务"
    bottle = "⚠️ 已成前道瓶颈" if pp["bottleneck"] else "未成瓶颈"
    lines.append(f"5️⃣ 前道人池：{cap} | {load} | {clear} | {bottle}")
    return "\n".join(lines)


def query_ctp(material: str = "", quantity: int = 0, height_mm: float = 0,
              due_date: str = "", amount: float = 0) -> str:
    """查询最短可交付时间 CTP（M4b 实装，M5a 增强预测校准）。material 工艺、
    quantity 件数、height_mm 零件高(mm)、due_date 可选交期——给出"能否按期"；
    amount 可选订单金额（≥5 万大单标注，建议按含预测预留的承诺期报客户）。只读。"""
    if not material or not quantity or not height_mm:
        return "❌ 参数不完整：需 material（SLA/MJS/SLM）+ quantity（件数）+ height_mm（零件高 mm）"
    try:
        r = assessment.compute_ctp_from_db(material, quantity, height_mm, due_date)
    except ValueError as e:
        return f"❌ {e}"
    lines = [
        f"📅 CTP（最短可交付）：{_fmt(r['ctp'])}",
        f"承诺期（含预测预留）：{_fmt(r['calibrated_ctp'])}"
        f"（预测预留 {r.get('forecast_reserved_days', 0):.0f} 天，"
        "预测机时按 90% 日产能折算，不扰动已下单订单）",
        f"瓶颈：{r['bottleneck']} | 新单机时 {r['machine_hours']:.2f}h"
        f"（该工艺现有占用完成 {_fmt(r['machine_ctp'])} / 前道人池完成 {_fmt(r['preprocess_ctp'])}）",
    ]
    try:
        threshold = float(get_config("预测", "large_order_amount", "50000"))
    except ValueError:
        threshold = 50000.0
    try:
        amount_v = float(amount)
    except (TypeError, ValueError):
        amount_v = 0.0
    if amount_v >= threshold:
        lines.append(f"💰 大单标注：金额 ¥{amount_v:,.0f} ≥ {threshold:,.0f}，"
                     "建议向客户按承诺期（含预测预留）报交期")
    if due_date:
        if r.get("meet_due"):
            lines.append(f"✅ 可满足交期 {due_date}")
        else:
            lines.append(f"⚠️ 无法满足交期 {due_date}，最早可交付 {_fmt(r['ctp'])}")
    return "\n".join(lines)


def _json_list(raw) -> list:
    """order_ids 字段（JSON 字符串/列表）→ list。"""
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return []


def query_order_tracking(order_id: str = "") -> str:
    """订单状态跟踪（M4b 实装）：当前环节、预计开打/完成、前面单据清单。只读。"""
    if not order_id:
        return "❌ 参数不完整：需 order_id（订单编号，如 ORD001）"
    orders = {o["id"]: o for o in load_orders()}
    order = orders.get(order_id)
    if not order:
        return f"❌ 订单不存在：{order_id}"
    parts = [p for p in load_parts() if p.get("order_id") == order_id]
    process = parts[0].get("material") if parts else "SLA"

    mine = [b for b in assessment._latest_batches()
            if order_id in _json_list(b.get("order_ids"))]

    lines = [f"🔍 订单 {order_id} 跟踪（工艺 {process}）",
             f"状态 {order['status']} | 交期 {_fmt(order['due_date'])} | "
             f"优先级 {order['priority']} | 金额 {_fmt(order['amount'])}"]

    if mine:
        lines.append("📦 关联批次：")
        for b in mine:
            done = _fmt(b.get("post_process_end") or b.get("end_time"))
            tag = "预计完成" if b.get("status") != "完成" else "完成"
            lines.append(f"批次 {b['id']} | {b['status']}/{b['approval_status']} | "
                         f"设备 {b['machine_id']} | 开工 {_fmt(b['start_time'])} | {tag} {done}")
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, part_count, man_hours, assigned_workers, start_time, end_time "
                    "FROM preprocess_tasks WHERE batch_id=%s", (mine[0]["id"],))
                cols = [d[0] for d in cur.description]
                ptasks = [dict(zip(cols, r)) for r in cur.fetchall()]
        if ptasks:
            lines.append("🧑‍🔧 前道任务：")
            lines.append(format_table(ptasks))
    else:
        lines.append("📦 未排入批次（排队等待排产）")

    ahead = _ahead_orders(order, process, orders)
    if ahead:
        rows = [{"订单": o["id"], "交期": _fmt(o["due_date"]),
                 "优先级": o["priority"], "状态": o["status"]} for o in ahead]
        lines.append(f"⏳ 前面单据（{len(ahead)} 单，交期升序→优先级降序）：")
        lines.append(format_table(rows))
    else:
        lines.append("⏳ 前面无同工艺单据（队首）")
    return "\n".join(lines)


def _ahead_orders(order: dict, process: str, orders: dict) -> list[dict]:
    """同工艺待处理订单按 交期升序→优先级降序 排队，取排在本单之前的（§8 目标函数顺序）。"""
    parts_by_order: dict[str, list[dict]] = {}
    for p in load_parts():
        parts_by_order.setdefault(p.get("order_id"), []).append(p)
    queue = []
    for oid, o in orders.items():
        if oid == order.get("id"):
            continue
        if o.get("status") not in ("待排队", "已审核", "打印中"):
            continue
        op = parts_by_order.get(oid, [])
        if (op[0].get("material") if op else "SLA") == process:
            queue.append(o)
    queue.sort(key=lambda o: (assessment._to_due_datetime(o.get("due_date")) or datetime.max,
                              -int(o.get("priority") or 0)))
    pos = next((i for i, o in enumerate(queue) if o["id"] == order.get("id")), -1)
    return queue[:pos] if pos > 0 else []


def query_preprocess_load() -> str:
    """前道人池负载（M4b 实装）：任务排队/在途、池占用率、预计清空、是否成瓶颈。只读。"""
    pp = assessment.preprocess_load()
    lines = [
        f"🧑‍🔧 前道人池负载（{pp['workers']} 人 {pp['shifts']}班×{pp['shift_hours']}h，"
        f"换班 {pp['changeover_min']}min）",
        f"净产能：{pp['net_capacity_h_per_day']:.1f} 人·时/天",
        f"待处理任务：{pp['pending_tasks']} 个 / {pp['remaining_man_hours']:.1f} 人·时",
        f"池占用率：{pp['utilization'] * 100:.0f}%",
    ]
    if pp["eta_clear"]:
        lines.append(f"预计清空：{_fmt(pp['eta_clear'])}")
    else:
        lines.append("预计清空：暂无排队任务")
    lines.append("状态：⚠️ 已成前道瓶颈" if pp["bottleneck"] else "状态：未成瓶颈")
    return "\n".join(lines)


def _kpi_on_time(completion: dict, orders: dict) -> tuple[int, int]:
    """准交率分子/分母：按期完成数 / 有完成时间的订单样本数。"""
    on_time = 0
    for oid, t in completion.items():
        due = assessment._to_due_datetime(orders.get(oid, {}).get("due_date"))
        if due and t <= due:
            on_time += 1
    return on_time, len(completion)


def _kpi_delay_total(completion: dict, orders: dict, customers: dict) -> Decimal:
    """延期违约金 = Σ 金额 × 客户违约金日费率 × 延期天数（Decimal 保精度，禁 float 裸算）。"""
    total = Decimal("0.00")
    for oid, t in completion.items():
        o = orders.get(oid, {})
        due = assessment._to_due_datetime(o.get("due_date"))
        if not due or t <= due:
            continue
        days = (t - due).days
        penalty = Decimal(str(customers.get(o.get("customer_id"), {}).get("penalty_rate") or 0))
        total += Decimal(str(o.get("amount") or 0)) * penalty * days
    return total


def _kpi_cabin_utilization(batches: list, parts_by_order: dict, machines: dict) -> float:
    """舱利用率 = Σ 批次投影面积 / Σ 舱底面积（舱底 = 设备 cabin_size²，粗算口径）。"""
    proj = Decimal("0.00")
    floor = Decimal("0.00")
    for b in batches:
        cs = machines.get(b.get("machine_id"), {}).get("cabin_size")
        if not cs:
            continue
        batch_proj = Decimal("0.00")
        for oid in _json_list(b.get("order_ids")):
            for p in parts_by_order.get(oid, []):
                batch_proj += (Decimal(str(p.get("length") or 0))
                               * Decimal(str(p.get("width") or 0))
                               * Decimal(str(p.get("quantity") or 1)))
        proj += batch_proj
        floor += Decimal(str(cs)) * Decimal(str(cs))
    if not floor:
        return 0.0
    return float(proj / floor)


def _kpi_done_parts(batches: list, parts_by_order: dict) -> int:
    """完成批次件数（良率分母）。"""
    return sum(
        int(p.get("quantity") or 0)
        for b in batches if b.get("status") == "完成"
        for oid in _json_list(b.get("order_ids"))
        for p in parts_by_order.get(oid, []))


def _kpi_yield_rate(scrap: int, done_parts: int) -> float | None:
    """良率 = 1 − 坏件/完工件数；无完工返回 None（不除零）。"""
    if not done_parts:
        return None
    return round(max(0.0, 1 - scrap / done_parts), 4)


def kpi_metrics() -> dict:
    """排产 KPI 结构化指标（M5b 抽取）：与 query_kpi 同源计算，看板快照/只读端点共用
    （验收条 74 口径一致：本函数是唯一计算源，query_kpi 仅做格式化）。
    delay_total 计算走 Decimal 保精度，出口转 float 仅供序列化展示。"""
    now = assessment._now()
    orders = {o["id"]: o for o in load_orders()}
    customers = {c["id"]: c for c in load_customers()}
    batches = assessment._latest_batches()
    parts_by_order: dict[str, list[dict]] = {}
    for p in load_parts():
        parts_by_order.setdefault(p.get("order_id"), []).append(p)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT entity_id, MAX(sim_time) FROM state_change_log "
                "WHERE entity_type='order' AND new_value='完成' GROUP BY entity_id")
            done_log = dict(cur.fetchall())
            # 坏件数：bad_parts 为准（M5a，与 query_yield 同源）；空表回落 sim_events 口径（兼容旧库）
            cur.execute("SELECT COALESCE(SUM(part_count), 0) FROM bad_parts")
            scrap = cur.fetchone()[0]
            if not scrap:
                cur.execute("SELECT COUNT(*) FROM sim_events WHERE event_type='scrap'")
                scrap = cur.fetchone()[0]
    # 完成时间：state_change_log（订单→完成）优先，批次 post_process_end 兜底
    batch_end: dict[str, datetime] = {}
    for b in batches:
        t = b.get("post_process_end") or b.get("end_time")
        if not t:
            continue
        for oid in _json_list(b.get("order_ids")):
            if oid not in batch_end or t > batch_end[oid]:
                batch_end[oid] = t
    completion = {oid: done_log.get(oid, batch_end.get(oid))
                  for oid in orders if oid in done_log or oid in batch_end}

    on_time, sample = _kpi_on_time(completion, orders)
    delay_total = _kpi_delay_total(completion, orders, customers)
    raw_machines = load_machines()
    machines = {m["id"]: m for m in raw_machines if "id" in m}
    # csv 模式（machines.csv 无 id/cabin_size 列）映射后为空 -> 舱利用率降级 None
    cabin = (_kpi_cabin_utilization(batches, parts_by_order, machines)
             if machines else None)
    done_parts = _kpi_done_parts(batches, parts_by_order)
    yield_rate = _kpi_yield_rate(scrap, done_parts)
    pp = assessment.preprocess_load()

    return {
        "generated_at": now,
        "on_time": on_time,
        "sample": sample,
        "on_time_rate": round(on_time / sample, 4) if sample else None,
        "delay_total": float(delay_total),
        "cabin_utilization": cabin,
        "batch_count": len(batches),
        "done_parts": done_parts,
        "scrap": int(scrap),
        "yield_rate": float(yield_rate) if yield_rate is not None else None,
        "preprocess": {
            "utilization": pp["utilization"],
            "remaining_man_hours": pp["remaining_man_hours"],
            "net_capacity_h_per_day": pp["net_capacity_h_per_day"],
            "bottleneck": pp["bottleneck"],
        },
    }


def query_kpi() -> str:
    """排产 KPI（M4b 实装）：准交率/延期金额/舱利用率/良率/前道瓶颈占用，DB 实时聚合。
    口径与 M5 KPI 看板共用（验收清单条 72）。M5b 起计算在 kpi_metrics()，本函数仅格式化。
    只读，无参数。"""
    m = kpi_metrics()
    ot_txt = (f"{m['on_time_rate'] * 100:.1f}%" if m["on_time_rate"] is not None
              else "暂无完工数据")
    yr = m["yield_rate"]
    yr_txt = f"{yr * 100:.1f}%" if yr is not None else "暂无完工批次"
    pp = m["preprocess"]
    lines = [f"📈 排产 KPI（生成 {_fmt(m['generated_at'])}）"]
    lines.append(f"1️⃣ 准交率：{ot_txt}（{m['on_time']}/{m['sample']} 单按期）")
    lines.append(f"2️⃣ 延期金额：¥{m['delay_total']:.2f}（Σ金额×违约金日费率×延期天数）")
    cabin = m["cabin_utilization"]
    cabin_txt = (f"{cabin * 100:.1f}%（Σ批次投影面积/舱底面积，{m['batch_count']} 批次）"
                 if cabin is not None else "暂无设备数据（csv 模式）")
    lines.append(f"3️⃣ 舱利用率：{cabin_txt}")
    lines.append(f"4️⃣ 良率：{yr_txt}（1 − 坏件 {m['scrap']} / 完工 {m['done_parts']} 件）")
    lines.append(f"5️⃣ 前道瓶颈占用：{pp['utilization'] * 100:.0f}%"
                 f"（{pp['remaining_man_hours']:.1f}/{pp['net_capacity_h_per_day']:.1f} 人·时）"
                 + (" | ⚠️ 已瓶颈" if pp["bottleneck"] else " | 未瓶颈"))
    return "\n".join(lines)


def query_forecast(days: str = "") -> str:
    """订单量统计预测（M5a 实装）：逐日分材料预测件数/机时。days 可选覆盖窗口。只读。"""
    n_days: int | None
    try:
        n_days = int(days) if days else None
        if n_days is not None and n_days <= 0:
            n_days = None  # 非法输入回落配置窗口
    except ValueError:
        n_days = None
    out = forecaster.forecast(n_days=n_days)
    if not out["materials"]:
        return f"ℹ️ {out['note']}"
    method_txt = {"ma": "移动平均", "exponential": "指数平滑"}[out["method"]]
    lines = [f"📈 订单量预测（{method_txt}，α={out['alpha']}，窗口 {out['window']} 天，"
             f"口径：按下单日 order_date 聚合历史 -> 预测未来机时按 90% 日产能折算预留）"]
    for material, rows in out["materials"].items():
        lines.append(f"【{material}】")
        lines.append(format_table([{"日期": r["date"], "件数": r["parts"],
                                    "机时(h)": r["hours"]} for r in rows]))
    return "\n".join(lines)


# ---- M5a T5a.9：query_yield（良率下钻 + LLM 改善建议） ----

def _yield_bad_rows() -> list[dict]:
    """bad_parts 全部坏件行（根因维度：批次/设备/材料）。"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT batch_id, machine_id, material, part_count FROM bad_parts")
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def _done_parts_by_machine() -> dict[str, int]:
    """完成批次件数按设备（良率分母；口径同 _kpi_done_parts）。"""
    batches = assessment._latest_batches()
    by_order: dict[str, list[dict]] = {}
    for p in load_parts():
        by_order.setdefault(p.get("order_id"), []).append(p)
    result: dict[str, int] = {}
    for b in batches:
        if b.get("status") != "完成" or not b.get("machine_id"):
            continue
        total = sum(int(p.get("quantity") or 0)
                    for oid in _json_list(b.get("order_ids"))
                    for p in by_order.get(oid, []))
        result[b["machine_id"]] = result.get(b["machine_id"], 0) + total
    return result


def _machine_failure_counts() -> dict[str, int]:
    """各设备 MTBF 故障次数（sim_events machine_failure 的 payload.machine_id 聚合）。"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT payload_json FROM sim_events WHERE event_type='machine_failure'")
            payloads = [r[0] for r in cur.fetchall()]
    counts: dict[str, int] = {}
    for raw in payloads:
        if not raw:
            continue
        try:
            mid = json.loads(raw).get("machine_id")
        except (TypeError, ValueError):
            continue
        if mid:
            counts[mid] = counts.get(mid, 0) + 1
    return counts


def _yield_rule_based_advice(bad_rows: list[dict]) -> str:
    """LLM 失败降级规则模板：烂设备->检修；材料->针对性换料/参数核查。"""
    by_machine: dict[str, int] = {}
    by_material: dict[str, int] = {}
    for r in bad_rows:
        by_machine[r["machine_id"]] = by_machine.get(r["machine_id"], 0) + int(r["part_count"])
        by_material[r["material"]] = by_material.get(r["material"], 0) + int(r["part_count"])
    lines = []
    if by_machine:
        worst_m, worst_n = max(by_machine.items(), key=lambda kv: kv[1])
        lines.append(f"设备 {worst_m} 坏件最多（{worst_n} 件），建议安排检修/校准后试打验证。")
    material_hint = {
        "SLA": "检查树脂批次与曝光参数（层厚/曝光时间）",
        "MJS": "检查喷射头状态与材料粘度",
        "SLM": "检查粉末粒径/含氧量/铺粉均匀性",
    }
    for m, n in sorted(by_material.items(), key=lambda kv: -kv[1]):
        lines.append(f"材料 {m} 坏件 {n} 件：{material_hint.get(m, '核查工艺参数')}。")
    return "\n".join(lines) if lines else "暂无坏件，无需归因建议。"


def _yield_advice(bad_rows: list[dict], total_bad: int, total_done: int,
                  by_machine_rows: list[dict]) -> str:
    """LLM 生成工艺改善建议；失败/无 key 降级规则模板（不中断工具）。"""
    yr = _kpi_yield_rate(total_bad, total_done)
    summary_lines = [f"良率 {yr * 100:.2f}%（坏件 {total_bad} / 完工 {total_done} 件）",
                     "设备下钻（坏件降序）：" + "; ".join(
                         f"{r['设备']} {r['坏件']}件/故障{r['MTBF故障']}次" for r in by_machine_rows)]
    summary = "\n".join(summary_lines)
    try:
        from demo.core.llm_client import call_llm_simple
        system = ("你是 3D 打印车间的工艺质量工程师。基于坏件归因摘要，给出 2~4 条"
                  "可执行的改善建议（设备/材料/工艺维度），直接给结论，不客套。")
        resp = call_llm_simple(system, summary, task_type="complex", max_tokens=300)
        content = (resp.choices[0].message.content or "").strip()
        if content:
            return content
    except Exception:  # noqa: BLE001 - LLM 失败不阻塞只读工具
        pass
    return _yield_rule_based_advice(bad_rows)


def query_yield() -> str:
    """打印良率（M5a 实装）：总览 -> 设备下钻（含 MTBF 故障次数）-> 批次下钻
    -> 材料对比 -> LLM 工艺改善建议。只读，无参数。"""
    rows = _yield_bad_rows()
    done = _done_parts_by_machine()
    total_bad = sum(int(r["part_count"]) for r in rows)
    total_done = sum(done.values())
    failures = _machine_failure_counts()

    lines = [f"🛡️ 打印良率（生成 {_fmt(datetime.now())}）"]
    if not rows:
        lines.append("（暂无坏件记录，全部批次良率 100%，无需归因）")
        return "\n".join(lines)
    yr = _kpi_yield_rate(total_bad, total_done)
    lines.append(f"总览：良率 {yr * 100:.2f}% | 坏件 {total_bad} 件 / 完工 {total_done} 件")

    by_machine: dict[str, int] = {}
    by_batch: dict[str, int] = {}
    by_material: dict[str, int] = {}
    for r in rows:
        by_machine[r["machine_id"]] = by_machine.get(r["machine_id"], 0) + int(r["part_count"])
        by_batch[r["batch_id"]] = by_batch.get(r["batch_id"], 0) + int(r["part_count"])
        by_material[r["material"]] = by_material.get(r["material"], 0) + int(r["part_count"])

    machine_rows = [{
        "设备": mid, "坏件": n,
        "完工": done.get(mid, 0),
        "良率": f"{_kpi_yield_rate(n, done.get(mid, 0)) * 100:.2f}%" if done.get(mid, 0) else "—",
        "MTBF故障": failures.get(mid, 0),
    } for mid, n in sorted(by_machine.items(), key=lambda kv: -kv[1])]
    lines.append("1️⃣ 设备下钻（坏件降序）：")
    lines.append(format_table(machine_rows))

    batch_rows = [{"批次": bid, "坏件": n}
                  for bid, n in sorted(by_batch.items(), key=lambda kv: -kv[1])]
    lines.append("2️⃣ 批次下钻：")
    lines.append(format_table(batch_rows))

    material_rows = [{"材料": m, "坏件": n}
                     for m, n in sorted(by_material.items(), key=lambda kv: -kv[1])]
    lines.append("3️⃣ 材料对比：")
    lines.append(format_table(material_rows))

    lines.append("4️⃣ 改善建议（LLM 归因，失败降级规则模板）：")
    lines.append(_yield_advice(rows, total_bad, total_done, machine_rows))
    return "\n".join(lines)


def _placeholder(name: str, milestone: str):
    def _handler(**_kwargs) -> str:
        return f"ℹ️ {name} 将在 {milestone} 提供（当前为占位注册，保证工具清单完整）"
    return _handler


PLACEHOLDER_TOOLS = {
    **{n: _placeholder(n, "M4b") for n in _PLACEHOLDER_M4B},
    **{n: _placeholder(n, "M5") for n in _PLACEHOLDER_M5},
}
