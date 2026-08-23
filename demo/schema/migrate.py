"""幂等迁移器（M1 T1.2）：schema_version 记录版本，up/down 可回滚。

- `up()`：执行 schema.sql 建表 + 记录版本；已是当前版本时 no-op（幂等）。
- `down()`：回滚当前版本（DROP 全部业务表），可回滚路径（DBA 红线）。
- CLI：`python -m demo.schema.migrate --up | --down | --status`。

连接说明：本模块是**运维脚本**（DDL/多语句/关外键检查），直接用 pymysql
连接（解析 config.get_mysql_dsn()），不走业务连接池——migration 工具
执行 DDL 不适合走池（T2.1 R-D3 验收的 grep「业务代码零裸连接」豁免本目录）。
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pymysql

from demo.config import get_mysql_dsn

SCHEMA_SQL = Path(__file__).resolve().parent / "schema.sql"
CURRENT_VERSION = 2

# bad_parts 建表 DDL（v2 增量复用；与 schema.sql 保持一致）
_BAD_PARTS_DDL = """
CREATE TABLE IF NOT EXISTS bad_parts (
    id                BIGINT AUTO_INCREMENT COMMENT '坏件记录 id',
    batch_id          VARCHAR(32)  NOT NULL COMMENT '批次（根因维度）',
    machine_id        CHAR(6)      NOT NULL COMMENT '设备（根因维度）',
    material          ENUM('SLA','MJS','SLM') NOT NULL COMMENT '材料（根因维度）',
    part_count        INT          NOT NULL DEFAULT 1 COMMENT '坏件数',
    related_event_id  INT          DEFAULT NULL COMMENT '关联 sim_events 事件 id（scrap/MTBF 故障）',
    sim_time          DATETIME     NOT NULL COMMENT 'sim 时间',
    tenant_id         VARCHAR(32)  NOT NULL DEFAULT 'default' COMMENT 'R8',
    PRIMARY KEY (id),
    KEY idx_badparts_machine (machine_id),
    KEY idx_badparts_batch (batch_id),
    KEY idx_badparts_material (material)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='坏件记录（所有权：simulator）'
"""


def _column_exists(cur, table: str, column: str) -> bool:
    """列存在检查（MySQL 8 无 ADD/DROP COLUMN IF EXISTS，用 information_schema 判断）。"""
    cur.execute(
        "SELECT 1 FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
        (table, column))
    return cur.fetchone() is not None


def _up_v2(cur) -> None:
    """v2 增量（M5a）：orders.order_date 列（预测聚合维度）+ bad_parts 表（良率闭环）。"""
    if not _column_exists(cur, "orders", "order_date"):
        cur.execute(
            "ALTER TABLE orders ADD COLUMN order_date DATE NOT NULL "
            "DEFAULT '2026-08-01' COMMENT '下单日（预测聚合维度，M5a）' AFTER priority")
    cur.execute(_BAD_PARTS_DDL)


def _down_v2(cur) -> None:
    """v2 回滚：DROP bad_parts + 删 orders.order_date 列。"""
    cur.execute("DROP TABLE IF EXISTS bad_parts")
    if _column_exists(cur, "orders", "order_date"):
        cur.execute("ALTER TABLE orders DROP COLUMN order_date")


_MIGRATIONS = {2: (_up_v2, _down_v2)}


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


def _table_names(sql: str) -> list[str]:
    """从 schema.sql 提取建表表名（down 时 DROP 用）。"""
    return re.findall(r"CREATE TABLE IF NOT EXISTS\s+(\w+)", sql)


def up(conn: pymysql.connections.Connection | None = None) -> bool:
    """应用迁移（幂等，逐版本推进）。返回是否发生了变更（False = 已是最新 no-op）。

    v1 = 基线（整跑 schema.sql 建全量表）；v2+ = 增量 DDL（_MIGRATIONS 注册）。
    """
    own = conn is None
    c = conn or _connect()
    try:
        with c.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS schema_version "
                "(version INT PRIMARY KEY, applied_at DATETIME NOT NULL)"
            )
            cur.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version")
            applied = cur.fetchone()[0]
            if applied >= CURRENT_VERSION:
                return False
            for version in range(applied + 1, CURRENT_VERSION + 1):
                if version == 1:
                    cur.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
                else:
                    _MIGRATIONS[version][0](cur)
                cur.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (%s, %s)",
                    (version, datetime.now()),
                )
            c.commit()
            return True
    finally:
        if own:
            c.close()


def down(conn: pymysql.connections.Connection | None = None) -> bool:
    """回滚全部已应用版本（逐版本 down 到 0）。返回是否发生了变更。"""
    own = conn is None
    c = conn or _connect()
    try:
        with c.cursor() as cur:
            cur.execute("SET FOREIGN_KEY_CHECKS=0")
            cur.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version")
            applied = cur.fetchone()[0]
            if applied == 0:
                return False
            for version in range(applied, 0, -1):
                if version == 1:
                    for t in _table_names(SCHEMA_SQL.read_text(encoding="utf-8")):
                        cur.execute(f"DROP TABLE IF EXISTS `{t}`")
                else:
                    _MIGRATIONS[version][1](cur)
                cur.execute("DELETE FROM schema_version WHERE version = %s", (version,))
            cur.execute("SET FOREIGN_KEY_CHECKS=1")
            c.commit()
            return True
    finally:
        if own:
            c.close()


def status() -> dict:
    """当前迁移状态：已应用版本 + 业务表数量。"""
    c = _connect()
    try:
        with c.cursor() as cur:
            cur.execute("SELECT version, applied_at FROM schema_version ORDER BY version")
            versions = cur.fetchall()
            cur.execute("SHOW TABLES")
            tables = sorted(r[0] for r in cur.fetchall())
        return {"versions": [{"version": v, "applied_at": a.isoformat()} for v, a in versions],
                "table_count": len(tables), "tables": tables}
    finally:
        c.close()


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="demo_scheduling 数据库迁移器（M1）")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--up", action="store_true", help="应用迁移（幂等，连跑两次第二次 no-op）")
    g.add_argument("--down", action="store_true", help="回滚当前版本（可回滚路径）")
    g.add_argument("--status", action="store_true", help="查看已应用版本与表清单")
    args = p.parse_args(argv)

    if args.up:
        changed = up()
        print("up: 已应用当前版本" if changed else "up: 已是最新（no-op）")
    elif args.down:
        changed = down()
        print("down: 已回滚（业务表已删除）" if changed else "down: 无待回滚版本")
    elif args.status:
        s = status()
        print(f"已应用版本: {[v['version'] for v in s['versions']]}")
        print(f"业务表数量: {s['table_count']} -> {s['tables']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
