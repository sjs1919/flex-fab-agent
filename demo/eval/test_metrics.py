"""工具层指标单元测试。"""
from demo.eval.metrics import compute_all_metrics, tool_call_accuracy, answer_completeness


def test_tool_call_accuracy_perfect():
    """工具 F1：完全命中 = 1.0。"""
    assert tool_call_accuracy(["a", "b"], ["a", "b"]) == 1.0


def test_tool_call_accuracy_partial():
    """工具 F1：部分命中 < 1.0。"""
    score = tool_call_accuracy(["a", "b"], ["a", "c"])
    assert 0.0 < score < 1.0


def test_tool_call_accuracy_empty_actual():
    """工具 F1：一个都没调 = 0.0。"""
    assert tool_call_accuracy(["a", "b"], []) == 0.0


def test_answer_completeness_all_match():
    """完整性：所有 must_contain 都出现 = 全通过。"""
    checks = {"must_contain": ["ORD003", "深圳精密"]}
    results = answer_completeness(checks, "ORD003 已排产，深圳精密订单优先")
    assert all(results.values())


def test_answer_completeness_missing_phrase():
    """完整性：有 must_contain 没出现 = 未通过。"""
    checks = {"must_contain": ["ORD003"]}
    results = answer_completeness(checks, "没有 ORD004 的信息")
    assert not all(results.values())


def test_compute_all_metrics_reads_min_tools_called():
    """compute_all_metrics 必须读取 min_tools_called，工具数不足时 tool_call_accuracy 应为 0。"""
    case = {
        "id": "eval_test",
        "scenario": "测试",
        "query": "test",
        "expected_tools": ["a", "b", "c"],
        "checks": {"min_tools_called": 3},
    }
    result = compute_all_metrics(case, "answer", ["a"])  # 只调了 1 个工具
    assert result["tool_call_accuracy"] == 0.0
    assert "min_tools_called" in result


def test_compute_all_metrics_meets_min_tools():
    """min_tools_called 满足时不影响工具分。"""
    case = {
        "id": "eval_test",
        "scenario": "测试",
        "query": "test",
        "expected_tools": ["a", "b"],
        "checks": {"min_tools_called": 2},
    }
    result = compute_all_metrics(case, "answer", ["a", "b"])
    assert result["tool_call_accuracy"] == 1.0
    assert result["min_tools_called"] == 2


def test_compute_all_metrics_order_recall():
    """订单召回：预期订单号出现在答案中。"""
    case = {
        "id": "eval_test",
        "scenario": "测试",
        "query": "test",
        "expected_tools": ["a"],
        "expected_order_ids": ["ORD001", "ORD003"],
        "checks": {},
    }
    result = compute_all_metrics(case, "ORD003 需要优先处理，ORD001 可延后", ["a"])
    assert result["order_accuracy"] == 1.0
