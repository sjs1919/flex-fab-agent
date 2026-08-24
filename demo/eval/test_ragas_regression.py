"""ragas_regression 纯函数测试（M5a T5a.15⑦；LLM 调用路径不入 mock 零成本回归）。"""
from demo.eval.ragas_regression import (
    BASELINE,
    GROUND_TRUTH,
    average_precision,
    _reviewer_perms,
)


def test_average_precision_all_relevant_first():
    """相关片段全排前面 -> AP=1。"""
    assert average_precision([True, True, False]) == 1.0


def test_average_precision_ordering_penalty():
    """相关片段排后面 -> AP 低于排前面（排序惩罚）。"""
    first = average_precision([True, False, False])
    last = average_precision([False, False, True])
    assert first == 1.0
    assert last < 1.0
    assert first > last


def test_average_precision_no_relevant():
    """无相关片段 -> 0（不除零）。"""
    assert average_precision([False, False]) == 0.0
    assert average_precision([]) == 0.0


def test_ground_truth_matches_baseline_eval():
    """Q1-Q5 共 5 题（与基线评测同题集）。"""
    assert len(GROUND_TRUTH) == 5
    assert [g["id"] for g in GROUND_TRUTH] == ["Q1", "Q2", "Q3", "Q4", "Q5"]
    assert set(BASELINE) == {"context_precision", "faithfulness",
                             "answer_relevancy", "context_recall"}


def test_reviewer_perms_include_confidential():
    """Q2/Q4 保密文档检索需 reviewer 权限集（confidential+public）。"""
    assert _reviewer_perms() == {"public", "confidential"}
