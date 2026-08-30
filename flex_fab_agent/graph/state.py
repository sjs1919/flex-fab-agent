"""AgentState -- LangGraph 贯穿所有节点的共享状态。

类比 Vuex/Redux 的 store，区别是 LangGraph 用 TypedDict，非响应式。
每个节点接收 state、返回 state（修改后返回）。

R3 缺陷修复（2026-08-07）：新增 evaluation_notes / needs_retry / needs_more / ready_for_answer /
  compression_count / compressed_summary 字段，支持步骤校验和上下文压缩。
"""
from typing import Any, TypedDict


class AgentState(TypedDict):
    messages: list[dict[str, Any]]       # 对话历史（system + user + assistant + tool）
    tool_results: list[dict[str, Any]]   # 工具调用结果汇总
    iteration: int                       # 当前迭代次数，防死循环（上限 5）
    final_answer: str                    # 最终输出
    # R3 新增：步骤校验字段
    evaluation_notes: str                # evaluate_results 的检查记录
    needs_retry: bool                    # 工具执行失败，需要重试
    needs_more: bool                     # 数据不够，需要继续查
    ready_for_answer: bool               # 数据充足，可以生成答案
    # R4 新增：上下文压缩字段
    compression_count: int               # 已压缩次数
    compressed_summary: str              # 最新摘要文本
    # R9 新增（2026-08-30）：待办写操作（approve_schedule / run_scheduling）。
    # evaluate 识别到排产/审批意图但写工具未执行时设置，select_and_execute 每轮注入
    # 执行指令，写工具执行后由 evaluate 清空。必须在 schema 声明——LangGraph 会丢弃
    # 未声明 key，导致 pending_write 从未真正传递（trace 83e162c3 根因）。
    pending_write: str                   # 待执行的写工具名，空串 = 无待办
