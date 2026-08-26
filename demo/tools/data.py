"""统一数据层 -- 为工具提供数据加载接口。

数据层与工具层分离：工具只管暴露能力，数据来源（CSV/DB）集中管理。
生产环境把 CSV 换成数据库，工具接口不变。
类比 Java 的 DAO 层，上层 Service 不关心数据来自哪里。

数据文件在 demo/data/：
  orders.csv    订单（15 条）
  inventory.csv 材料库存（10 种）
  machines.csv  设备（8 台）
  customers.csv 客户（5 个，含等级/信用/延期率/折扣率/行业）

R8 缺陷修复（2026-08-07）：load_* 函数支持 tenant_id 过滤。
  默认 tenant_id="" 返回全部数据（向后兼容）。
"""
import csv
import logging
import urllib.parse
from contextlib import contextmanager
from typing import Any, Iterator

from dbutils.pooled_db import PooledDB
import pymysql

from ..config import DATA_DIR, get_data_source, get_mysql_dsn

logger = logging.getLogger(__name__)

# ---- M1 T2.1 连接池（R-D3 核心）----
# 池为模块级单例，三并发入口（模拟器线程 / API / agent 工具）共用。
# 业务代码统一走 get_connection()，禁止裸 pymysql.connect。
_pool: PooledDB | None = None


def _get_pool() -> PooledDB:
    global _pool
    if _pool is None:
        parsed = urllib.parse.urlparse(get_mysql_dsn().replace("mysql+pymysql://", "mysql://"))
        _pool = PooledDB(
            creator=pymysql,
            mincached=5,
            maxcached=10,
            maxconnections=30,
            blocking=True,
            reset=True,  # 归还前 rollback 未提交事务，避免半开事务污染
            host=parsed.hostname,
            port=parsed.port or 3306,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path.lstrip("/"),
            charset="utf8mb4",
        )
    return _pool


def get_connection() -> pymysql.connections.Connection:
    """从连接池取一个连接。用完必须 close() 归还到池。"""
    return _get_pool().connection()


def create_raw_connection(multi_statements: bool = False) -> pymysql.connections.Connection:
    """创建 pymysql 裸连接（不走连接池），供 DDL / 批量 DML 运维脚本使用。

    复用连接池相同的 DSN 解析逻辑（urlparse），比正则更可靠。

    Args:
        multi_statements: 是否启用 CLIENT.MULTI_STATEMENTS flag（批量 SQL 脚本需要）
    """
    parsed = urllib.parse.urlparse(get_mysql_dsn().replace("mysql+pymysql://", "mysql://"))
    client_flag = 0
    if multi_statements:
        client_flag |= pymysql.constants.CLIENT.MULTI_STATEMENTS
    return pymysql.connect(
        host=parsed.hostname,
        port=parsed.port or 3306,
        user=parsed.username,
        password=parsed.password,
        database=parsed.path.lstrip("/"),
        charset="utf8mb4",
        client_flag=client_flag,
    )


@contextmanager
def transaction() -> Iterator[pymysql.connections.Connection]:
    """事务原子提交 contextmanager（R-D3，模拟器 tick 多写基础）。

    用法：
        with transaction() as conn:
            # 多写（批次→设备→状态日志）
        正常退出自动 commit；异常 rollback 后向上抛（无半写）。
    """
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _read_rows(query: str, params: tuple = (), filename: str = "") -> list[dict]:
    """按数据源分流读取行（v2 A1 核心）。

    - mysql：参数化查询（防 SQL 注入），返回 list[dict]，key=列名
    - csv：`_read_csv(filename)` 兜底；mysql 缺连接串/不可用时自动降级 csv
      并打 warning（验收清单第 1 条：缺连接串时提示 + 降级）。
    """
    if get_data_source() == "mysql":
        try:
            conn = get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    cols = [d[0] for d in cur.description] if cur.description else []
                    return [dict(zip(cols, row)) for row in cur.fetchall()]
            finally:
                conn.close()
        except (RuntimeError, pymysql.err.Error) as e:
            logger.warning("MySQL 数据源不可用（%s），自动降级 csv 兜底", e)
            return _read_csv(filename) if filename else []
    return _read_csv(filename) if filename else []


def _read_csv(filename: str) -> list[dict[str, str]]:
    """通用 CSV 读取。返回 list[dict]，每行一个 dict，key 是列名。"""
    path = DATA_DIR / filename
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _with_tenant(table: str, tenant_id: str) -> tuple[str, tuple]:
    """拼查询：tenant_id 非空时加 WHERE tenant_id=%s（R8 在 SQL 层过滤）。"""
    query, params = f"SELECT * FROM {table}", ()
    if tenant_id:
        query += " WHERE tenant_id=%s"
        params = (tenant_id,)
    return query, params


def _row_filter(rows: list[dict], tenant_id: str) -> list[dict]:
    """csv 兜底/无 tenant 列的 R8 行级过滤；tenant_id 为空全量返回。"""
    if not tenant_id:
        return rows
    return [r for r in rows if r.get("tenant_id", "") == tenant_id]


