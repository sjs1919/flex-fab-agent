"""读一致性快照（M2 T2.1）-- 求解器输入的一体化读取。

设计（v2 §8 B1）：求解输入用**单事务只读快照**（InnoDB REPEATABLE READ）——
同一池连接上连续 SELECT，第一次 SELECT 建立一致性视图，避免 M3 模拟器
并行 tick 写库时读到半新状态（orders 更新到一半 / batches 半写）。

连接说明：走业务连接池 get_connection()（非裸 connect），只读不写，
close() 归还时由池 reset 回滚，无副作用。

CLI：python -m demo.scheduler.snapshot --check  # 打印快照统计
"""
from __future__ import annotations

import sys

from demo.tools.data import get_connection, load_config

# ---- system_config 参数缺省常量（M4 起由 get_config 统一抽象，M2 先用代码默认）----
DEFAULT_PARAMS = {
    "solver_max_time_seconds": 20,  # R-D1 预算，秒（2026-08-27 性能优化 60→20：3 工艺组串行共 ~60s）
    "emergency_reserve": 0.10,      # C8 产能预留 10%（应急池）
    "part_limit": 50,               # C2③ 单批件数上限
    "weight_limit": 600,            # C2④ 单批承重上限 kg
}
_NUMERIC = {"solver_max_time_seconds": int, "emergency_reserve": float,
            "part_limit": int, "weight_limit": float}


def _fetch(cur) -> list[dict]:
    """cursor -> list[dict]（列名作 key）。"""
    cols = [d[0] for d in cur.description] if cur.description else []
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _to_float(v):
    return float(v) if v is not None else None


def _date_str(v):
    """date/datetime -> 'YYYY-MM-DD'；已是 str 原样返回；None 保持。"""
    if v is None or isinstance(v, str):
        return v
    return v.strftime("%Y-%m-%d")


def _normalize_machines(raw: list[dict]) -> list[dict]:
    """过滤仅 status='空闲' 的设备 + 规范化数值字段（C3 机型/容量口径）。"""
    out = []
    for m in raw:
        if m.get("status") != "空闲":
            continue
        out.append({
            "id": m.get("id"),
            "process": m.get("process"),
            "model_type": m.get("model_type"),
            "cabin_size": int(m.get("cabin_size") or 0),
            "max_weight": _to_float(m.get("max_weight")),
            "status": "空闲",
        })
    return out


def load_snapshot() -> dict:
    """单事务只读快照：待排队订单(含违约金费率) + 零件 + 可用设备 + 工艺参数。

    D 幂等（定稿 §3.D）：只取 status='待排队'（persist 锁定为已审核后不再进求解）；
    parts 同步按待排队订单过滤，防已锁订单零件被 pack_parts 打包进后续版本。

    返回规范化结构（Decimal/date → float/str），供 model/solver 直接使用。
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT o.*, c.penalty_rate "
                "FROM orders o JOIN customer c ON o.customer_id = c.id "
                "WHERE o.status = '待排队'"
            )
            orders_raw = _fetch(cur)
            cur.execute(
                "SELECT * FROM parts WHERE order_id IN "
                "(SELECT id FROM orders WHERE status='待排队')")
            parts_raw = _fetch(cur)
            cur.execute("SELECT * FROM machines")
            machines_raw = _fetch(cur)
            cur.execute("SELECT * FROM material")
            material_raw = _fetch(cur)
    finally:
        conn.close()

    orders = []
    for o in orders_raw:
        orders.append({
            "id": o.get("id"),
            "customer_id": o.get("customer_id"),
            "amount": _to_float(o.get("amount")),
            "urgent": int(o.get("urgent") or 0),
            "priority": int(o.get("priority") or 0),
            "due_date": _date_str(o.get("due_date")),
            "status": o.get("status"),
            "penalty_rate": _to_float(o.get("penalty_rate")),
        })
    parts = []
    for p in parts_raw:
        parts.append({
            "id": p.get("id"),
            "order_id": p.get("order_id"),
            "material": p.get("material"),
            "length": _to_float(p.get("length")),
            "width": _to_float(p.get("width")),
            "height": _to_float(p.get("height")),
            "weight": _to_float(p.get("weight")),
            "quantity": int(p.get("quantity") or 1),
        })
    material = []
    for mt in material_raw:
        material.append({
            "process": mt.get("process"),
            "rate_mm_h": _to_float(mt.get("rate_mm_h")),
            "post_process_hours": _to_float(mt.get("post_process_hours")),
        })
    return {
        "orders": orders,
        "parts": parts,
        "machines": _normalize_machines(machines_raw),
        "material": material,
        "params": get_solver_params(),
    }


def get_solver_params() -> dict:
    """读 system_config 的求解参数；空表/缺行回落默认常量。"""
    params = dict(DEFAULT_PARAMS)
    rows = load_config()  # system_config 表，M2 阶段为空 → 默认
    for r in rows:
        key = r.get("key")
        if key in params:
            cast = _NUMERIC[key]
            try:
                params[key] = cast(r.get("value"))
            except (TypeError, ValueError):
                pass  # 非法值回落默认
    return params


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="demo 求解器快照（M2 T2.1）")
    p.add_argument("--check", action="store_true", help="打印快照统计")
    args = p.parse_args(argv)
    if not args.check:
        p.print_help()
        return 1
    snap = load_snapshot()
    params = snap["params"]
    print(f"未完成订单：{len(snap['orders'])} 条")
    print(f"零件：{len(snap['parts'])} 个")
    print(f"可用设备：{len(snap['machines'])} 台")
    print(f"工艺参数：{len(snap['material'])} 类")
    print(f"求解参数：{params}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
