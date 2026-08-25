"""请求级上下文 -- trace_id 等请求维度的状态，用 contextvars 隔离。

为什么用 contextvars 而不是全局变量：
  - 全局 tracer 单例非线程安全（tracer.py 注释明确说明）
  - API 并发请求时，所有请求共享同一个 tracer，span 会串扰
  - contextvars 是 Python 标准库，线程/协程安全，每个请求有独立的上下文
  - 模拟器线程也能有自己的 trace_id，不与 API 请求串

使用方式：
  from .request_context import get_trace_id, set_trace_id, new_trace_id

  # 请求入口（中间件）
  trace_id = new_trace_id()

  # 下游任何地方
  trace_id = get_trace_id()

注意：
  - 不在请求上下文内调用 get_trace_id() 会自动生成一个（lazy 模式）
  - tracer / audit_logger / cost_tracker 都从这里取 trace_id，保证一致
"""
from __future__ import annotations

import contextvars
import uuid

# 请求级 trace_id（16 位 hex，与 tracer 原格式一致）
_request_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_trace_id", default=""
)


def get_trace_id() -> str:
    """获取当前请求的 trace_id。上下文中没有则自动生成一个（lazy）。"""
    tid = _request_trace_id.get()
    if not tid:
        tid = uuid.uuid4().hex[:16]
        _request_trace_id.set(tid)
    return tid


def set_trace_id(trace_id: str) -> contextvars.Token:
    """设置当前请求的 trace_id（请求入口处调用）。返回 token 用于 reset。"""
    return _request_trace_id.set(trace_id)


def new_trace_id() -> str:
    """生成并设置新的 trace_id，返回它。用于每轮请求开始时。"""
    tid = uuid.uuid4().hex[:16]
    _request_trace_id.set(tid)
    return tid


def reset_trace_id(token: contextvars.Token) -> None:
    """重置 trace_id 到之前的状态（配合 set_trace_id 使用）。"""
    _request_trace_id.reset(token)
