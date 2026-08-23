"""migrate.py 幂等迁移测试（M1 T1.2 + M5a T5a.1，需 WSL MySQL 可用）。

覆盖：up-up 幂等、down-up 可重建（DBA 红线：有回滚路径）、
v2 增量（orders.order_date 列 + bad_parts 表）、v2 幂等重跑。
测试直接操作 demo_scheduling 库（运维脚本，与业务连接池隔离）。
"""
import demo.schema.migrate as m


def _tables():
    conn = m._connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW TABLES")
            return sorted(r[0] for r in cur.fetchall())
    finally:
        conn.close()


def _versions():
    conn = m._connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT version FROM schema_version")
            return sorted(r[0] for r in cur.fetchall())
    finally:
        conn.close()


def _column_exists(table: str, column: str) -> bool:
    conn = m._connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SHOW COLUMNS FROM `{table}` LIKE '{column}'")
            return cur.fetchone() is not None
    finally:
        conn.close()


def test_migrate_up_up_idempotent():
    """连跑两次 up：第二次 no-op 不报错，schema_version 记录全部已应用版本。"""
    m.up()          # 第一次：建表 + 记录版本
    changed = m.up()  # 第二次：应 no-op
    assert changed is False
    assert _versions() == list(range(1, m.CURRENT_VERSION + 1))
    tables = _tables()
    assert "orders" in tables and "machines" in tables and "batches" in tables


def test_migrate_down_up_rebuild():
    """down 回滚（业务表消失）后 up 可重建。"""
    m.up()
    m.down()
    assert "orders" not in _tables()   # 业务表已回滚
    assert _versions() == []           # 版本记录已清
    m.up()                              # 重建
    assert _versions() == list(range(1, m.CURRENT_VERSION + 1))
    tables = _tables()
    assert "orders" in tables and "machines" in tables and "sim_clock" in tables


def test_migrate_v2_order_date_and_bad_parts():
    """v2 增量：orders 有 order_date 列、bad_parts 表存在；列存在时重跑不报错（幂等）。"""
    m.up()
    assert _column_exists("orders", "order_date")
    tables = _tables()
    assert "bad_parts" in tables
    assert _column_exists("bad_parts", "machine_id")
    assert _column_exists("bad_parts", "material")
    assert _column_exists("bad_parts", "related_event_id")
    assert m.up() is False  # 幂等


def test_bad_parts_insert_query_roundtrip():
    """bad_parts 插入/查询按根因维度走通（rollback 清理不留测试数据）。"""
    m.up()
    conn = m._connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO bad_parts (batch_id, machine_id, material, part_count, sim_time) "
                "VALUES ('B00001', 'M00001', 'SLA', 2, '2026-08-23 10:00:00')")
            cur.execute(
                "SELECT batch_id, machine_id, material, part_count FROM bad_parts "
                "WHERE machine_id = %s AND material = %s", ("M00001", "SLA"))
            row = cur.fetchone()
        conn.rollback()
        assert row == ("B00001", "M00001", "SLA", 2)
    finally:
        conn.close()


def test_migrate_v2_down_up():
    """v2 回滚路径：down（v2 先回滚 bad_parts/order_date，再 v1 全清）后 up 恢复。"""
    m.up()
    m.down()
    tables = _tables()
    assert "bad_parts" not in tables
    assert "orders" not in tables  # 全回滚到 0（v2 down 已执行不报错）
    m.up()
    assert _column_exists("orders", "order_date")
    assert "bad_parts" in _tables()
