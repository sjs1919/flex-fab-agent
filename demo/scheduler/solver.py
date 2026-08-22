"""solver.py 求解入口（M2 T2.5）-- 装箱 -> CP-SAT 排程 -> 排产表。

R-D1 求解预算三件套：
  1. CP-SAT 预算：params["solver_max_time_seconds"]（默认 60s，model 层执行）
  2. 预算耗尽：返回当前最优可行解 + timed_out=true，不抛错
  3. 无可行解：输出冲突订单清单（NFR-01，含超尺寸/超承重），不静默空结果

CLI：python -m demo.scheduler.solver --solve [--snapshot snap.json] [--out result.json]
"""
from __future__ import annotations

import json
import math
import time
from datetime import datetime

from demo.observability.tracer import tracer
from demo.scheduler import model, verify
from demo.tools.data import transaction

_TS_FMT = "%Y-%m-%d %H:%M:%S"


def _dt(s: str) -> datetime:
    return datetime.strptime(s, _TS_FMT)


def _due_dt(date_str: str) -> datetime:
    """'YYYY-MM-DD' -> 当天 23:59:59（与 verify 口径一致）。"""
    d = datetime.fromisoformat(date_str).date()
    return datetime(d.year, d.month, d.day, 23, 59, 59)


def _delay_days(completion: datetime, due: datetime) -> int:
    return max(0, math.ceil((completion - due).total_seconds() / 86400))


def compute_metrics(schedule: dict, snapshot: dict) -> dict:
    """排产表指标（T2.6）：
      准交率 = 按时完成订单 / 总订单（无排程订单计入分母）；
      延期清单 = 订单 + 延期天数 + 延期金额（金额×违约金日费率×天数）；
      舱利用率 = Σ批次件重 / Σ所用设备承重。"""
    orders = {o["id"]: o for o in snapshot["orders"]}
    machines = {m["id"]: m for m in snapshot["machines"]}
    ends_by_order: dict[str, list[datetime]] = {}
    used_machines: set[str] = set()
    weight_hours = 0.0
    span_times: list[datetime] = []
    for b in schedule["batches"]:
        if not b.get("start_time"):
            continue
        if b.get("machine_id"):
            used_machines.add(b["machine_id"])
        start = _dt(b["start_time"])
        post_end = _dt(b["post_process_end"])
        w = sum(p["weight"] * p["quantity"] for p in b["parts"])
        weight_hours += w * (post_end - start).total_seconds() / 3600
        span_times += [start, post_end]
        for oid in b.get("order_ids", []):
            ends_by_order.setdefault(oid, []).append(post_end)

    on_time = 0
    total = len(orders)
    delay_list: list[dict] = []
    for oid, o in orders.items():
        ends = ends_by_order.get(oid)
        if not ends:
            continue
        completion = max(ends)
        due = _due_dt(o["due_date"]) if o.get("due_date") else None
        if due and completion <= due:
            on_time += 1
            continue
        days = _delay_days(completion, due) if due else None
        delay_amount = round(o.get("amount", 0) * o.get("penalty_rate", 0) * days, 2) \
            if days else 0.0
        delay_list.append({
            "order_id": oid,
            "delay_days": days,
            "amount": o.get("amount"),
            "delay_amount": delay_amount,
            "completion": completion.strftime(_TS_FMT),
            "due_date": o.get("due_date"),
        })
    cap_w = sum(machines[mid]["max_weight"] for mid in used_machines if mid in machines)
    span_h = (max(span_times) - min(span_times)).total_seconds() / 3600 if span_times else 0.0
    # 舱利用率 = Σ(批重×占用时长) / (Σ所用机承重×排程跨度)，≤1 才合理
    cabin_utilization = round(weight_hours / (cap_w * span_h), 4) if cap_w and span_h else 0.0
    return {
        "on_time": on_time,
        "total_orders": total,
        "on_time_rate": round(on_time / total, 4) if total else 0.0,
        "cabin_utilization": cabin_utilization,
        "load_weight_hours": round(weight_hours, 1),
        "capacity_weight": cap_w,
        "span_hours": round(span_h, 1),
        "delay_list": delay_list,
    }


def persist(result: dict, snapshot: dict, triggered_by: str = "initial") -> int:
    """单事务写 schedule_versions + batches，返回 version_id。

    批次号跨版本唯一：batches.id = f"{version_id}-{原批次id}"（表 PK 为 id，
    result_json 保留原批次号语义）。"""
    params = snapshot.get("params", {})
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO schedule_versions (created_at, triggered_by, params_json, "
                "result_json, status) VALUES (NOW(), %s, %s, %s, '待审核')",
                (triggered_by,
                 json.dumps(params, ensure_ascii=False, default=str),
                 json.dumps(result, ensure_ascii=False, default=str)))
            version_id = int(cur.lastrowid)
            for b in result["batches"]:
                cur.execute(
                    "INSERT INTO batches (id, schedule_version_id, order_ids, parts_json, "
                    "process, model_type, machine_id, start_time, end_time, post_process_end, "
                    "status, approval_status, source) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '前道', '待审核', %s)",
                    (f"{version_id}-{b['id']}", version_id,
                     json.dumps(b.get("order_ids", []), ensure_ascii=False),
                     json.dumps(b["parts"], ensure_ascii=False, default=str),
                     b["process"], b["model_type"], b.get("machine_id"),
                     b.get("start_time"), b.get("end_time"), b.get("post_process_end"),
                     b.get("source", "整批")))
    return version_id


