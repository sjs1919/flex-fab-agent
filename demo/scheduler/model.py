"""排产模型（M2 T2.3/T2.4）-- 两段式：贪心装箱 + CP-SAT 排程。

Step1 `pack_parts`（本文件 T2.3）：确定性装箱，非 CP 变量。
  - 材料->机型分组（C1 同舱同材料 / C3 机型匹配）
  - 排序键：交期升序 -> priority 降序（v1 §6.2）
  - C2 容量贪心：单边≤舱边 + Σ投影×0.7≤舱底 + 件数≤part_limit + Σ件重≤承重
  - 整批优先（同订单先试现有批）、超舱可拆（新批标 source='拆批'）
  - 超尺寸 part（max>600）入预警清单，不入批（不静默）

Step2 `solve_scheduling`（T2.4）：CP-SAT 排程，按工艺分组独立求解，
  批次->设备 + 时间槽。C8 为自然日交集精确语义（与 verify 口径一致）。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from ortools.sat.python import cp_model

from demo.scheduler import verify

OVERSIZE_THRESHOLD = verify.OVERSIZE_THRESHOLD
_TS_FMT = "%Y-%m-%d %H:%M:%S"
_DAY_SEC = 86400


def _proj(p: dict) -> float:
    """投影面积：最长边作高，投影 = 中×短（装舱最小化底面）。"""
    sides = sorted([p["length"], p["width"], p["height"]])  # 升序 [短,中,长]
    return sides[1] * sides[0]


def _to_part(p: dict) -> dict:
    """snapshot part（key 'id'）-> batch part（key 'part_id'）。"""
    return {
        "part_id": p["id"], "order_id": p["order_id"], "material": p["material"],
        "length": p["length"], "width": p["width"], "height": p["height"],
        "weight": p["weight"], "quantity": p["quantity"],
    }


def pack_parts(snapshot: dict) -> tuple[list[dict], list[dict]]:
    """Step1 贪心装箱。返回 (batches, warnings)；超尺寸预警不入批。

    batch 字段：id/order_ids/parts/process/model_type/machine_id(None)/
    start_time|end_time|post_process_end(None)/source。
    """
    parts = snapshot["parts"]
    machines = snapshot["machines"]
    orders = {o["id"]: o for o in snapshot["orders"]}
    part_limit = snapshot["params"].get("part_limit", 50)

    warnings = verify.oversize_warnings(snapshot, {"batches": []})
    warn_ids = {w["part_id"] for w in warnings}
    packable = [p for p in parts if p["id"] not in warn_ids]
    if not packable:
        return [], warnings

    # 机型容量字典：(process, model_type) -> {cabin_size, max_weight}
    models: dict[tuple, dict] = {}
    for m in machines:
        key = (m["process"], m["model_type"])
        models.setdefault(key, {"cabin_size": m["cabin_size"], "max_weight": m["max_weight"]})

    def _fits(batch: dict, part: dict, cap: dict) -> bool:
        """C2 容量：单边 / Σ投影×0.7 / 件数 / Σ件重。"""
        sides = sorted([part["length"], part["width"], part["height"]])
        if sides[2] > cap["cabin_size"]:
            return False
        proj = sum(_proj(p) * p["quantity"] for p in batch["parts"]) + _proj(part) * part["quantity"]
        if proj * 0.7 > cap["cabin_size"] ** 2:
            return False
        if sum(p["quantity"] for p in batch["parts"]) + part["quantity"] > part_limit:
            return False
        if (sum(p["weight"] * p["quantity"] for p in batch["parts"])
                + part["weight"] * part["quantity"] > cap["max_weight"]):
            return False
        return True

    def _sort_key(p: dict):
        o = orders.get(p["order_id"], {})
        return (o.get("due_date", "9999-99-99"), -o.get("priority", 0), p["id"])

    packable.sort(key=_sort_key)

    batches: list[dict] = []
    batch_of_model: dict[tuple, list[int]] = {}
    order_to_batches: dict[str, set[int]] = {}
    cannot_pack: list[dict] = []
    seq = 0

    for p in packable:
        max_edge = max(p["length"], p["width"], p["height"])
        oid = p["order_id"]
        # 可行机型（工艺匹配 + 舱边可容 + 单件可承重），选舱边最小的省大舱
        cand = sorted(
            ((proc, mt) for (proc, mt), cap in models.items()
             if proc == p["material"] and cap["cabin_size"] >= max_edge
             and cap["max_weight"] >= p["weight"]),
            key=lambda km: models[km]["cabin_size"],
        )
        if not cand:
            # 无法装舱（C2 硬约束）：单件超所有可行机型承重 -> 显式预警，不入批
            cannot_pack.append({
                "part_id": p["id"], "order_id": oid,
                "weight": p["weight"], "quantity": p["quantity"],
                "message": (f"单件重量 {p['weight']:.0f}kg 超所有可行机型承重，无法装舱，不入排产表"),
            })
            continue
        # 单舱最大件数 k：投影/承重/件数三约束取最小，跨机型取最大
        per_proj = _proj(p)
        k = 0
        for key in cand:
            cap = models[key]
            kp = int(cap["cabin_size"] ** 2 / (0.7 * per_proj)) if per_proj else part_limit
            kw = int(cap["max_weight"] / p["weight"]) if p["weight"] else part_limit
            k = max(k, min(kp, kw, part_limit))
        if k == 0:
            cannot_pack.append({
                "part_id": p["id"], "order_id": oid,
                "weight": p["weight"], "quantity": p["quantity"],
                "message": (f"单件投影面积 {per_proj:.0f}mm² 超所有可行机型舱底，无法装舱，不入排产表"),
            })
            continue
        # 数量超单舱容量 -> 按舱容量分块（C5 超舱可拆），逐块走 整批优先->同机型->新建
        chunks = [k] * (p["quantity"] // k)
        if p["quantity"] % k:
            chunks.append(p["quantity"] % k)
        for q in chunks:
            pv = dict(p, quantity=q)
            placed = False
            # ① 整批优先：同订单现有批
            for idx in order_to_batches.get(oid, []):
                b = batches[idx]
                key = (b["process"], b["model_type"])
                if key in cand and _fits(b, pv, models[key]):
                    b["parts"].append(_to_part(pv))
                    placed = True
                    break
            # ② 同机型任意批
            if not placed:
                for key in cand:
                    for idx in batch_of_model.get(key, []):
                        if _fits(batches[idx], pv, models[key]):
                            batches[idx]["parts"].append(_to_part(pv))
                            placed = True
                            break
                    if placed:
                        break
            # ③ 新建批次（最小可行机型，校验单块可装）
            if not placed:
                for key in cand:
                    if not _fits({"parts": []}, pv, models[key]):
                        continue
                    seq += 1
                    batches.append({
                        "id": f"B{seq}",
                        "order_ids": [oid],
                        "parts": [_to_part(pv)],
                        "process": key[0],
                        "model_type": key[1],
                        "machine_id": None,
                        "start_time": None, "end_time": None, "post_process_end": None,
                        "source": "拆批" if oid in order_to_batches else "整批",
                    })
                    batch_of_model.setdefault(key, []).append(len(batches) - 1)
                    order_to_batches.setdefault(oid, set()).add(len(batches) - 1)
                    placed = True
                    break
            if not placed:
                cannot_pack.append({
                    "part_id": p["id"], "order_id": oid,
                    "weight": p["weight"], "quantity": q,
                    "message": f"零件 {p['id']} 分块（数量 {q}）无可行机型可装，不入排产表",
                })

    for b in batches:
        b["order_ids"] = sorted({p["order_id"] for p in b["parts"]})
    return batches, warnings + cannot_pack


# ---- Step 2 · CP-SAT 排程（T2.4）----

def _material_map(snapshot) -> tuple[dict, dict]:
    """process -> (rate_mm_h, post_process_hours)。"""
    rate, post = {}, {}
    for m in snapshot.get("material", []):
        rate[m["process"]] = m.get("rate_mm_h")
        post[m["process"]] = m.get("post_process_hours")
    return rate, post


def _batch_duration_sec(b: dict, rate: dict, post: dict) -> tuple[int, int]:
    """(print_sec, total_sec)。C4：打印 = max(单件时长)；total = 打印 + 静置。"""
    mx = max(max(p["length"], p["width"], p["height"]) for p in b["parts"])
    print_sec = int(round(mx / rate[b["process"]] * 3600))
    post_sec = int(round((post.get(b["process"]) or 0) * 3600))
    return print_sec, print_sec + post_sec


def _default_base_dt(snapshot) -> datetime:
    """基准时刻：最早交期日 - 7 天 00:00（排产启动窗口，覆盖全部订单）。"""
    dues = [o["due_date"] for o in snapshot.get("orders", []) if o.get("due_date")]
    earliest = min(datetime.fromisoformat(d) for d in dues) if dues else datetime(2026, 9, 1)
    return (earliest - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)


def _due_sec(due_str: str, base_dt: datetime) -> int:
    """交期 'YYYY-MM-DD' 当天 23:59:59 相对 base 的秒。"""
    d = datetime.fromisoformat(due_str).date()
    due_dt = datetime(d.year, d.month, d.day, 23, 59, 59)
    return int((due_dt - base_dt).total_seconds())


def _batch_weight(b: dict, orders: dict) -> int:
    """批权重 = Σ 批内订单 amount×penalty_rate（×10000 保精度）。"""
    w = 0.0
    for oid in b.get("order_ids", []):
        o = orders.get(oid, {})
        w += (o.get("amount") or 0) * (o.get("penalty_rate") or 0)
    return int(round(w * 10000))


def solve_scheduling(batches: list[dict], snapshot: dict, params: dict | None = None,
                     base_dt: str | None = None) -> tuple[dict, dict]:
    """CP-SAT 排程：批次->机器 + 时间槽（C6/C7/C8）。

    按工艺分组独立求解：机器不跨工艺共享、约束组间独立、目标可加
    （Σ w·lat + Σ end），子模型并集即全局最优，规模 ÷3。

    返回 (schedule, meta)：
      schedule = {"batches": [{id, order_ids, parts, process, model_type,
                               machine_id, start_time, end_time, post_process_end, source}],
                  "metrics": {}, "warnings": [], "conflicts": []}
      meta = {"status", "objective", "latencies", "duration_ms", "timed_out"}
    """
    params = params or snapshot.get("params", {})
    reserve = params.get("emergency_reserve", 0.10)
    cap_sec = int(round(_DAY_SEC * (1 - reserve)))          # 21.6h
    max_time = params.get("solver_max_time_seconds", 60)
    base = datetime.strptime(base_dt, _TS_FMT) if base_dt else _default_base_dt(snapshot)
    rate, post = _material_map(snapshot)
    orders = {o["id"]: o for o in snapshot.get("orders", [])}
    machines = snapshot["machines"]

    groups: dict[str, list[dict]] = {}
    for b in batches:
        groups.setdefault(b["process"], []).append(b)

    out_batches, latencies = [], {}
    weighted = 0.0
    statuses, total_ms, timed_out = [], 0.0, False
    infeasible_groups: list[str] = []
    infeasible_order_ids: set[str] = set()
    for proc in sorted(groups):
        sub = groups[proc]
        sub_machines = [m for m in machines if m["process"] == proc]
        out, meta = _solve_group(sub, sub_machines, rate, post, orders, base,
                                 cap_sec, max_time)
        total_ms += meta["duration_ms"]
        timed_out = timed_out or meta["timed_out"]
        if meta["status"] not in ("OPTIMAL", "FEASIBLE"):
            # 工艺组级部分成功（定稿 u-d-1）：剔除不可行组批次（不入 out_batches），
            # 其他组照常排；meta 记 infeasible_groups/infeasible_order_ids 供 NFR-01
            # 输出无解订单清单（保持待排队下轮重排）。
            infeasible_groups.append(proc)
            for b in sub:
                infeasible_order_ids.update(b.get("order_ids", []))
            continue
        statuses.append(meta["status"])
        out_batches.extend(out)
        latencies.update(meta["latencies"])
        weighted += meta["objective"] or 0.0
    if not out_batches:
        # 全部工艺组不可行 → 返回空排产表（persist 据此跳过建版本，防刷屏）。
        # _infeasible_schedule 保留仅作兜底（全 None 批次），不再由本循环调用。
        return {"batches": [], "metrics": {}, "warnings": [], "conflicts": []}, {
            "status": "INFEASIBLE", "objective": None, "latencies": {},
            "duration_ms": total_ms, "timed_out": timed_out,
            "infeasible_groups": infeasible_groups,
            "infeasible_order_ids": sorted(infeasible_order_ids)}
    # 恢复输入批序（分组求解打乱顺序）
    order = {b["id"]: i for i, b in enumerate(batches)}
    out_batches.sort(key=lambda ob: order.get(ob["id"], 0))
    status = "OPTIMAL" if all(s == "OPTIMAL" for s in statuses) else "FEASIBLE"
    return {"batches": out_batches, "metrics": {}, "warnings": [], "conflicts": []}, {
        "status": status, "objective": weighted, "latencies": latencies,
        "duration_ms": total_ms, "timed_out": timed_out,
        "infeasible_groups": infeasible_groups,
        "infeasible_order_ids": sorted(infeasible_order_ids)}


def _daily_overlap(start: int, size: int) -> dict[int, int]:
    """[start, start+size) 按自然日切分 -> {day: 秒}。"""
    out = {}
    pos, end = start, start + size
    while pos < end:
        day = pos // _DAY_SEC
        day_end = (day + 1) * _DAY_SEC
        seg = min(end, day_end) - pos
        out[day] = out.get(day, 0) + seg
        pos += seg
    return out


def _greedy_hint(prep: list[dict], machines: list[dict], cap_sec: int,
                 horizon_sec: int) -> dict[int, tuple[str, int]] | None:
    """贪心初解（C6+C8 可行）：交期升序、权重降序逐批放置。

    返回 {bi: (machine_id, start_sec)}；贪心失败返回 None（不代表无解）。
    """
    order = sorted(range(len(prep)), key=lambda i: (prep[i]["due_sec"], -prep[i]["w"]))
    busy: dict[str, list[tuple[int, int]]] = {m["id"]: [] for m in machines}
    daily: dict[str, dict[int, int]] = {m["id"]: {} for m in machines}
    hints = {}
    for bi in order:
        p = prep[bi]
        size = p["total_sec"]
        best = None  # (start, machine_id)
        for f in p["feasible"]:
            mid = f["id"]
            start = 0
            while start <= p["s_max"] and start + size <= horizon_sec:
                nxt = None
                for (bs, be) in busy[mid]:
                    if start < be and bs < start + size:  # C6 重叠
                        nxt = be
                        break
                if nxt is not None:
                    start = nxt
                    continue
                # C8 日容量：超容量的最早日 -> 跳到次日 00:00
                jump = None
                for day, occ in _daily_overlap(start, size).items():
                    if daily[mid].get(day, 0) + occ > cap_sec:
                        jump = (day + 1) * _DAY_SEC
                        break
                if jump is not None:
                    start = jump
                    continue
                if best is None or start < best[0]:
                    best = (start, mid)
                break
        if best is None:
            return None
        start, mid = best
        busy[mid].append((start, start + size))
        for day, occ in _daily_overlap(start, size).items():
            daily[mid][day] = daily[mid].get(day, 0) + occ
        hints[bi] = (mid, start)
    return hints


def _solve_group(batches: list[dict], machines: list[dict], rate: dict, post: dict,
                 orders: dict, base: datetime, cap_sec: int,
                 max_time: float) -> tuple[list[dict], dict]:
    """单工艺组 CP-SAT。C6 = 机器 no_overlap；C8 = 自然日交集容量（精确语义）。

    C7 软约束（加权迟到目标）：start 上界 = 组完工上界 max(最晚交期, 各机型
    工时/产能折天数) + 7 天余量，保证过载组（如 SLM 单机）有可行解。
    """
    mdl = cp_model.CpModel()
    midx = {m["id"]: i for i, m in enumerate(machines)}
    prep = []
    for b in batches:
        print_sec, total_sec = _batch_duration_sec(b, rate, post)
        due_secs = [_due_sec(orders[oid]["due_date"], base)
                    for oid in b.get("order_ids", [])
                    if oid in orders and orders[oid].get("due_date")]
        prep.append({"b": b, "print_sec": print_sec, "total_sec": total_sec,
                     "due_sec": min(due_secs) if due_secs else None,
                     "feasible": [m for m in machines if m["model_type"] == b["model_type"]],
                     "w": _batch_weight(b, orders)})
    if any(not p["feasible"] for p in prep):
        # 工艺组无可行设备（快照按 status='空闲' 过滤，组内设备全忙/全故障即零设备；
        # 或批机型与组内设备机型全不匹配）→ 组不可行。交 solve_scheduling 组级短路
        # 剔除该组（否则下方 n_by_mt=0 除零崩溃，短路拿不到状态）。
        return [], {"status": "INFEASIBLE", "objective": None, "latencies": {},
                    "duration_ms": 0.0, "timed_out": False}
    max_due = max((p["due_sec"] for p in prep if p["due_sec"] is not None),
                  default=30 * _DAY_SEC)
    for p in prep:
        if p["due_sec"] is None:
            p["due_sec"] = max_due
    # 组完工上界：各机型总工时 / (机数×日产能) 折天数（工时守恒下界），与最晚交期取大
    bound = max_due
    work_by_mt: dict[str, int] = {}
    n_by_mt: dict[str, int] = {}
    for p in prep:
        mt = p["b"]["model_type"]
        work_by_mt[mt] = work_by_mt.get(mt, 0) + p["total_sec"]
        n_by_mt[mt] = len(p["feasible"])
    for mt, work in work_by_mt.items():
        need = -(-work // (n_by_mt[mt] * cap_sec)) * _DAY_SEC  # ceil 折天
        bound = max(bound, need)
    s_bound = bound + 7 * _DAY_SEC
    days = s_bound // _DAY_SEC + 1
    for p in prep:
        p["s_max"] = s_bound

    starts, ends, lat_vars = [], [], []
    assign = {}          # (bi, mi) -> BoolVar
    iv_by_machine = {}   # mi -> [IntervalVar]（C6）
    for bi, p in enumerate(prep):
        b = p["b"]
        s = mdl.NewIntVar(0, p["s_max"], f"start_{b['id']}")
        e = mdl.NewIntVar(0, p["s_max"] + p["total_sec"], f"end_{b['id']}")
        mdl.Add(e == s + p["total_sec"])
        mdl.Add(e <= s_bound)
        starts.append(s)
        ends.append(e)
        lat = mdl.NewIntVar(0, 365, f"lat_{b['id']}")
        mdl.Add(e <= p["due_sec"] + lat * _DAY_SEC)
        lat_vars.append(lat)
        if len(p["feasible"]) == 1:
            mi = midx[p["feasible"][0]["id"]]
            x = mdl.NewBoolVar(f"x_{b['id']}")
            mdl.Add(x == 1)
            assign[(bi, mi)] = x
            iv_by_machine.setdefault(mi, []).append(
                mdl.NewOptionalIntervalVar(s, p["total_sec"], e, x, f"iv_{b['id']}"))
        else:
            xs = []
            for f in p["feasible"]:
                mi = midx[f["id"]]
                x = mdl.NewBoolVar(f"x_{b['id']}_{f['id']}")
                assign[(bi, mi)] = x
                xs.append(x)
                iv_by_machine.setdefault(mi, []).append(
                    mdl.NewOptionalIntervalVar(s, p["total_sec"], e, x, f"iv_{b['id']}_{f['id']}"))
            mdl.Add(sum(xs) == 1)
    for ivs in iv_by_machine.values():
        mdl.AddNoOverlap(ivs)

    # C8：批-自然日交集（六种位置关系互斥完备），当日占用 l 精确 = 交集长度
    day_dem = {}  # (mi, d) -> [w_var]（w = l×x 线性化）
    z_by = {}     # (bi, d) -> {zin..zg, l}：hint 补全用
    w_by = {}     # (bi, mi, d) -> w_var
    for bi, p in enumerate(prep):
        b = p["b"]
        size = p["total_sec"]
        dmax = min(days - 1, (p["s_max"] + size) // _DAY_SEC)
        for d in range(dmax + 1):
            D0, D1 = d * _DAY_SEC, (d + 1) * _DAY_SEC
            z_in = mdl.NewBoolVar(f"zin_{b['id']}_{d}")   # 整段在日内
            z_l = mdl.NewBoolVar(f"zl_{b['id']}_{d}")     # 跨日开始（s<D0, e 在日内）
            z_r = mdl.NewBoolVar(f"zr_{b['id']}_{d}")     # 跨日结束（s 在日内, e>D1）
            z_o = mdl.NewBoolVar(f"zo_{b['id']}_{d}")     # 横跨整天
            z_e = mdl.NewBoolVar(f"ze_{b['id']}_{d}")     # 整段在日前（e≤D0）
            z_g = mdl.NewBoolVar(f"zg_{b['id']}_{d}")     # 整段在日后（s≥D1）
            mdl.Add(z_in + z_l + z_r + z_o + z_e + z_g == 1)
            mdl.Add(starts[bi] >= D0).OnlyEnforceIf(z_in)
            mdl.Add(ends[bi] <= D1).OnlyEnforceIf(z_in)
            mdl.Add(starts[bi] <= D0 - 1).OnlyEnforceIf(z_l)
            mdl.Add(ends[bi] >= D0 + 1).OnlyEnforceIf(z_l)
            mdl.Add(ends[bi] <= D1).OnlyEnforceIf(z_l)
            mdl.Add(starts[bi] >= D0).OnlyEnforceIf(z_r)
            mdl.Add(starts[bi] <= D1 - 1).OnlyEnforceIf(z_r)
            mdl.Add(ends[bi] >= D1 + 1).OnlyEnforceIf(z_r)
            mdl.Add(starts[bi] <= D0 - 1).OnlyEnforceIf(z_o)
            mdl.Add(ends[bi] >= D1 + 1).OnlyEnforceIf(z_o)
            mdl.Add(ends[bi] <= D0).OnlyEnforceIf(z_e)
            mdl.Add(starts[bi] >= D1).OnlyEnforceIf(z_g)
            l = mdl.NewIntVar(0, _DAY_SEC, f"l_{b['id']}_{d}")
            z_by[(bi, d)] = {"zin": z_in, "zl": z_l, "zr": z_r,
                             "zo": z_o, "ze": z_e, "zg": z_g, "l": l}
            mdl.Add(l == size).OnlyEnforceIf(z_in)
            mdl.Add(l == ends[bi] - D0).OnlyEnforceIf(z_l)
            mdl.Add(l == D1 - starts[bi]).OnlyEnforceIf(z_r)
            mdl.Add(l == _DAY_SEC).OnlyEnforceIf(z_o)
            mdl.Add(l == 0).OnlyEnforceIf(z_e)
            mdl.Add(l == 0).OnlyEnforceIf(z_g)
            for f in p["feasible"]:
                mi = midx[f["id"]]
                x = assign[(bi, mi)]
                w = mdl.NewIntVar(0, _DAY_SEC, f"w_{b['id']}_{f['id']}_{d}")
                w_by[(bi, mi, d)] = w
                mdl.Add(w <= l)
                mdl.Add(w <= _DAY_SEC * x)
                mdl.Add(w >= l - _DAY_SEC * (1 - x))
                day_dem.setdefault((mi, d), []).append(w)
    for ws in day_dem.values():
        mdl.Add(sum(ws) <= cap_sec)

    # 目标：主 = 加权迟到 Σ w×lat；次 = 尽早完成 Σ end
    mdl.Minimize(
        sum(p["w"] * lat_vars[bi] for bi, p in enumerate(prep))
        + sum(ends[bi] for bi in range(len(prep))))

    # 贪心初解 hints：完整可行解（start/assign/lat/z/l/w 全部推导补全），
    # 跳过「找首个可行解」的搜索阶段，直接从可行解优化
    hints = _greedy_hint(prep, machines, cap_sec, s_bound)
    if hints:
        for bi, (mid, start) in hints.items():
            p = prep[bi]
            e_val = start + p["total_sec"]
            mdl.AddHint(starts[bi], start)
            mdl.AddHint(ends[bi], e_val)
            mdl.AddHint(lat_vars[bi], -(-max(0, e_val - p["due_sec"]) // _DAY_SEC))
            for f in p["feasible"]:
                mdl.AddHint(assign[(bi, midx[f["id"]])], 1 if f["id"] == mid else 0)
            for (bi2, d), z in z_by.items():
                if bi2 != bi:
                    continue
                D0, D1 = d * _DAY_SEC, (d + 1) * _DAY_SEC
                if e_val <= D0:
                    on, l_val = "ze", 0
                elif start >= D1:
                    on, l_val = "zg", 0
                elif start >= D0 and e_val <= D1:
                    on, l_val = "zin", p["total_sec"]
                elif start <= D0 - 1 and e_val >= D1 + 1:
                    on, l_val = "zo", _DAY_SEC
                elif start <= D0 - 1:
                    on, l_val = "zl", e_val - D0
                else:
                    on, l_val = "zr", D1 - start
                for name, var in z.items():
                    if name == "l":
                        mdl.AddHint(var, l_val)
                    else:
                        mdl.AddHint(var, 1 if name == on else 0)
                for f in p["feasible"]:
                    w = w_by.get((bi, midx[f["id"]], d))
                    if w is not None:
                        mdl.AddHint(w, l_val if f["id"] == mid else 0)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_time
    solver.parameters.num_search_workers = 8
    status = solver.Solve(mdl)
    status_name = solver.StatusName(status)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # R-D1 兜底：预算耗尽连首解都未出（如 presolve 占满预算）时，
        # 返回贪心 hint 作为次优可行解（贪心已保证 C6+C8），不空手而归
        if hints:
            out, latencies, weighted = [], {}, 0.0
            for bi, p in enumerate(prep):
                mid, start = hints[bi]
                e_val = start + p["total_sec"]
                lat = -(-max(0, e_val - p["due_sec"]) // _DAY_SEC)
                latencies[p["b"]["id"]] = int(lat)
                weighted += p["w"] * lat
                out.append(_out_batch(p["b"], mid, start, p["print_sec"],
                                      p["total_sec"], base))
            return out, {"status": "FEASIBLE", "objective": weighted / 10000.0,
                         "latencies": latencies,
                         "duration_ms": solver.WallTime() * 1000,
                         "timed_out": True}
        return [], {"status": status_name, "objective": None, "latencies": {},
                    "duration_ms": solver.WallTime() * 1000,
                    "timed_out": solver.WallTime() >= max_time}

    out = []
    latencies = {}
    for bi, p in enumerate(prep):
        b = p["b"]
        start_val = solver.Value(starts[bi])
        machine_id = next((f["id"] for f in p["feasible"]
                           if solver.Value(assign[(bi, midx[f["id"]])]) == 1), None)
        latencies[b["id"]] = int(solver.Value(lat_vars[bi]))
        out.append(_out_batch(b, machine_id, start_val, p["print_sec"],
                              p["total_sec"], base))
    weighted = sum(p["w"] * solver.Value(lat_vars[bi])
                   for bi, p in enumerate(prep)) / 10000.0
    return out, {
        "status": status_name, "objective": weighted, "latencies": latencies,
        "duration_ms": solver.WallTime() * 1000,
        "timed_out": solver.WallTime() >= max_time}


def _out_batch(b: dict, machine_id: str | None, start_val: int,
               print_sec: int, total_sec: int, base: datetime) -> dict:
    """排产输出批次（CP-SAT 解与贪心兜底共用）。"""
    return {
        "id": b["id"], "order_ids": b["order_ids"], "parts": b["parts"],
        "process": b["process"], "model_type": b["model_type"],
        "machine_id": machine_id,
        "start_time": (base + timedelta(seconds=start_val)).strftime(_TS_FMT),
        "end_time": (base + timedelta(seconds=start_val + print_sec)).strftime(_TS_FMT),
        "post_process_end": (base + timedelta(seconds=start_val + total_sec)).strftime(_TS_FMT),
        "source": b["source"],
    }


def _infeasible_schedule(batches: list[dict]) -> dict:
    """无可行解：批次保留空排程字段，conflicts 由 solver 层填。"""
    out = []
    for b in batches:
        out.append({
            "id": b["id"], "order_ids": b["order_ids"], "parts": b["parts"],
            "process": b["process"], "model_type": b["model_type"],
            "machine_id": None, "start_time": None, "end_time": None,
            "post_process_end": None, "source": b["source"],
        })
    return {"batches": out, "metrics": {}, "warnings": [], "conflicts": []}
