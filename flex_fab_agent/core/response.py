"""统一 API 响应格式。

所有端点返回 ApiResponse（成功走 ok()，失败走 fail()），前端
按统一字段解析，不用每个端点猜结构。

响应格式：
{
    "code": 0,           // 0 = 成功，非 0 = 错误码
    "message": "ok",     // 成功消息或错误描述
    "data": {...},       // 业务数据
    "trace_id": "..."    // 全链路 trace_id（中间件注入，响应头也有）
}
"""
from __future__ import annotations

from typing import Any


def _trace_id() -> str:
    """懒导入 request_context，避免 core 反向依赖 observability。"""
    from ..observability.request_context import get_trace_id
    return get_trace_id()


def ok(data: Any = None, message: str = "ok") -> dict[str, Any]:
    """成功响应。"""
    return {
        "code": 0,
        "message": message,
        "data": data,
        "trace_id": _trace_id(),
    }


def fail(message: str, code: int = 1, data: Any = None) -> dict[str, Any]:
    """失败响应。"""
    return {
        "code": code,
        "message": message,
        "data": data,
        "trace_id": _trace_id(),
    }
