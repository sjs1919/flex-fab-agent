"""统一数据层 -- 为工具提供数据加载接口。

数据层与工具层分离：工具只管暴露能力，数据来源（CSV/DB）集中管理。
生产环境把 CSV 换成数据库，工具接口不变。
类比 Java 的 DAO 层，上层 Service 不关心数据来自哪里。

数据文件在 demo/data/：
  orders.csv    订单（15 条）
  inventory.csv 材料库存（10 种）
  machines.csv  设备（8 台）
  customers.csv 客户（5 个，含等级/信用/延期率/折扣率/行业）
"""
import csv
from typing import Any

from ..config import DATA_DIR


def _read_csv(filename: str) -> list[dict[str, str]]:
    """通用 CSV 读取。返回 list[dict]，每行一个 dict，key 是列名。"""
    path = DATA_DIR / filename
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_orders() -> list[dict[str, str]]:
    """加载订单数据（15 条）。"""
    return _read_csv("orders.csv")


def load_inventory() -> list[dict[str, str]]:
    """加载库存数据（10 种材料）。"""
    return _read_csv("inventory.csv")


def load_machines() -> list[dict[str, str]]:
    """加载设备数据（8 台）。"""
    return _read_csv("machines.csv")


def load_customers() -> list[dict[str, str]]:
    """加载客户数据（5 个）。"""
    return _read_csv("customers.csv")


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
