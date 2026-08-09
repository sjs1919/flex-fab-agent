"""HTML 报告生成测试。"""
import pytest

from demo.eval.report import render_html_report, save_report, _semantic_score


def _sample_results():
    return [
        {
            "case_id": "eval_001", "scenario": "排产优先级", "query": "今天先做哪些订单？",
            "overall_score": 0.85, "pass": True,
            "tool": {"overall_score": 0.9},
            "trajectory": {"trajectory_score": 0.8, "loop_detected": False},
            "semantic": {"faithfulness": 0.9, "answer_relevancy": 0.8,
                         "has_context": True, "faithfulness_evaluated": True},
            "elapsed_s": 3.2, "answer_preview": "ORD003 今天优先排产",
        },
        {
            "case_id": "eval_002", "scenario": "紧急订单", "query": "有哪些紧急订单？",
            "overall_score": 0.45, "pass": False,
            "tool": {"overall_score": 0.5},
            "trajectory": {"trajectory_score": 0.3, "loop_detected": True},
            "semantic": {"faithfulness": 0.4, "answer_relevancy": 0.6,
                         "has_context": False, "faithfulness_evaluated": False},
            "elapsed_s": 5.1, "answer_preview": "暂无紧急订单",
        },
    ]


def test_render_html_report_contains_pass_fail():
    html = render_html_report(_sample_results(), {"avg_tool": 0.7, "avg_traj": 0.55, "avg_sem": 0.7})
    assert "eval_001" in html
    assert "eval_002" in html
    assert "综合评分" in html


def test_render_html_report_has_trajectory_column():
    html = render_html_report(_sample_results())
    assert "轨迹层" in html
    assert "🔴" in html  # eval_002 loop_detected 标记
    assert "✅" in html  # eval_001 无循环标记


def test_render_html_report_has_three_layers():
    html = render_html_report(_sample_results())
    assert "工具层" in html
    assert "轨迹层" in html
    assert "语义层" in html


def test_render_html_report_marks_failed_case():
    html = render_html_report(_sample_results())
    assert 'class="fail"' in html  # eval_002 失败应有 fail 样式


def test_render_html_report_empty_results():
    html = render_html_report([])
    assert "暂无数据" in html


def test_save_report_writes_file(tmp_path):
    path = save_report(_sample_results(), None, str(tmp_path / "report.html"))
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "eval_001" in content


def test_semantic_score_adaptive():
    """语义分自适应：有 context 用两指标均值，无 context 只用 relevancy（与 runner 一致）。"""
    # 有 context： (0.9+0.8)/2 = 0.85
    assert _semantic_score({"has_context": True, "faithfulness": 0.9, "answer_relevancy": 0.8}) == pytest.approx(0.85)
    # 无 context：只用 relevancy = 0.6（不用 faithfulness 0.4 拖低）
    assert _semantic_score({"has_context": False, "faithfulness": 0.4, "answer_relevancy": 0.6}) == pytest.approx(0.6)


def test_render_html_report_adaptive_semantic_column():
    """报告语义列按 has_context 自适应：eval_002（无 context）显示 relevancy 而非两指标均值。"""
    html = render_html_report(_sample_results())
    # eval_002 无 context：语义列 = 0.60（relevancy），而非 (0.4+0.6)/2 = 0.50
    assert "0.60" in html
