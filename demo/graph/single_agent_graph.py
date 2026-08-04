"""单 Agent 的 LangGraph 状态图。

流程：
  analyze_intent -> select_and_execute -> evaluate_results
       ↑                                       │
       └──────── needs_more_data ──────────────┘
                                               │
                                          generate_answer -> END

对比 week4 多 Agent：单 Agent 一个节点做"查订单+查资源+综合判断"，
多 Agent 拆成 Supervisor + 审核 + 生产各司其职。

关键改动（vs 原 week3 langgraph_agent）：
  - 工具来源：原硬编码 TOOLS dict -> ToolRegistry（O(1) 查找 + 参数白名单）
  - LLM 调用：原本地 call_llm -> core.llm_client.call_llm（统一主备）
  - 节点通过闭包绑定 registry，build_single_agent_graph(registry) 工厂构造
"""
import json
from typing import Any

from langgraph.graph import END, StateGraph

from ..core.llm_client import call_llm
from ..graph.state import AgentState
from ..tools.registry import ToolRegistry


def build_single_agent_graph(registry: ToolRegistry, checkpointer=None):
    """构建单 Agent 状态图。registry 决定 Agent 可用哪些工具。"""

    tools_schema = registry.get_tool_defs()

    def analyze_intent(state: AgentState) -> AgentState:
        """分析用户意图（当前打印日志；生产可扩展为意图分类器路由）。"""
        user_msg = next((m["content"] for m in reversed(state["messages"]) if m["role"] == "user"), "")
        print(f"\n{'=' * 60}\n 用户提问：{user_msg}\n{'=' * 60}")
        return state

    def select_and_execute(state: AgentState) -> AgentState:
        """Agent 核心决策 + 执行：LLM 决策调哪些工具 -> 执行 -> 注入结果。"""
        response = call_llm(state["messages"], tools_schema)
        msg = response.choices[0].message

        # LLM 未调工具 -> 直接返回文本
        if not msg.tool_calls:
            state["messages"].append({"role": "assistant", "content": msg.content or ""})
            return state

        # 执行每个 tool_call
        for tc in msg.tool_calls:
            tool_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            schema = registry.get_schema(tool_name)
            server = schema.server if schema else "?"
            print(f" -> [{server}] {tool_name}({args})")

            result = registry.execute(tool_name, args)
            preview = result[:120].replace("\n", " ")
            print(f"   结果：{preview}...")
            state["tool_results"].append({"tool": tool_name, "arguments": args, "result": result})

        # 注入 assistant 消息（含 tool_calls 元数据）
        state["messages"].append({
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ],
        })
        # 逐个注入 tool 消息（含执行结果）
        for tc in msg.tool_calls:
            matching = [r for r in state["tool_results"] if r["tool"] == tc.function.name]
            result_text = matching[-1]["result"] if matching else ""
            state["messages"].append({"role": "tool", "tool_call_id": tc.id, "content": result_text})

        state["iteration"] += 1
        return state

    def evaluate_results(state: AgentState) -> AgentState:
        """评估数据是否足够（当前 noop，由 should_continue 条件边决定）。"""
        return state

    def should_continue(state: AgentState) -> str:
        """条件边：判断是否继续调工具。

        三种情况：① 迭代≥5 强制结束（防死循环）；② 末条是 tool 结果 -> 继续；
                  ③ 末条是 assistant 文本（无 tool_calls）-> 生成最终答案。
        """
        if state["iteration"] >= 5:
            return "generate_answer"
        last_msg = state["messages"][-1] if state["messages"] else {}
        if last_msg.get("role") == "tool":
            return "select_and_execute"
        if last_msg.get("role") == "assistant" and last_msg.get("tool_calls"):
            return "select_and_execute"
        return "generate_answer"

    def generate_answer(state: AgentState) -> AgentState:
        """综合所有数据生成最终调度建议。"""
        last_msg = state["messages"][-1] if state["messages"] else {}
        # 上一条已是最终回复 -> 直接复用
        if last_msg.get("role") == "assistant" and last_msg.get("content") and not last_msg.get("tool_calls"):
            state["final_answer"] = last_msg["content"]
            return state

        # 追加综合指令让 LLM 汇总
        summary_prompt = {
            "role": "system",
            "content": ("请基于以上所有工具查询结果，给出综合调度建议。\n"
                        "必须包含：\n1. 关键发现（交期/客户/库存/设备）\n"
                        "2. 今日优先排产订单（按优先级排序，列出订单号和原因）\n"
                        "3. 可以延后的订单及原因\n用中文回答，格式清晰。"),
        }
        try:
            response = call_llm(state["messages"] + [summary_prompt])
            answer = response.choices[0].message.content or ""
        except Exception as e:
            # 兜底：LLM 失败时返回原始工具数据
            answer = f"调度建议生成失败：{e}\n\n已收集的工具数据：\n"
            for tr in state["tool_results"]:
                answer += f"\n--- {tr['tool']} ---\n{tr['result'][:300]}"
        state["final_answer"] = answer
        state["messages"].append({"role": "assistant", "content": answer})
        return state

    # ---- 组装状态图 ----
    graph = StateGraph(AgentState)
    graph.add_node("analyze_intent", analyze_intent)
    graph.add_node("select_and_execute", select_and_execute)
    graph.add_node("evaluate_results", evaluate_results)
    graph.add_node("generate_answer", generate_answer)
    graph.set_entry_point("analyze_intent")
    graph.add_edge("analyze_intent", "select_and_execute")
    graph.add_edge("select_and_execute", "evaluate_results")
    graph.add_conditional_edges("evaluate_results", should_continue, {
        "select_and_execute": "select_and_execute",
        "generate_answer": "generate_answer",
    })
    graph.add_edge("generate_answer", END)
    return graph.compile(checkpointer=checkpointer)
