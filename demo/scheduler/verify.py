"""C1-C9 程序化校验器（M2 T2.2）-- 纯函数，输入排产表 + 快照，输出违规清单。

约束口径（v1 §6.2）：
  C1 同舱同材料；C2 容量（单边≤舱边 + Σ投影面积×0.7 + 件数≤part_limit + Σ件重≤承重）；
  C3 机型匹配（工艺分群 + model_type）；C4 批次时长=max(单件时长)（同批并行）；
  C5 整批优先可拆（source ∈ {整批,拆批}）；C6 设备互斥 + 静置占用（interval 含静置）；
  C7 交期按天 23:59（批内最早交期）；C8 日可用 = 24×(1-emergency_reserve) = 21.6h；
  C9 前道完成 ≤ 打印开始（M2 前道数据空 → 恒真）。

CLI：python -m demo.scheduler.verify --verify <result.json>
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta

_TS_FMT = "%Y-%m-%d %H:%M:%S"
OVERSIZE_THRESHOLD = 600  # mm，超过全部机型舱边 → 无法装舱预警


def _dt(s: str) -> datetime:
    return datetime.strptime(s, _TS_FMT)


def _due_dt(date_str) -> datetime:
    """'YYYY-MM-DD' -> 当天 23:59:59。"""
    d = datetime.fromisoformat(date_str).date()
    return datetime(d.year, d.month, d.day, 23, 59, 59)


def _hours(a: str, b: str) -> float:
    return (_dt(b) - _dt(a)).total_seconds() / 3600


def _daily_occupation(batches: list[dict]) -> dict[str, float]:
    """每设备每自然日占用小时数（interval 含静置，跨日切分）。"""
    occ: dict[str, float] = {}
    for b in batches:
        cur = _dt(b["start_time"])
        end = _dt(b["post_process_end"])
        while cur < end:
            next_midnight = (cur + timedelta(days=1)).replace(hour=0, minute=0, second=0)
            seg_end = min(end, next_midnight)
            day_key = cur.date().isoformat()
            occ[day_key] = occ.get(day_key, 0.0) + (seg_end - cur).total_seconds() / 3600
            cur = seg_end
    return occ


def verify(schedule: dict, snapshot: dict, strict_due: bool = False) -> list[str]:
    """校验排产表，返回违规清单（空列表 = 硬约束全满足）。

    C7 交期默认软约束（目标函数为加权迟到，延期入指标层延期清单）；
    strict_due=True 时按硬约束校验 C7。"""
    violations: list[str] = []
    machines = {m["id"]: m for m in snapshot.get("machines", [])}
    material = {mt["process"]: mt for mt in snapshot.get("material", [])}
    orders = {o["id"]: o for o in snapshot.get("orders", [])}
    params = snapshot.get("params", {})
    part_limit = params.get("part_limit", 50)
    emergency_reserve = params.get("emergency_reserve", 0.10)

    by_machine: dict[str, list[dict]] = {}
    for b in schedule.get("batches", []):
        by_machine.setdefault(b["machine_id"], []).append(b)
        bid = b["id"]
        m = machines.get(b["machine_id"])
        # C3 机型匹配
        if not m or b["process"] != m["process"] or b["model_type"] != m["model_type"]:
            violations.append(
                f"C3 批次 {bid}: 机型不匹配（{b['process']}/{b['model_type']} → 设备 {b['machine_id']}）")
            continue
        # C1 同批同材料
        mats = {p["material"] for p in b["parts"]}
        if len(mats) != 1 or b["process"] not in mats:
            violations.append(f"C1 批次 {bid}: 同批材料不一致 {mats}")
        # C2 容量
        count = sum(p["quantity"] for p in b["parts"])
        total_w = sum(p["weight"] * p["quantity"] for p in b["parts"])
        cabin = m["cabin_size"]
        proj = 0.0
        edge_ok = True
        for p in b["parts"]:
            sides = sorted([p["length"], p["width"], p["height"]])  # 升序 [短,中,长]
            if sides[2] > cabin:
                edge_ok = False
            proj += sides[1] * sides[0] * p["quantity"]  # 最长作高，投影 = 中×短
        if not edge_ok:
            violations.append(f"C2 批次 {bid}: 存在单边超舱边 {cabin}mm")
        if proj * 0.7 > cabin * cabin:
            violations.append(f"C2 批次 {bid}: 投影面积 {proj * 0.7:.0f} > 舱底 {cabin * cabin}")
        if count > part_limit:
            violations.append(f"C2 批次 {bid}: 件数 {count} > part_limit {part_limit}")
        if total_w > m["max_weight"]:
            violations.append(f"C2 批次 {bid}: 件重 {total_w:.0f}kg > 承重 {m['max_weight']}kg")
        # C4 批次时长 = max(单件时长)（打印段，不含静置）
        rate = material.get(b["process"], {}).get("rate_mm_h")
        if rate:
            max_part_h = max(max(p["length"], p["width"], p["height"]) / rate for p in b["parts"])
            dur = _hours(b["start_time"], b["end_time"])
            # 容差 2s：求解器整秒排程，舍入误差 ≤0.5s
            if abs(dur - max_part_h) > 2 / 3600:
                violations.append(f"C4 批次 {bid}: 打印时长 {dur}h ≠ max单件 {max_part_h:.2f}h")
        # C7 交期：批内最早交期 23:59；完成含后处理（spec §8：订单完成 = 批次完成 + 后处理延时）
        due_min = None
        for oid in b["order_ids"]:
            d = _due_dt(orders.get(oid, {}).get("due_date")) if orders.get(oid, {}).get("due_date") else None
            if d and (due_min is None or d < due_min):
                due_min = d
        completion = _dt(b["post_process_end"])
        if strict_due and due_min and completion > due_min:
            violations.append(f"C7 批次 {bid}: 完成 {completion} 超交期 {due_min}")
        # C5 source 合法性
        if b.get("source") not in ("整批", "拆批"):
            violations.append(f"C5 批次 {bid}: source 非法 '{b.get('source')}'")

    # C6 设备互斥（interval 含静置，no_overlap）
    for mid, bs in by_machine.items():
        ivs = sorted((_dt(b["start_time"]), _dt(b["post_process_end"]), b["id"]) for b in bs)
        for i in range(1, len(ivs)):
            if ivs[i][0] < ivs[i - 1][1]:
                violations.append(
                    f"C6 设备 {mid}: 批次 {ivs[i - 1][2]} 与 {ivs[i][2]} 时间重叠 "
                    f"({ivs[i - 1][1]} > {ivs[i][0]})")
    # C8 日可用 = 24×(1-emergency_reserve)
    daily_cap = 24 * (1 - emergency_reserve)
    for mid, bs in by_machine.items():
        for day, hours in sorted(_daily_occupation(bs).items()):
            if hours > daily_cap + 1e-6:
                violations.append(
                    f"C8 设备 {mid} {day}: 占用 {hours:.2f}h > 日可用 {daily_cap:.2f}h（预留 "
                    f"{emergency_reserve * 100:.0f}%）")

    # C9 前道完成 ≤ 打印开始：M2 前道数据空 → 恒真
    return violations


def oversize_warnings(snapshot: dict, schedule: dict, threshold: int = OVERSIZE_THRESHOLD) -> list[dict]:
    """超尺寸零件预警清单：max 边 > threshold（无法装舱），且不得出现在排产表。"""
    scheduled_ids = {p["part_id"] for b in schedule.get("batches", []) for p in b["parts"]}
    warnings = []
    for p in snapshot.get("parts", []):
        longest = max(p["length"], p["width"], p["height"])
        if longest > threshold:
            warnings.append({
                "part_id": p["id"],
                "order_id": p["order_id"],
                "quantity": p["quantity"],
                "length": p["length"], "width": p["width"], "height": p["height"],
                "message": f"超尺寸 {longest}mm > {threshold}mm，无法装舱，不入排产表",
            })
            if p["id"] in scheduled_ids:
                warnings[-1]["message"] += "；⚠ 且已错误进入排产表"
    return warnings


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="demo 排产表校验器（M2 T2.2）")
    p.add_argument("--verify", metavar="result.json", help="校验排产表 JSON，打印 C1-C9 违规")
    p.add_argument("--snapshot", metavar="snapshot.json", help="快照 JSON（缺省从库读）")
    args = p.parse_args(argv)
    if not args.verify:
        p.print_help()
        return 1
    with open(args.verify, encoding="utf-8") as f:
        schedule = json.load(f)
    if args.snapshot:
        with open(args.snapshot, encoding="utf-8") as f:
            snapshot = json.load(f)
    else:
        from demo.scheduler.snapshot import load_snapshot
        snapshot = load_snapshot()
    bad = verify(schedule, snapshot)
    if bad:
        print(f"C1-C9 校验发现 {len(bad)} 处违规：")
        for v in bad:
            print(f"  - {v}")
        return 1
    print("C1-C9 校验通过：0 违规")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
