"""LangGraph checkpointer -- 编排层状态持久化（#1/#7）。

把 Agent 运行状态（messages/工具结果/迭代次数）检查点化，支持：
  - 多轮对话：同一 thread_id 跨 invoke 共享历史
  - 中断恢复：长任务崩溃后从最近 checkpoint 续跑
  - 重启不丢：sqlite 落盘，新进程读同一 db 即可恢复

backend 由 CHECKPOINTER 环境变量选：
  sqlite（默认）落盘 demo/data/checkpoints.db，重启可恢复
  memory        进程内存，重启即失（仅演示 checkpoint 概念）
  none          不持久化（等价 week4 无 checkpointer）

为什么不用 add_messages reducer：
  它会把消息转成 LangChain HumanMessage/AIMessage 对象，而本 demo 全链路按 dict
  处理消息并直接喂 OpenAI SDK。改对象类型风险大、收益小，故保持 dict + 覆盖语义，
  多轮时显式从 checkpoint 取历史 messages 追加新问题再 invoke（见 single_agent.py）。
"""
import os
import sqlite3

from langgraph.checkpoint.memory import MemorySaver

_BUILT = False
_CHECKPOINTER = None


def build_checkpointer():
    """构建并持有 checkpointer（模块级单例，sqlite 连接随进程存活）。"""
    global _BUILT, _CHECKPOINTER
    if _BUILT:
        return _CHECKPOINTER
    _BUILT = True

    mode = os.getenv("CHECKPOINTER", "sqlite").lower()
    if mode == "none":
        return None
    if mode == "memory":
        _CHECKPOINTER = MemorySaver()
        return _CHECKPOINTER

    # sqlite 默认：落盘，重启可恢复
    from langgraph.checkpoint.sqlite import SqliteSaver

    from ..config import DATA_DIR

    conn = sqlite3.connect(str(DATA_DIR / "checkpoints.db"), check_same_thread=False)
    _CHECKPOINTER = SqliteSaver(conn)
    return _CHECKPOINTER
