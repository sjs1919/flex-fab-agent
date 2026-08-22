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
import re
import sys
from datetime import date, timedelta

import pymysql

from demo.config import get_mysql_dsn
from demo.schema import migrate

# 固定种子 → 幂等（两次执行数据一致）
random.seed(42)

# 业务表（seed 管理的表；schedule_versions/batches 等由 solver 管，不清）
SEED_TABLES = ["customer", "orders", "parts", "machines", "material", "inventory"]

# 客户：沿用现有 customers.csv 口径 + penalty_rate（v1 §3.17：S=0.01/A=0.005/B=C=0.003）
CUSTOMERS = [
    ("C001", "深圳精密五金", "A", 92, 0.85, "消费电子", 0.005),
    ("C002", "东莞模具厂", "B", 78, 0.92, "汽车模具", 0.003),
    ("C003", "广州航天精工", "S", 98, 0.80, "航空航天", 0.010),
    ("C004", "惠州医疗器械", "C", 65, 0.95, "医疗器械", 0.003),
    ("C005", "佛山智能家居", "B", 82, 0.90, "智能家居", 0.003),
]
LEVEL_SCORE = {"S": 50, "A": 40, "B": 25, "C": 10}

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

# 每材料 part 尺寸范围（包络盒 mm，长边 ≤550 保证可装舱；超尺寸样例单独注入）
PART_DIM_RANGE = {"SLA": (80, 400), "MJS": (150, 500), "SLM": (50, 300)}
PART_WEIGHT_RANGE = {"SLA": (0.5, 8), "MJS": (2, 25), "SLM": (1, 30)}
ORDER_COUNT = 40  # 30-50 内


def _connect() -> pymysql.connections.Connection:
    """解析 config 合成的 DSN，返回 pymysql 连接（autocommit=False）。"""
    m = re.match(r"mysql\+pymysql://([^:]+):([^@]*)@([^:]+):(\d+)/([^?]+)", get_mysql_dsn())
    if not m:
        raise RuntimeError("MYSQL_DSN 解析失败，请检查 config.get_mysql_dsn()")
    user, pw, host, port, db = m.groups()
    return pymysql.connect(
        host=host, port=int(port), user=user, password=pw, database=db,
        client_flag=pymysql.constants.CLIENT.MULTI_STATEMENTS, autocommit=False,
    )


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


def _seed_orders(cur) -> None:
    """生成 40 订单：amount/urgent/priority/due_date/status=待排队。"""
    start = date(2026, 9, 1)
    rows = []
    for i in range(1, ORDER_COUNT + 1):
        cid, name, lv, *_ = CUSTOMERS[(i - 1) % len(CUSTOMERS)]
        amount = round(random.uniform(5000, 800000), 2)
        urgent = 1 if i % 7 == 0 else 0  # 每 7 单 1 单加急
        priority = LEVEL_SCORE[lv] + urgent * 30 + (20 if amount >= 50000 else 0)
        due = start + timedelta(days=random.randint(7, 30))
        rows.append((f"ORD{i:03d}", cid, amount, urgent, priority, due, "待排队", "default"))
    cur.executemany(
        "INSERT INTO orders (id, customer_id, amount, urgent, priority, due_date, status, tenant_id) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
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