def solve(snapshot: dict, params: dict | None = None,
          triggered_by: str = "initial") -> dict:
    """快照 -> 排产表：pack_parts -> solve_scheduling -> 组装 warnings/conflicts/metrics。

    返回 dict：
      batches   排产批次（无可行解时 machine_id/time 为 None）
      warnings  超尺寸/超承重预警（不静默）
      conflicts 冲突清单：排程不可行（含受影响订单）/ 装箱不可行（含订单与明细）
      metrics   {status, objective, timed_out, solver_duration_ms, wall_duration_ms,
                 total_batches, total_parts}
    """
    t0 = time.perf_counter()
    batches, pack_warnings = model.pack_parts(snapshot)
    schedule, meta = model.solve_scheduling(batches, snapshot, params)

    oversize = verify.oversize_warnings(snapshot, schedule)
    seen = {(w.get("part_id"), w.get("order_id")) for w in oversize}
    schedule["warnings"] = oversize + [w for w in pack_warnings
                                       if (w.get("part_id"), w.get("order_id")) not in seen]

    conflicts: list[dict] = []
    sched_ok = meta["status"] in ("OPTIMAL", "FEASIBLE")
    if not sched_ok and batches:
        order_ids = sorted({oid for b in schedule["batches"] for oid in b["order_ids"]})
        conflicts.append({
            "type": "scheduling",
            "reason": f"排程不可行（CP-SAT {meta['status']}）：{len(batches)} 批无可行排产方案",
            "order_ids": order_ids,
        })
    if pack_warnings:
        order_ids = sorted({w["order_id"] for w in pack_warnings})
        conflicts.append({
            "type": "packing",
            "reason": f"{len(pack_warnings)} 个零件无法装舱（超尺寸/超承重），不入排产表",
            "order_ids": order_ids,
            "details": pack_warnings,
        })
    schedule["conflicts"] = conflicts

    wall_ms = round((time.perf_counter() - t0) * 1000, 1)
    schedule["metrics"] = {
        "status": meta["status"],
        "objective": meta["objective"],
        "timed_out": meta["timed_out"],
        "solver_duration_ms": meta["duration_ms"],
        "wall_duration_ms": wall_ms,
        "total_batches": len(schedule["batches"]),
        "total_parts": sum(p["quantity"] for b in schedule["batches"] for p in b["parts"]),
        "verify_violations": len(verify.verify(schedule, snapshot)),
        **compute_metrics(schedule, snapshot),
    }
    tracer.record("solver:run_scheduling", wall_ms,
                  objective=meta["objective"],
                  timed_out=meta["timed_out"],
                  status=meta["status"],
                  verify_violations=schedule["metrics"]["verify_violations"],
                  triggered_by=triggered_by)
    return schedule


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="demo 排产求解入口（M2 T2.5/T2.6）")
    p.add_argument("--solve", action="store_true", help="读快照求解，打印排产表 + 指标 + 耗时")
    p.add_argument("--snapshot", metavar="snapshot.json", help="快照 JSON（缺省从库读）")
    p.add_argument("--out", metavar="result.json", help="排产表输出 JSON 路径")
    p.add_argument("--persist", metavar="triggered_by", nargs="?", const="initial",
                   help="求解后写库（schedule_versions/batches），可选触发源")
    args = p.parse_args(argv)
    if not args.solve:
        p.print_help()
        return 1
    if args.snapshot:
        with open(args.snapshot, encoding="utf-8") as f:
            snapshot = json.load(f)
    else:
        from demo.scheduler.snapshot import load_snapshot
        snapshot = load_snapshot()

    result = solve(snapshot, triggered_by=args.persist or "initial")
    m = result["metrics"]
    print(f"求解完成：{m['status']} | 批次 {m['total_batches']} | 零件 {m['total_parts']} 件")
    print(f"目标值 {m['objective']} | 求解耗时 {m['solver_duration_ms']:.0f}ms | "
          f"总耗时 {m['wall_duration_ms']:.0f}ms | timed_out={m['timed_out']}")
    print(f"指标：准交率 {m['on_time_rate']}（{m['on_time']}/{m['total_orders']}）| "
          f"舱利用率 {m['cabin_utilization']} | 延期 {len(m['delay_list'])} 单")
    if result["warnings"]:
        print(f"预警 {len(result['warnings'])} 条：")
        for w in result["warnings"]:
            print(f"  - {w.get('part_id', '?')}（订单 {w.get('order_id', '?')}）：{w['message']}")
    if result["conflicts"]:
        print(f"冲突 {len(result['conflicts'])} 项：")
        for c in result["conflicts"]:
            print(f"  - [{c['type']}] {c['reason']}，涉及订单 {c['order_ids']}")
    if args.persist:
        version_id = persist(result, snapshot, triggered_by=args.persist)
        print(f"已写库：schedule_versions id={version_id}，批次 {m['total_batches']} 行（待审核）")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        print(f"排产表已写入 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