# M6 联调修复：orders.csv 仍是 M1 T3.1 前的旧列名/旧状态枚举。
# 数据层归一为 schema 键（status/due_date）+ 新枚举，csv 与 mysql 语义一致；
# 不迁移数据文件（补列=双维护，与 T6.1 machines.csv 处理同款）。
_ORDERS_CSV_ALIAS = {"交期": "due_date", "状态": "status"}
_ORDERS_CSV_STATUS = {
    "生产中": "打印中",   # 在产
    "即将完成": "打印中",  # 在产（收尾）
    "紧急": "打印中",      # 质检/收尾在产
    "排期中": "待排队",    # 排队等待排产
    "待排产": "待排队",    # 排队等待排产
    "排队": "待排队",      # LLM/用户口吻词
    "排队中": "待排队",    # LLM/用户口吻词
    "排产中": "待排队",    # LLM/用户口吻词
    "打印完成": "完成",    # LLM/用户口吻词
    "已完成": "完成",      # LLM/用户口吻词
}


def normalize_order_status(status: str) -> str:
    """订单状态宽容归一：旧枚举/口吻词 -> 新枚举（待排队/已审核/打印中/完成）。

    load_orders（csv 行）与 query_orders（LLM status 实参）共用：
    LLM 常按用户口吻传旧词（排期中/待排产/排队），归一后再过滤避免空结果。
    未知值原样返回。"""
    return _ORDERS_CSV_STATUS.get(status, status)


def _normalize_orders_row(row: dict[str, str]) -> dict[str, str]:
    out = dict(row)
    for src, dst in _ORDERS_CSV_ALIAS.items():
        if src in out and dst not in out:
            out[dst] = out[src]
    st = out.get("status")
    if st:
        out["status"] = normalize_order_status(st)
    return out


def load_orders(tenant_id: str = "") -> list[dict[str, str]]:
    """加载订单数据。签名不变（v2 A1：上层零改动）。"""
    query, params = _with_tenant("orders", tenant_id)
    rows = [_normalize_orders_row(r) for r in _read_rows(query, params, filename="orders.csv")]
    return _row_filter(rows, tenant_id)


def load_inventory(tenant_id: str = "") -> list[dict[str, str]]:
    """加载库存数据。"""
    query, params = _with_tenant("inventory", tenant_id)
    return _row_filter(_read_rows(query, params, filename="inventory.csv"), tenant_id)


def load_machines(tenant_id: str = "") -> list[dict[str, str]]:
    """加载设备数据。"""
    query, params = _with_tenant("machines", tenant_id)
    return _row_filter(_read_rows(query, params, filename="machines.csv"), tenant_id)


def load_customers(tenant_id: str = "") -> list[dict[str, str]]:
    """加载客户数据。"""
    query, params = _with_tenant("customer", tenant_id)
    return _row_filter(_read_rows(query, params, filename="customers.csv"), tenant_id)


def load_parts(tenant_id: str = "") -> list[dict[str, str]]:
    """加载零件数据（M1 新增）。"""
    query, params = _with_tenant("parts", tenant_id)
    return _row_filter(_read_rows(query, params, filename=""), tenant_id)


def load_batches(tenant_id: str = "") -> list[dict[str, str]]:
    """加载批次数据（M1 新增；本轮 solver 未产出，空表返回 []）。

    注：batches 等求解输出表无 tenant_id 列，参数保留仅为对齐 load_* 签名，
    R8 租户隔离对这类表无列可过滤（v2 §4.2 所有权由 solver 保证）。
    """
    return _read_rows("SELECT * FROM batches", (), filename="")


def load_personnel(tenant_id: str = "") -> list[dict[str, str]]:
    """加载人员（personnel 无 tenant_id，参数保留对齐签名）。"""
    return _read_rows("SELECT * FROM personnel", (), filename="")


def load_config(tenant_id: str = "") -> list[dict[str, str]]:
    """加载系统配置（M1 新增；本轮未灌数据，空表返回 []）。

    注：system_config 无 tenant_id 列（全局配置），参数保留仅为对齐 load_* 签名。
    """
    return _read_rows("SELECT * FROM system_config", (), filename="")


def load_preprocess_tasks(tenant_id: str = "") -> list[dict[str, str]]:
    """加载前道任务（M1 新增；本轮空表返回 []）。

    注：preprocess_tasks 无 tenant_id 列，参数保留仅为对齐 load_* 签名。
    """
    return _read_rows("SELECT * FROM preprocess_tasks", (), filename="")


def load_bad_parts(tenant_id: str = "") -> list[dict[str, str]]:
    """加载坏件记录（M5a 新增，query_yield 良率根因分析数据源）。"""
    query, params = _with_tenant("bad_parts", tenant_id)
    return _row_filter(_read_rows(query, params, filename=""), tenant_id)


def format_table(rows: list[dict], columns: list[str] | None = None) -> str:
    """将 dict 列表格式化为 Markdown 表格，方便 LLM 阅读。

    为什么用 Markdown：LLM 训练数据含大量 Markdown，解析效果好；比 JSON 省 token。
    """
    if not rows:
        return "（无数据）"
    cols = columns or list(rows[0].keys())
    header = "| " + " | ".join(cols) + " |"
    sep = "|" + "|".join(["---" for _ in cols]) + "|"
    lines = [header, sep]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(c, "")) for c in cols) + " |")
    return "\n".join(lines)


def filter_by(rows: list[dict], **kwargs: Any) -> list[dict]:
    """多条件 AND 过滤。值为 None/空字符串的 key 自动跳过。"""
    result = rows
    for key, val in kwargs.items():
        if val is not None and val != "":
            result = [r for r in result if str(r.get(key, "")).strip() == str(val).strip()]
    return result
