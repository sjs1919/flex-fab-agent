"""events.py B 事件层（M3 T3.4）-- 按分布预排 + 随机插单。

事件生成方式（v1 §5.3）：开工/触发时按分布预排下次事件时间戳，插
sim_events（status=scheduled，payload_json 含明细）；engine 每 tick 检查
到点事件 -> 触发（T3.5 fire_events）。

分布参数（system_config category='模拟'，缺省常量）：
  machine_mtbf_h=96 / machine_mttr_h=2（指数）
  order_arrival_rate=2 单/天 / leave_rate=restock_rate=order_change_rate=0.5 次/天
  scrap_rate=0.05 / new_order_max=10（用户需求：每次触发插 1~10 单）

随机插单（用户需求核心）：generate_new_order 每次触发生成 1~10 单随机
订单（随机数量/材料/体积/交期/金额/加急概率）+ parts -> 待排队，进入后续
排产。订单号 SIM 前缀（区别 seed ORD 前缀），零件号 SIMP 前缀。
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta

from flex_fab_agent.simulator import states
from flex_fab_agent.simulator.constants import (
    LEVEL_SCORE, PART_DIM_RANGE, PART_WEIGHT_RANGE, calc_priority,
)

PARAMS_DEFAULT = {
    "machine_mtbf_h": 96,
    "machine_mttr_h": 2,
    "order_arrival_rate": 2,
    "leave_rate": 0.5,
    "restock_rate": 0.5,
    "order_change_rate": 0.5,
    "scrap_rate": 0.05,
    "new_order_max": 10,
}


# — 以下常量已迁移到 simulator/constants.py，通过 import 复用 —
# 保留 re-export 便于外部 import（向后兼容）


def get_sim_params(conn) -> dict:
    """读 system_config（category='模拟'）模拟参数，缺行回落默认常量。"""
    params = dict(PARAMS_DEFAULT)
    with conn.cursor() as cur:
        cur.execute("SELECT `key`, value FROM system_config WHERE category='模拟'")
        for key, value in cur.fetchall():
            if key in params and value is not None:
                try:
                    params[key] = type(params[key])(float(value) if isinstance(
                        params[key], float) else int(value))
                except (TypeError, ValueError):
                    continue  # 配置脏值回落默认
    return params


def _next_interval_hours(event_type: str, params: dict) -> float:
    """按事件类型抽样下次间隔（sim 小时）。rate 单位：次/天 -> /24 转小时率。"""
    samplers = {
        "machine_failure": lambda: random.expovariate(1 / params["machine_mtbf_h"]),
        "repair_done": lambda: random.expovariate(1 / params["machine_mttr_h"]),
        "new_order": lambda: random.expovariate(params["order_arrival_rate"] / 24),
        "leave": lambda: random.expovariate(params["leave_rate"] / 24),
        "restock": lambda: random.expovariate(params["restock_rate"] / 24),
        "order_change": lambda: random.expovariate(params["order_change_rate"] / 24),
    }
    sampler = samplers.get(event_type)
    if sampler is None:
        raise ValueError(f"未知事件类型：{event_type}")
    return sampler()


def schedule_next(cur, event_type: str, from_time: datetime, params: dict,
                  payload: dict | None = None) -> datetime:
    """按分布预排下次事件 -> 插 sim_events(scheduled)，返回预排时刻。"""
    hours = _next_interval_hours(event_type, params)
    fire_at = from_time + timedelta(hours=hours)
    cur.execute(
        "INSERT INTO sim_events (sim_time, event_type, payload_json, status) "
        "VALUES (%s, %s, %s, 'scheduled')",
        (fire_at, event_type,
         json.dumps(payload, ensure_ascii=False) if payload else None))
    return fire_at


def _next_seq(cur, table: str, id_col: str, prefix: str, width: int) -> int:
    """查 {prefix} 前缀 id 的当前最大序号 + 1（无则 1）。"""
    cur.execute(f"SELECT MAX({id_col}) FROM {table} WHERE {id_col} LIKE %s",
                (prefix + "%",))
    row = cur.fetchone()
    return int(row[0][len(prefix):]) + 1 if row and row[0] else 1


def generate_new_order(conn, cur, sim_time: datetime, params: dict | None = None) -> int:
    """随机插单（用户需求）：生成 1~10 单随机订单 + parts -> 待排队。

    随机维度：订单数（1~10）、每单零件数（1~10）、材料（SLA/MJS/SLM）、
    体积（PART_DIM_RANGE）、件重、件数、金额、加急（~1/7）、交期（7~30 天）。
    返回本次插单数。"""
    p = params or PARAMS_DEFAULT
    cur.execute("SELECT id, level FROM customer")
    customers = cur.fetchall()
    if not customers:
        return 0

    order_seq = _next_seq(cur, "orders", "id", "SIM", 5)
    part_seq = _next_seq(cur, "parts", "id", "SIMP", 5)
    n_orders = random.randint(1, p["new_order_max"])
    for _ in range(n_orders):
        cid, level = random.choice(customers)
        amount = round(random.uniform(5000, 800000), 2)
        urgent = 1 if random.random() < 1 / 7 else 0
        priority = calc_priority(level, bool(urgent), amount, default_score=10)
        due = sim_time.date() + timedelta(days=random.randint(7, 30))
        oid = f"SIM{order_seq:05d}"
        order_seq += 1
        cur.execute(
            "INSERT INTO orders (id, customer_id, amount, urgent, priority, due_date, "
            "status, tenant_id) VALUES (%s, %s, %s, %s, %s, %s, '待排队', 'default')",
            (oid, cid, amount, urgent, priority, due))
        states.log_state_change(cur, sim_time, "order", oid, "created", None, "待排队")
        for _ in range(random.randint(1, 10)):
            material = random.choice(["SLA", "MJS", "SLM"])
            lo, hi = PART_DIM_RANGE[material]
            wlo, whi = PART_WEIGHT_RANGE[material]
            cur.execute(
                "INSERT INTO parts (id, order_id, product_id, name, quantity, material, "
                "length, width, height, weight, tenant_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'default')",
                (f"SIMP{part_seq:05d}", oid, f"SIM-{oid}", f"{material}-零件",
                 random.randint(1, 5), material,
                 round(random.uniform(lo, hi), 2), round(random.uniform(lo, hi), 2),
                 round(random.uniform(lo, hi), 2), round(random.uniform(wlo, whi), 2)))
            part_seq += 1
    return n_orders


def seed_schedule_events(cur, sim_time: datetime, params: dict | None = None) -> int:
    """开工预排：每台设备各预排 1 条 machine_failure + 全局 4 类到达事件。

    返回预排事件总数。"""
    p = params or PARAMS_DEFAULT
    n = 0
    cur.execute("SELECT id FROM machines")
    for (mid,) in cur.fetchall():
        schedule_next(cur, "machine_failure", sim_time, p, payload={"machine_id": mid})
        n += 1
    for event_type in ("new_order", "leave", "restock", "order_change"):
        schedule_next(cur, event_type, sim_time, p)
        n += 1
    return n
