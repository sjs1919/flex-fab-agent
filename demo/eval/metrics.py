"""评估指标 -- Agent 评估指标实现（R6 缺陷修复）。

指标：
  - tool_call_accuracy: Agent 是否调了正确的工具（F1 score）
  - answer_completeness: 是否包含所有必要信息 + 不包含禁止内容
  - order_accuracy: 预期订单号的召回率
  - overall_score: 加权综合评分
"""
from typing import Any


def tool_call_accuracy(expected_tools: list[str], actual_tools: list[str]) -> float:
    """工具调用准确率（F1 score）。

    召回率：期望的工具中有多少被调了
    精确率：调了的工具有多少是需要的
    """
    if not actual_tools:
        return 0.0
    # 去重后的实际工具名
    actual_set = set(actual_tools)
    expected_set = set(expected_tools)
    if not expected_set:
        return 1.0
    recall = len(actual_set & expected_set) / len(expected_set)
    precision = len(actual_set & expected_set) / len(actual_set)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def answer_completeness(checks: dict, answer: str) -> dict:
    """回答完整性检查。返回各子项的通过情况。"""
    results: dict[str, bool] = {}
    for phrase in checks.get("must_contain", []):
        results[f"包含'{phrase}'"] = phrase in answer
    for phrase in checks.get("must_not_contain", []):
        results[f"不包含'{phrase}'"] = phrase not in answer
    return results


def compute_all_metrics(case: dict, answer: str, actual_tools: list[str]) -> dict:
    """对一个 case 计算所有指标。"""
    checks = case.get("checks", {})
    completeness = answer_completeness(checks, answer)
    completeness_score = sum(completeness.values()) / len(completeness) if completeness else 1.0

    tool_score = tool_call_accuracy(
        case.get("expected_tools", []), actual_tools,
    )

    # 检查是否包含预期订单号
    expected_orders = case.get("expected_order_ids", [])
    if expected_orders:
        order_hit = sum(1 for oid in expected_orders if oid in answer) / len(expected_orders)
    else:
        order_hit = 1.0

    return {
        "case_id": case["id"],
        "scenario": case["scenario"],
        "query": case["query"],
        "answer_preview": answer[:150],
        "tools_called": actual_tools,
        "tool_call_accuracy": round(tool_score, 3),
        "completeness_score": round(completeness_score, 3),
        "completeness_details": completeness,
        "order_accuracy": round(order_hit, 3),
        "overall_score": round((tool_score * 0.3 + completeness_score * 0.5 + order_hit * 0.2), 3),
    }
