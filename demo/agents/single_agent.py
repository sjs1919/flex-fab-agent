"""单 Agent -- week3 的 LangGraph 调度 Agent（工程化版）。

一个 Agent 同时做"查订单 + 查资源 + 综合判断"，适合简单查询。
复杂排产用 Supervisor 多 Agent 模式（见 supervisor.py）。

状态持久化（#1/#7）：
  图编译时接入 checkpointer（默认 sqlite 落盘）。run_single_agent(query, thread_id)
  传同一 thread_id 即多轮对话：从 checkpoint 取历史 messages，追加新问题，每轮重置
  工具状态（tool_results/iteration）。重启进程后用原 thread_id 仍能恢复上下文。
"""
import logging
import uuid

from ..cache.manager import cache_manager
from ..graph.checkpointer import build_checkpointer
from ..graph.single_agent_graph import (
    _GRACEFUL_FALLBACK,
    _looks_like_tool_markup,
    build_single_agent_graph,
)
from ..graph.state import AgentState
from ..observability import tracer
from ..prompts.versioning import load_system_prompt
from ..tools.registry import build_default_registry

logger = logging.getLogger(__name__)

# 模块级缓存编译好的图：多轮复用同一图 + checkpointer（checkpointer 是单例）
_app = None
_app_registry = None


def _get_app(registry):
    """缓存编译好的图（首次构建接 checkpointer；registry 变了才重建）。"""
    global _app, _app_registry
    if _app is None or registry is not _app_registry:
        _app = build_single_agent_graph(registry, checkpointer=build_checkpointer())
        _app_registry = registry
    return _app


def run_single_agent(query: str, registry=None, thread_id: str | None = None) -> dict:
    """运行单 Agent 处理一次查询，返回最终 state。

    registry 可传入（多 Agent 共享同一注册表时）；默认构建含 7 工具的注册表。
    thread_id 传入时为多轮对话：从 checkpoint 恢复历史 messages，追加本次提问，
    每轮重置 tool_results/iteration/final_answer。不传则用临时 thread_id（单次）。

    语义缓存（#6）：仅 thread_id None（无多轮上下文）时启用，避免上下文污染。
    命中则跳过整图执行直接返回缓存答案，trace 记 cache:lookup(result=hit)。
    """
    registry = registry or build_default_registry()

    # 语义缓存：仅无多轮上下文时查（多轮答案依赖前文，不能复用）
    if thread_id is None:
        with tracer.span("cache:lookup") as sp:
            hit = cache_manager.lookup_semantic(query)
        if hit:
            answer, dist = hit
            sp.attributes["result"] = "hit"
            sp.attributes["distance"] = round(dist, 4)
            logger.info("命中语义缓存（cosine 距离 %.4f，跳过 LLM 执行）", dist)
            logger.debug("缓存答案：%s", answer)
            return {"final_answer": answer, "tool_results": []}
        sp.attributes["result"] = "miss"

    app = _get_app(registry)
    tid = thread_id or f"eph-{uuid.uuid4().hex[:12]}"
    config = {"configurable": {"thread_id": tid}}

    if thread_id:
        # 多轮：从 checkpoint 取历史 messages，追加新问题；每轮重置工具状态
        state_tuple = app.get_state(config)
        hist = state_tuple.values.get("messages", []) if state_tuple.values else []
    else:
        hist = []

    if hist:
        initial_state: AgentState = {
            "messages": list(hist) + [{"role": "user", "content": query}],
            "tool_results": [],
            "iteration": 0,
            "final_answer": "",
        }
    else:
        initial_state = {
            "messages": [
                {"role": "system", "content": load_system_prompt()},
                {"role": "user", "content": query},
            ],
            "tool_results": [],
            "iteration": 0,
            "final_answer": "",
        }

    result = app.invoke(initial_state, config)

    logger.debug("最终调度建议：%s", result["final_answer"])
    logger.debug("工具调用统计：%d 次", len(result["tool_results"]))
    for tr in result["tool_results"]:
        schema = registry.get_schema(tr["tool"])
        server = schema.server if schema else "?"
        logger.debug("  [%s] %s(%s)", server, tr["tool"], tr["arguments"])

    # 缓存写入：仅无多轮上下文（首轮独立问题才有复用价值）
    if thread_id is None and result.get("final_answer"):
        # 缓存投毒纵深防御：标记文本（未解析工具调用）与失败兜底文本（生成异常）
        # 均不得写入语义缓存，否则用户重问会一直命中失败答案。
        fa = result["final_answer"]
        if not _looks_like_tool_markup(fa) and fa != _GRACEFUL_FALLBACK:
            cache_manager.store_semantic(query, fa)

    return result
