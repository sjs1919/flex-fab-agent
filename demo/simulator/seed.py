"""种子生成器（M1 T1.3，⭐ 新建 demo/simulator/ 包）。

确定性生成（固定随机种子）→ `--reset` 幂等重建（先清后插），满足 todo T1.3 口径：
- 7 台设备：SLA600×1 + SLA450×2 / MJS600×1 + MJS450×2 / SLM600×1
- 5 客户（沿用 customers.csv 口径 + 补 penalty_rate：S=0.01/A=0.005/B=C=0.003）
- 40 订单（amount/urgent/priority/due_date/status=待排队）+ 数百 part（包络盒三边/件重）
- 10 种材料库存（沿用 inventory.csv 口径）
- 超尺寸样例（≥1 part 某边 >600mm，M2 预警验收预留）

CLI：`python -m demo.simulator.seed --reset | --seed`
连接说明：运维脚本（批量 DML），直连 pymysql（解析 config.get_mysql_dsn()），
不走业务连接池（T2.1 R-D3 验收 grep 豁免 demo/schema/ 与 demo/simulator/）。
"""
from __future__ import annotations

import random
import sys
from datetime import date, timedelta

import pymysql

from demo.schema import migrate
from demo.simulator.constants import (
    LEVEL_SCORE, PART_DIM_RANGE, PART_WEIGHT_RANGE, calc_priority,
)
from demo.tools.data import create_raw_connection

# 固定种子 → 幂等（两次执行数据一致）
random.seed(42)

# 业务表（seed 管理的表；schedule_versions/batches 等由 solver 管，不清）
SEED_TABLES = ["customer", "orders", "parts", "machines", "material", "inventory", "personnel"]

# 客户：沿用现有 customers.csv 口径 + penalty_rate（v1 §3.17：S=0.01/A=0.005/B=C=0.003）
CUSTOMERS = [
    ("C001", "深圳精密五金", "A", 92, 0.85, "消费电子", 0.005),
    ("C002", "东莞模具厂", "B", 78, 0.92, "汽车模具", 0.003),
    ("C003", "广州航天精工", "S", 98, 0.80, "航空航天", 0.010),
    ("C004", "惠州医疗器械", "C", 65, 0.95, "医疗器械", 0.003),
    ("C005", "佛山智能家居", "B", 82, 0.90, "智能家居", 0.003),
]
# LEVEL_SCORE 从 simulator.constants import（下同）

# 设备 7 台（id / name / process / model_type / cabin_size / max_weight）
MACHINES = [
    ("M0001", "SLA600", "SLA", "600", 600, 100),
    ("M0002", "SLA450-A", "SLA", "450", 450, 50),
    ("M0003", "SLA450-B", "SLA", "450", 450, 50),
    ("M0004", "MJS600", "MJS", "600", 600, 150),
    ("M0005", "MJS450-A", "MJS", "450", 450, 80),
    ("M0006", "MJS450-B", "MJS", "450", 450, 80),
    ("M0007", "SLM600", "SLM", "600", 600, 120),
]

# 工艺参数（material 表）
MATERIAL = [("SLA", 50, 1), ("MJS", 25, 3), ("SLM", 15, 12)]

# system_config 种子（M4b T4b.1）：产能/前道/路由三类。
# INSERT IGNORE 写入（uk_system_config 幂等，不覆盖运维已改值；不在 SEED_TABLES 清空列表）。
SYSTEM_CONFIG_ROWS = [
    ("产能", "t_window_h", "24", "h", "T 窗口（满负荷判断窗口，需求规格 §8）"),
    ("前道", "workers", "6", "人", "前道人池（3 班×2 人）"),
    ("前道", "shifts", "3", "班", "班次"),
    ("前道", "shift_hours", "8", "h", "每班时长"),
    ("前道", "changeover_min", "30", "min", "换班无产出时长"),
    ("前道", "per_part_eff_sla_mjs", "15", "件/人·h", "SLA/MJS 件人效"),
    ("前道", "per_part_eff_slm", "6", "件/人·h", "SLM 件人效"),
    ("前道", "per_part_eff_mix", "12", "件/人·h", "综合件人效（按件活动折算）"),
    ("前道", "plan_review_hours", "0.5", "h/方案", "方案审核分摊"),
    # 默认空策略 = 不按任务类型分流，全类型走 PRIMARY_PROVIDER 主备链（主→备 fallback）。
    # 需要按任务类型分流时，用 /config PUT 配置 {"simple": "…", "complex": "…"}。
    ("路由", "routing_policy", "{}", "json", "B3 模型路由策略（空=走主备链；需分流时 /config 配置）"),
    # 预测类（M5a T5a.2）：rq §3.19 用户 2026-08-23 确认口径
    ("预测", "forecast_method", "exponential", "ma|exponential", "预测方法（默认指数平滑）"),
    ("预测", "forecast_window", "5", "天", "预测窗口（用户确认 5 天）"),
    ("预测", "large_order_amount", "50000", "元", "大单判定阈值（承诺期提示预测校准）"),
    ("预测", "smoothing_alpha", "0.3", "-", "指数平滑系数 α"),
]

