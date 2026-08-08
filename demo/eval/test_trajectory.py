"""轨迹评估单元测试。"""
from demo.eval.trajectory import (
    compute_trajectory_score, path_efficiency, retry_quality, loop_detection_penalty,
)
from demo.eval.trajectory_capture import rebuild_trajectory


def _make_trace(spans):
    return {"spans": spans, "total_ms": 0, "span_count": len(spans), "by_kind": {}}


def test_rebuild_trajectory_from_trace():
    """从 trace + state 重建 trajectory：按时序 + 参数匹配。"""
    trace = _make_trace([
        {"name": "tool:query_orders", "ms": 100, "attrs": {"tool_success": True, "tool_retries": 0}},
        {"name": "tool:search_knowledge_base", "ms": 50, "attrs": {"tool_success": True, "tool_retries": 1}},
    ])
    state = [
        {"tool": "query_orders", "arguments": {"status": "紧急"}, "result": "订单数据"},
        {"tool": "search_knowledge_base", "arguments": {"query": "延期"}, "result": "合同条款"},
    ]
    traj = rebuild_trajectory(trace, state)
    assert traj["total_tool_calls"] == 2
    assert traj["calls"][0]["tool"] == "query_orders"
    assert traj["calls"][0]["order"] == 1
    assert traj["calls"][0]["arguments"] == {"status": "紧急"}
    assert traj["calls"][1]["retries"] == 1


def test_rebuild_trajectory_ignores_non_tool_spans():
    """非 tool 前缀 span 应被忽略。"""
    trace = _make_trace([
        {"name": "llm:call", "ms": 100, "attrs": {}},
        {"name": "tool:query_orders", "ms": 50, "attrs": {"tool_success": True, "tool_retries": 0}},
    ])
    traj = rebuild_trajectory(trace, [])
    assert traj["total_tool_calls"] == 1
    assert traj["calls"][0]["tool"] == "query_orders"


def test_rebuild_trajectory_empty():
    """空 trace + 空 state。"""
    traj = rebuild_trajectory(_make_trace([]), [])
    assert traj["total_tool_calls"] == 0
    assert traj["calls"] == []
    assert traj["loop_detected"] is False


def test_rebuild_trajectory_detects_loop():
    """同一工具连续调用 >=3 次视为循环。"""
    spans = [
        {"name": f"tool:query_orders", "ms": 10, "attrs": {"tool_success": True, "tool_retries": 0}}
        for _ in range(4)
    ]
    traj = rebuild_trajectory(_make_trace(spans), [])
    assert traj["loop_detected"] is True


def test_path_efficiency_no_redundancy():
    """无冗余调用 = 1.0。"""
    traj = {"calls": [{"tool": "a"}, {"tool": "b"}]}
    assert path_efficiency(traj) == 1.0


def test_path_efficiency_redundant():
    """同一工具调 3 次 -> 2 次冗余 -> 扣 0.4。"""
    traj = {"calls": [{"tool": "a"}, {"tool": "a"}, {"tool": "a"}]}
    assert path_efficiency(traj) == 0.6


def test_path_efficiency_empty():
    """无调用 = 0。"""
    assert path_efficiency({"calls": []}) == 0.0


def test_retry_quality_perfect():
    """无重试无失败 = 1.0。"""
    traj = {"calls": [{"tool": "a", "retries": 0, "success": True},
                      {"tool": "b", "retries": 0, "success": True}]}
    assert retry_quality(traj) == 1.0


def test_retry_quality_with_retries():
    """有重试会扣分。"""
    traj = {"calls": [{"tool": "a", "retries": 2, "success": True}]}
    score = retry_quality(traj)
    assert 0.0 < score < 1.0


def test_retry_quality_all_failed():
    """全部失败 = 0。"""
    traj = {"calls": [{"tool": "a", "retries": 3, "success": False}]}
    assert retry_quality(traj) == 0.0


def test_loop_detection_penalty_true():
    """检测到循环 = 0。"""
    assert loop_detection_penalty({"loop_detected": True}) == 0.0


def test_loop_detection_penalty_false():
    """无循环 = 1。"""
    assert loop_detection_penalty({"loop_detected": False}) == 1.0


def test_compute_trajectory_score_aggregates():
    """聚合评分 + 原始计数都在返回里。"""
    traj = {
        "calls": [{"tool": "a", "retries": 0, "success": True},
                  {"tool": "b", "retries": 0, "success": True}],
        "total_tool_calls": 2,
        "distinct_tools": 2,
        "loop_detected": False,
        "errors": 0,
    }
    result = compute_trajectory_score(traj)
    assert result["trajectory_score"] == 1.0
    assert result["total_tool_calls"] == 2
    assert result["errors"] == 0
