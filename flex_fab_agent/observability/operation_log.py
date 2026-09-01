"""统一操作日志（四类来源）落库 + 查询 + 请求分类。

写方：
  - HTTP 手工/调试：api.py trace_id_middleware 响应完成后 BackgroundTask 落库
    （走 classify_request 分流，保证 trace_id 一致、不阻塞响应）
  - 后台线程：auto_scheduler / simulator runner 关键动作点显式调用
查询：GET /logs 走 query_operations（real_time DESC 分页）。
旁路设计：落库失败只告警不抛出，不拖垮主链路（参考 runner._record_kpi_snapshot）。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from ..tools.data import get_connection, transaction

logger = logging.getLogger(__name__)

# ---- HTTP 请求分类（middleware 用） ----

_HTTP_DEBUG_PREFIX = "/debug/"
_HTTP_MANUAL_PREFIXES = ("/schedule/", "/sim/", "/config", "/resources/", "/ask", "/threads/")

# 不落库路径（静态资源 / 健康检查 / 日志自身 / 令牌签发）
_EXCLUDE_PREFIXES = ("/assets/", "/health", "/logs", "/debug/admin-token")

# path 前缀 -> 语义动作名（第一个命中的生效；未命中用 "METHOD path" 兜底）
_ACTION_PREFIXES: list[tuple[str, str]] = [
    ("/schedule/load", "手动排产加载"),
    ("/schedule/approve", "排产审批"),
    ("/schedule/latest", "查看排产版本"),
    ("/schedule/versions", "查看版本列表"),
    ("/schedule/", "排产查询"),
    ("/sim/start", "模拟器启动"),
    ("/sim/stop", "模拟器停止"),
    ("/sim/status", "模拟器状态"),
    ("/config", "配置操作"),
    ("/resources/", "资源操作"),
    ("/ask", "智能问答"),
    ("/threads/", "会话历史"),
    ("/debug/rerun", "调试重跑"),
    ("/debug/judge", "调试判定"),
    ("/debug/cases", "调试用例"),
    ("/debug/trace", "调试trace"),
    ("/debug/stats", "调试统计"),
    ("/debug/", "调试操作"),
]


def classify_request(method: str, path: str) -> tuple[str, str] | None:
    """HTTP 请求分类为 (category, action)。不记录时返回 None。

    - /debug/* -> debug；其余手工端点 -> manual；未命中返回 None
    - 排除静态资源 / 健康检查 / 日志自身 / admin-token
    """
    if not path or path == "/":
        return None
    if path.startswith(_EXCLUDE_PREFIXES):
        return None
    if path.startswith(_HTTP_DEBUG_PREFIX):
        category = "debug"
    elif path.startswith(_HTTP_MANUAL_PREFIXES):
        category = "manual"
    else:
        return None
    for prefix, action in _ACTION_PREFIXES:
        if path.startswith(prefix):
            return category, action
    return category, f"{method} {path}"


# ---- 写入 ----

def record_operation(category: str, action: str, status: str = "ok",
                     summary: str = "", detail: dict | None = None,
                     sim_time: datetime | None = None,
                     trace_id: str | None = None,
                     relate_id: str | None = None) -> int:
    """写一条操作日志。落库失败只告警不抛出（旁路）。返回日志 id，失败返回 0。"""
    try:
        payload = json.dumps(detail, ensure_ascii=False, default=str) if detail else None
        with transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO operation_log (category, action, status, summary, "
                    "detail_json, sim_time, trace_id, relate_id) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (category, action, status, summary, payload,
                     sim_time, trace_id, relate_id))
                return cur.lastrowid
    except Exception:
        logger.warning("操作日志落库失败（旁路忽略）: %s/%s", category, action, exc_info=True)
        return 0


# ---- 查询 ----

def query_operations(category: str | None = None,
                     start: str | None = None, end: str | None = None,
                     keyword: str | None = None,
                     page: int = 1, page_size: int = 20) -> dict:
    """分页查询操作日志，real_time DESC。返回 {total, page, page_size, items}。

    keyword 模糊匹配 action / summary / trace_id；start/end 过滤 real_time 区间；
    参数全可空。演示项目不做 keyword 通配符转义（LIKE % 拼接）。
    """
    # 钳制分页参数，防 page<=0 / page_size<=0 时 OFFSET/LIMIT 为负触发 MySQL 语法错误
    page = max(page, 1)
    page_size = max(page_size, 1)
    where: list[str] = []
    params: list[Any] = []
    if category:
        where.append("category = %s")
        params.append(category)
    if start:
        where.append("real_time >= %s")
        params.append(start)
    if end:
        where.append("real_time <= %s")
        params.append(end)
    if keyword:
        where.append("(action LIKE %s OR summary LIKE %s OR trace_id LIKE %s)")
        params += [f"%{keyword}%"] * 3
    cond = ("WHERE " + " AND ".join(where)) if where else ""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM operation_log {cond}", params)
            total = cur.fetchone()[0]
            cur.execute(
                f"SELECT id, category, action, status, summary, detail_json, "
                f"sim_time, real_time, trace_id, relate_id "
                f"FROM operation_log {cond} "
                f"ORDER BY real_time DESC, id DESC LIMIT %s OFFSET %s",
                params + [page_size, (page - 1) * page_size])
            cols = [d[0] for d in cur.description]
            items = [dict(zip(cols, row)) for row in cur.fetchall()]
    return {"total": total, "page": page, "page_size": page_size, "items": items}