# 库存 10 种（沿用 inventory.csv 口径：id/名称/材料名/库存量/单位/安全库存/采购周期天/单价）
INVENTORY = [
    ("MAT001", "AlSi10Mg铝合金粉末", "铝合金粉末", 120, "kg", 50, 7, 380),
    ("MAT002", "316L不锈钢粉末", "不锈钢粉末", 80, "kg", 30, 5, 420),
    ("MAT003", "TC4钛合金粉末", "钛合金粉末", 25, "kg", 20, 14, 2800),
    ("MAT004", "PA12尼龙粉末", "尼龙粉末", 200, "kg", 60, 3, 180),
    ("MAT005", "ABS树脂", "ABS", 150, "kg", 40, 2, 65),
    ("MAT006", "6061铝合金板材", "铝合金板", 35, "块", 20, 10, 850),
    ("MAT007", "45#钢棒料", "钢材", 60, "根", 30, 5, 120),
    ("MAT008", "铜电极", "铜材", 15, "根", 10, 7, 350),
    ("MAT009", "PEEK高性能塑料", "特种塑料", 8, "kg", 10, 21, 3200),
    ("MAT010", "碳纤维预浸料", "碳纤维", 12, "卷", 8, 15, 1800),
]

# — 尺寸/重量范围已迁移到 simulator/constants.py —

ORDER_COUNT = 40  # 30-50 内


def _connect() -> pymysql.connections.Connection:
    """返回 pymysql 裸连接（批量 DML 用，不走连接池，支持 MULTI_STATEMENTS）。"""
    return create_raw_connection(multi_statements=True)


def _clear(conn: pymysql.connections.Connection) -> None:
    """清空业务表（先禁 FK，再逐表 TRUNCATE）。"""
    with conn.cursor() as cur:
        cur.execute("SET FOREIGN_KEY_CHECKS=0")
        for t in SEED_TABLES:
            cur.execute(f"TRUNCATE TABLE `{t}`")
        cur.execute("SET FOREIGN_KEY_CHECKS=1")
    conn.commit()


def _seed_customers(cur) -> None:
    cur.executemany(
        "INSERT INTO customer (id, name, level, credit_score, discount_rate, industry, penalty_rate, tenant_id) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        [(cid, name, lv, cs, dr, ind, pr, "default") for cid, name, lv, cs, dr, ind, pr in CUSTOMERS],
    )


def _seed_machines(cur) -> None:
    cur.executemany(
        "INSERT INTO machines (id, name, process, model_type, cabin_size, max_weight, status, current_batch_id, tenant_id) "
        "VALUES (%s,%s,%s,%s,%s,%s,'空闲',NULL,%s)",
        [(mid, name, p, mt, cs, mw, "default") for mid, name, p, mt, cs, mw in MACHINES],
    )


def _seed_material(cur) -> None:
    cur.executemany(
        "INSERT INTO material (process, rate_mm_h, post_process_hours) VALUES (%s,%s,%s)", MATERIAL
    )


def _seed_inventory(cur) -> None:
    cur.executemany(
        "INSERT INTO inventory (id, 名称, 材料名, 库存量, 单位, 安全库存, 采购周期天, 单价, tenant_id) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        [(iid, name, mat, qty, unit, safe, lead, price, "default")
         for iid, name, mat, qty, unit, safe, lead, price in INVENTORY],
    )


def seed_personnel(cur) -> None:
    """预置 6 名前道工人（对应原"前道工人池"，改具体人员）。幂等：存在即跳过。"""
    cur.execute("SELECT COUNT(*) FROM personnel")
    if cur.fetchone()[0] > 0:
        return
    rows = [
        ("P001", "张伟", "前道工人"), ("P002", "李强", "前道工人"),
        ("P003", "王芳", "前道工人"), ("P004", "刘洋", "前道工人"),
        ("P005", "陈静", "前道工人"), ("P006", "赵磊", "前道工人"),
    ]
    for pid, name, role in rows:
        cur.execute("INSERT INTO personnel (id, name, role) VALUES (%s, %s, %s)",
                    (pid, name, role))


