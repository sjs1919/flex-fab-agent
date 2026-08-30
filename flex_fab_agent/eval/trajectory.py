"""轨迹评估指标 -- 路径效率 + 重试分析 + 循环检测。

设计要点：
  - 这是行业 2026 强调的 trajectory evaluation，不只看最终答案，看路径。
  - 指标全部可解释：面试时能讲清"为什么这个路径低分"。
"""
from collections import Counter


def path_efficiency(trajectory: dict) -> float:
    """路径效率（0-1）：冗余调用越少越高。

    计算：1 - (冗余调用数 / 总调用数)。冗余 = 同一工具反复调用。
    简化启发式：同一工具出现 >=2 次，多出来的每次扣 0.2。
    """
    calls = trajectory.get("calls", [])
    if not calls:
        return 0.0
    tool_counts = Counter(c["tool"] for c in calls)
    redundant = sum(max(0, cnt - 1) for cnt in tool_counts.values())
    if redundant == 0:
        return 1.0
    return max(0.0, 1.0 - 0.2 * redundant)


def retry_quality(trajectory: dict) -> float:
    """重试质量（0-1）：重试越少越高，失败越少越高。

    设计：全部调用失败直接清零；否则每次重试扣 0.2、每次失败额外扣 0.3，
    结果 clamp 到 [0,1]。完美无重试无失败 = 1.0。
    """
    calls = trajectory.get("calls", [])
    if not calls:
        return 0.0
    if all(not c.get("success", True) for c in calls):
        return 0.0
    total_retries = sum(c.get("retries", 0) for c in calls)
    total_errors = sum(1 for c in calls if not c.get("success", True))
    score = 1.0 - 0.2 * total_retries - 0.3 * total_errors
    return max(0.0, min(1.0, score))


def loop_detection_penalty(trajectory: dict) -> float:
    """循环扣分：检测到循环直接给 0。"""
    if trajectory.get("loop_detected"):
        return 0.0
    return 1.0


def compute_trajectory_score(trajectory: dict) -> dict:
    """聚合轨迹指标。"""
    return {
        "path_efficiency": round(path_efficiency(trajectory), 3),
        "retry_quality": round(retry_quality(trajectory), 3),
        "loop_score": round(loop_detection_penalty(trajectory), 3),
        "total_tool_calls": trajectory.get("total_tool_calls", 0),
        "distinct_tools": trajectory.get("distinct_tools", 0),
        "loop_detected": trajectory.get("loop_detected", False),
        "errors": trajectory.get("errors", 0),
        "trajectory_score": round(
            (path_efficiency(trajectory) * 0.4
             + retry_quality(trajectory) * 0.4
             + loop_detection_penalty(trajectory) * 0.2), 3
        ),
    }
