"""通用工具函数集合。

集中存放各处散落的小工具：JSON 解析、时间格式化、类型转换、参数校验、ID 生成等。
"""
import json
import uuid
from datetime import date, datetime
from typing import Any


# ---- JSON / 列表转换 ----

def json_list(raw: Any) -> list:
    """将 order_ids 字段统一转为 list。

    支持：None → []、list → 原样、JSON 字符串 → 解析后列表、
    逗号分隔字符串 → split 后列表。解析失败返回空列表。
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return []
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass
        return [s.strip() for s in raw.split(",") if s.strip()]
    return []


# ---- 类型转换（安全，带默认值） ----

def to_float(v: Any, default: float = 0.0) -> float:
    """安全转 float，失败返回 default。"""
    if v is None:
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def to_int(v: Any, default: int = 0) -> int:
    """安全转 int，失败返回 default。"""
    if v is None:
        return default
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


def to_bool(v: Any) -> bool:
    """安全转 bool。支持 true/false/1/0/yes/no 等常见形式。"""
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in {"true", "1", "yes", "y", "on"}
    return bool(v)


# ---- 时间格式化 ----

def fmt_dt(value: Any) -> str:
    """datetime/date/None → 标准字符串。
    datetime → '%Y-%m-%d %H:%M'，date → '%Y-%m-%d'，None → ''。
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def fmt_date(value: Any) -> str:
    """date/datetime/None → 日期字符串 '%Y-%m-%d'，None → ''。"""
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    return str(value)


def fmt_money(value: float) -> str:
    """金额统一格式化：¥0.0000（4 位小数）。"""
    return f"¥{value:.4f}"


# ---- 参数校验 ----

def cap_limit(limit: int, max_limit: int = 2000) -> int:
    """limit 参数夹取：最小 1，最大 max_limit。"""
    return min(max(limit, 1), max_limit)


# ---- ID 生成 ----

def gen_id(prefix: str = "", length: int = 12) -> str:
    """生成短 ID（hex 形式）。

    Args:
        prefix: 可选前缀，如 "trace_" / "chat_"
        length: hex 部分长度，默认 12
    """
    suffix = uuid.uuid4().hex[:length]
    return f"{prefix}{suffix}" if prefix else suffix


# ---- 业务常量（跨包共用） ----

CUSTOMER_LEVEL_ORDER: dict[str, int] = {"S": 0, "A": 1, "B": 2, "C": 3}
"""客户等级排序权重，用于按等级排序/过滤。数值越小等级越高。"""