def _seed_system_config(cur) -> None:
    """写 system_config 种子（INSERT IGNORE：缺行才插，保运维已改值）。"""
    cur.executemany(
        "INSERT IGNORE INTO system_config (category, `key`, value, unit, description) "
        "VALUES (%s,%s,%s,%s,%s)",
        SYSTEM_CONFIG_ROWS,
    )


def _seed_orders(cur) -> None:
    """生成 40 订单：amount/urgent/priority/order_date/due_date/status=待排队。

    order_date 分布在 sim 起始日（9/1）前 30 天内 -- 保证有"历史"供预测聚合，
    且 order_date < due_date（due = 9/1 起 7~30 天）。
    """
    start = date(2026, 9, 1)
    rows = []
    for i in range(1, ORDER_COUNT + 1):
        cid, name, lv, *_ = CUSTOMERS[(i - 1) % len(CUSTOMERS)]
        amount = round(random.uniform(5000, 800000), 2)
        urgent = 1 if i % 7 == 0 else 0  # 每 7 单 1 单加急
        priority = calc_priority(lv, bool(urgent), amount)
        ordered = start - timedelta(days=random.randint(1, 30))
        due = start + timedelta(days=random.randint(7, 30))
        rows.append((f"ORD{i:03d}", cid, amount, urgent, priority, ordered, due, "待排队", "default"))
    cur.executemany(
        "INSERT INTO orders (id, customer_id, amount, urgent, priority, order_date, due_date, status, tenant_id) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        rows,
    )


def _seed_parts(cur) -> None:
    """每订单 5-12 个 part，包络盒三边/件重；注入 ≥1 超尺寸样例（某边>600）。"""
    part_no = 0
    for i in range(1, ORDER_COUNT + 1):
        n = random.randint(5, 12)
        for _ in range(n):
            part_no += 1
            material = random.choice(["SLA", "MJS", "SLM"])
            lo, hi = PART_DIM_RANGE[material]
            length = round(random.uniform(lo, hi), 2)
            width = round(random.uniform(lo, hi), 2)
            height = round(random.uniform(lo, hi), 2)
            weight = round(random.uniform(*PART_WEIGHT_RANGE[material]), 2)
            # 超尺寸样例：第 1 个 part 注入 length>600（M2 预警验收）
            if part_no == 1:
                length, width, height = 650.00, 200.00, 150.00
            cur.execute(
                "INSERT INTO parts (id, order_id, product_id, name, quantity, material, length, width, height, weight, tenant_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (f"PART{part_no:05d}", f"ORD{i:03d}", f"P-{i:03d}-{part_no % 100:02d}",
                 f"{material}-零件-{part_no % 100:02d}", random.randint(1, 5), material,
                 length, width, height, weight, "default"),
            )


def seed(conn: pymysql.connections.Connection | None = None) -> dict:
    """插入全部种子数据（不清理；幂等由 reset() 保证）。返回统计。"""
    random.seed(42)  # 重置随机状态 → 每次执行数据一致（幂等）
    own = conn is None
    c = conn or _connect()
    try:
        with c.cursor() as cur:
            _seed_customers(cur)
            _seed_machines(cur)
            _seed_material(cur)
            _seed_inventory(cur)
            _seed_orders(cur)
            _seed_parts(cur)
            seed_personnel(cur)
            _seed_system_config(cur)
        c.commit()
        with c.cursor() as cur:
            stats = {}
            for t in SEED_TABLES:
                cur.execute(f"SELECT COUNT(*) FROM `{t}`")
                stats[t] = cur.fetchone()[0]
        return stats
    finally:
        if own:
            c.close()


def reset(conn: pymysql.connections.Connection | None = None) -> dict:
    """幂等重建：确保表存在（migrate.up）→ 清空 → 插入。"""
    migrate.up()
    own = conn is None
    c = conn or _connect()
    try:
        _clear(c)
        return seed(c)
    finally:
        if own:
            c.close()


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="demo 业务库种子生成器（M1 T1.3）")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--reset", action="store_true", help="幂等重建（先清后插）")
    g.add_argument("--seed", action="store_true", help="插入种子（不清理，需先 --reset 或已空表）")
    args = p.parse_args(argv)

    if args.reset:
        stats = reset()
        print("seed --reset 完成，各表计数：", stats)
    elif args.seed:
        stats = seed()
        print("seed 完成，各表计数：", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
