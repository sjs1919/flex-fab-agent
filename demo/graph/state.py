"""AgentState -- LangGraph 贯穿所有节点的共享状态。

类比 Vuex/Redux 的 store，区别是 LangGraph 用 TypedDict，非响应式。
每个节点接收 state、返回 state（修改后返回）。
"""
from typing import Any, TypedDict


class AgentState(TypedDict):
    messages: list[dict[str, Any]]   # 对话历史（system + user + assistant + tool）
    tool_results: list[dict[str, Any]]  # 工具调用结果汇总
    iteration: int                   # 当前迭代次数，防死循环
    final_answer: str                # 最终输出
