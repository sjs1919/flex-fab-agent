"""从 tracer span + Agent state 重建结构化 trajectory。

数据来源：
  - tracer.get_summary()["spans"]：tool: 前缀的 span，含 name/server/tool_success/tool_retries 属性
  - Agent 返回的 state["tool_results"]：{tool, arguments, result} 列表，含完整参数与结果

设计要点：
  - trajectory 是"有序的工具调用序列"，含每次调用的参数、是否成功、重试次数。
  - 从 tracer 拿顺序和耗时（span 时序），从 state 拿参数和结果。
  - runner 在真实 Agent 跑完后调用本模块重建 trajectory，交给 trajectory.py 打分。
"""
from collections import Counter


def rebuild_trajectory(trace_summary: dict, tool_results: list[dict]) -> dict:
    """从 trace + state 重建结构化 trajectory。

    Args:
        trace_summary: tracer.get_summary() 的返回
        tool_results: Agent state 的 tool_results 列表

    Returns:
        {
            "calls": [
                {"tool": str, "arguments": dict, "result_preview": str,
                 "duration_ms": float, "success": bool, "retries": int, "order": int}
            ],
            "total_tool_calls": int,
            "distinct_tools": int,
            "loop_detected": bool,   # 是否检测到循环
            "errors": int,           # 失败的调用数
        }
    """
    # 从 trace 的 tool: spans 提取（保持时序）
    span_by_order = []
    for sp in trace_summary.get("spans", []):
        name = sp.get("name", "")
        if name.startswith("tool:"):
            span_by_order.append(sp)

    # 从 tool_results 按工具名匹配参数（同一个工具可能被调多次，按出现顺序匹配）
    result_index = 0
    calls = []
    for order, sp in enumerate(span_by_order, 1):
        tool = sp["name"].replace("tool:", "")
        attrs = sp.get("attrs", {})
        # 找到匹配的 tool_results（按顺序消费）
        args = {}
        result_preview = ""
        while result_index < len(tool_results):
            tr = tool_results[result_index]
            if tr.get("tool") == tool:
                args = tr.get("arguments", {})
                result_preview = (tr.get("result", "") or "")[:120].replace("\n", " ")
                result_index += 1
                break
            result_index += 1

        calls.append({
            "tool": tool,
            "arguments": args,
            "result_preview": result_preview,
            "duration_ms": sp.get("ms", 0),
            "success": bool(attrs.get("tool_success", True)),
            "retries": int(attrs.get("tool_retries", 0)),
            "order": order,
        })

    # 循环检测：同一工具调用 >=3 次视为可疑循环
    tool_counts = Counter(c["tool"] for c in calls)
    loop_detected = any(cnt >= 3 for cnt in tool_counts.values())

    return {
        "calls": calls,
        "total_tool_calls": len(calls),
        "distinct_tools": len({c["tool"] for c in calls}),
        "loop_detected": loop_detected,
        "errors": sum(1 for c in calls if not c["success"]),
    }
