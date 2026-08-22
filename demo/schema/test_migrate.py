"""migrate.py 幂等迁移测试（M1 T1.2，需 WSL MySQL 可用）。

覆盖：up-up 幂等、down-up 可重建（DBA 红线：有回滚路径）。
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


def test_migrate_up_up_idempotent():
    """连跑两次 up：第二次 no-op 不报错，schema_version 仍单版本。"""
    m.up()          # 第一次：建表 + 记录版本
    changed = m.up()  # 第二次：应 no-op
    assert changed is False
    assert _versions() == [m.CURRENT_VERSION]
    tables = _tables()
    assert "orders" in tables and "machines" in tables and "batches" in tables


def test_migrate_down_up_rebuild():
    """down 回滚（业务表消失）后 up 可重建。"""
    m.up()
    m.down()
    assert "orders" not in _tables()   # 业务表已回滚
    assert _versions() == []           # 版本记录已清
    m.up()                              # 重建
    assert _versions() == [m.CURRENT_VERSION]
    tables = _tables()
    assert "orders" in tables and "machines" in tables and "sim_clock" in tables
