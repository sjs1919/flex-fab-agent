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

from demo.scheduler import assessment
from demo.scheduler.snapshot import load_snapshot
from demo.scheduler.solver import persist, solve
from demo.tools.data import (format_table, get_connection, load_customers,
                             load_machines, load_orders, load_parts,
                             transaction)

_PLACEHOLDER_M4B = ()
_PLACEHOLDER_M5 = ("query_forecast", "query_yield")


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
              due_date: str = "") -> str:
    """查询最短可交付时间 CTP（M4b 实装）。material 工艺、quantity 件数、
    height_mm 零件高(mm)、due_date 可选交期——给出"能否按期"。只读。"""
    if not material or not quantity or not height_mm:
        return "❌ 参数不完整：需 material（SLA/MJS/SLM）+ quantity（件数）+ height_mm（零件高 mm）"
    try:
        r = assessment.compute_ctp_from_db(material, quantity, height_mm, due_date)
    except ValueError as e:
        return f"❌ {e}"
    lines = [
        f"📅 CTP（最短可交付）：{_fmt(r['ctp'])}",
        f"瓶颈：{r['bottleneck']} | 新单机时 {r['machine_hours']:.2f}h"
        f"（该工艺现有占用完成 {_fmt(r['machine_ctp'])} / 前道人池完成 {_fmt(r['preprocess_ctp'])}）",
    ]
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


def query_kpi() -> str:
    """排产 KPI（M4b 实装）：准交率/延期金额/舱利用率/良率/前道瓶颈占用，DB 实时聚合。
    口径与 M5 KPI 看板共用（验收清单条 72）。只读，无参数。"""
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
    cabin = _kpi_cabin_utilization(batches, parts_by_order,
                                   {m["id"]: m for m in load_machines()})
    done_parts = _kpi_done_parts(batches, parts_by_order)
    yield_rate = _kpi_yield_rate(scrap, done_parts)
    pp = assessment.preprocess_load()

    lines = [f"📈 排产 KPI（生成 {_fmt(now)}）"]
    ot_txt = f"{on_time / sample * 100:.1f}%" if sample else "暂无完工数据"
    lines.append(f"1️⃣ 准交率：{ot_txt}（{on_time}/{sample} 单按期）")
    lines.append(f"2️⃣ 延期金额：¥{delay_total:.2f}（Σ金额×违约金日费率×延期天数）")
    lines.append(f"3️⃣ 舱利用率：{cabin * 100:.1f}%（Σ批次投影面积/舱底面积，{len(batches)} 批次）")
    yr_txt = f"{yield_rate * 100:.1f}%" if yield_rate is not None else "暂无完工批次"
    lines.append(f"4️⃣ 良率：{yr_txt}（1 − 坏件 {scrap} / 完工 {done_parts} 件）")
    lines.append(f"5️⃣ 前道瓶颈占用：{pp['utilization'] * 100:.0f}%"
                 f"（{pp['remaining_man_hours']:.1f}/{pp['net_capacity_h_per_day']:.1f} 人·时）"
                 + (" | ⚠️ 已瓶颈" if pp["bottleneck"] else " | 未瓶颈"))
    return "\n".join(lines)


def _placeholder(name: str, milestone: str):
    def _handler(**_kwargs) -> str:
        return f"ℹ️ {name} 将在 {milestone} 提供（当前为占位注册，保证工具清单完整）"
    return _handler


PLACEHOLDER_TOOLS = {
    **{n: _placeholder(n, "M4b") for n in _PLACEHOLDER_M4B},
    **{n: _placeholder(n, "M5") for n in _PLACEHOLDER_M5},
}
