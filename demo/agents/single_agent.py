"""单 Agent -- week3 的 LangGraph 调度 Agent（工程化版）。

一个 Agent 同时做"查订单 + 查资源 + 综合判断"，适合简单查询。
复杂排产用 Supervisor 多 Agent 模式（见 supervisor.py）。
"""
from ..graph.single_agent_graph import build_single_agent_graph
from ..prompts.system_prompts import SINGLE_AGENT_PROMPT
from ..tools.registry import build_default_registry
from ..graph.state import AgentState


def run_single_agent(query: str, registry=None) -> dict:
    """运行单 Agent 处理一次查询，返回最终 state。

    registry 可传入（多 Agent 共享同一注册表时）；默认构建含 6 工具的注册表。
    """
    registry = registry or build_default_registry()
    app = build_single_agent_graph(registry)

    initial_state: AgentState = {
        "messages": [
            {"role": "system", "content": SINGLE_AGENT_PROMPT},
            {"role": "user", "content": query},
        ],
        "tool_results": [],
        "iteration": 0,
        "final_answer": "",
    }
    result = app.invoke(initial_state)

    print(f"\n{'=' * 60}\n 最终调度建议\n{'=' * 60}")
    print(result["final_answer"])
    print(f"\n工具调用统计：{len(result['tool_results'])} 次")
    for tr in result["tool_results"]:
        schema = registry.get_schema(tr["tool"])
        server = schema.server if schema else "?"
        print(f"  [{server}] {tr['tool']}({tr['arguments']})")
    return result
