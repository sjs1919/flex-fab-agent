"""端到端验收测试：mock 全链路（不发真实 LLM 调用），验证三层评估完整性。

对照验收标准：
  A. 工具层：min_tools_called 生效，回归基线可达
  B. 轨迹层：重建 trajectory + 路径效率/重试/循环指标产出
  C. 语义层：LLM-as-Judge 打分（mock）落位
  D. 报告层：HTML 报告生成，包含三层列
"""
import json

from demo.eval.runner import _evaluate_single_case, run_eval
from demo.eval.trajectory import compute_trajectory_score
from demo.eval.trajectory_capture import rebuild_trajectory
from demo.eval.report import render_html_report, save_report
from demo.eval.metrics import compute_all_metrics


def test_e2e_metric_chain_tool_trajectory_semantic(monkeypatch):
    """完整指标链：工具层 -> 轨迹层 -> 语义层 -> 报告，mock 链路端到端。"""
    # ---- mock Agent 运行 + tracer + cost + judge ----
    from demo.eval import runner as runner_mod

    def fake_run_single_agent(query, **kwargs):
        return {
            "final_answer": "ORD003 今天优先排产，深圳精密订单紧急，PEEK 库存充足",
            "tool_results": [
                {"tool": "query_orders", "arguments": {"sort_by": "priority", "limit": 5},
                 "result": "ORD003 深圳精密 紧急"},
                {"tool": "query_inventory", "arguments": {"material_name": "PEEK"},
                 "result": "PEEK 库存 120kg"},
                {"tool": "search_knowledge_base", "arguments": {"query": "深圳精密 排产"},
                 "result": "【片段1】(来源:contracts.md) 深圳精密订单需优先排产，交期紧张"},
            ],
        }

    monkeypatch.setattr(runner_mod, "run_single_agent", fake_run_single_agent)

    class FakeTracer:
        trace_id = "e2e-trace"
        def reset(self): pass
        def get_summary(self):
            return {
                "spans": [
                    {"name": "tool:query_orders", "ms": 50, "attrs": {"tool_success": True, "tool_retries": 0}},
                    {"name": "tool:query_inventory", "ms": 40, "attrs": {"tool_success": True, "tool_retries": 1}},
                    {"name": "tool:search_knowledge_base", "ms": 60, "attrs": {"tool_success": True, "tool_retries": 0}},
                ],
                "total_ms": 150, "span_count": 3, "by_kind": {"tool": 3},
            }
        def flush(self): pass
    class FakeCost:
        def reset(self): pass
        def get_summary(self): return {"total_tokens": 500, "total_cost": 0.01}
    monkeypatch.setattr(runner_mod, "tracer", FakeTracer())
    monkeypatch.setattr(runner_mod, "cost_tracker", FakeCost())
    monkeypatch.setattr(runner_mod, "judge_semantic_quality",
                        lambda q, c, a: {"faithfulness": 0.85, "answer_relevancy": 0.9})

    case = {
        "id": "eval_e2e", "scenario": "端到端", "query": "今天先做哪些订单？",
        "expected_tools": ["query_orders", "query_inventory", "search_knowledge_base"],
        "expected_order_ids": ["ORD003"],
        "checks": {"must_contain": ["ORD003"], "min_tools_called": 2},
    }

    result = _evaluate_single_case(case, mode="single", use_judge=True)

    # A. 工具层：min_tools_called 生效
    assert result["tool"]["min_tools_called"] == 2
    assert result["tool"]["overall_score"] > 0.6

    # B. 轨迹层：rebuilt + 指标
    assert result["trajectory"]["total_tool_calls"] == 3
    assert result["trajectory"]["trajectory_score"] is not None
    assert result["trajectory"]["loop_detected"] is False

    # C. 语义层：judge 打分落位
    assert result["semantic"]["faithfulness"] == 0.85
    assert result["semantic"]["answer_relevancy"] == 0.9

    # D. 报告层：HTML 包含三层列
    html = render_html_report([result], {"avg_tool": 0.8, "avg_traj": 0.7, "avg_sem": 0.8})
    assert "eval_e2e" in html
    assert "轨迹层" in html
    assert "语义层" in html
    assert "工具层" in html


def test_e2e_run_eval_multiple_cases(monkeypatch, tmp_path):
    """run_eval 跑多个 case，汇总通过/失败。"""
    from demo.eval import runner as runner_mod

    def fake_run_single_agent(query, **kwargs):
        return {
            "final_answer": f"处理 {query} 完成，ORD003 优先",
            "tool_results": [
                {"tool": "query_orders", "arguments": {}, "result": "ORD003 深圳精密"},
            ],
        }

    monkeypatch.setattr(runner_mod, "run_single_agent", fake_run_single_agent)
    monkeypatch.setattr(runner_mod, "judge_semantic_quality",
                        lambda q, c, a: {"faithfulness": 0.8, "answer_relevancy": 0.8})

    class FakeTracer:
        trace_id = "e2e-multi"
        def reset(self): pass
        def get_summary(self):
            return {
                "spans": [
                    {"name": "tool:query_orders", "ms": 50, "attrs": {"tool_success": True, "tool_retries": 0}},
                ],
                "total_ms": 50, "span_count": 1, "by_kind": {"tool": 1},
            }
        def flush(self): pass
    class FakeCost:
        def reset(self): pass
        def get_summary(self): return {"total_tokens": 0, "total_cost": 0}
    monkeypatch.setattr(runner_mod, "tracer", FakeTracer())
    monkeypatch.setattr(runner_mod, "cost_tracker", FakeCost())

    # 用临时 ground_truth
    gt_path = tmp_path / "ground_truth.json"
    gt_path.write_text(json.dumps({"cases": [
        {"id": "c1", "scenario": "s1", "query": "q1",
         "expected_tools": ["query_orders"], "checks": {"min_tools_called": 1}},
        {"id": "c2", "scenario": "s2", "query": "q2",
         "expected_tools": ["query_orders"], "checks": {"min_tools_called": 5}},  # 必失败
    ]}), encoding="utf-8")
    monkeypatch.setattr(runner_mod, "GROUND_TRUTH_PATH", gt_path)

    results = run_eval(mode="single", use_judge=False)
    assert len(results) == 2
    # c1：min_tools_called=1 满足，工具调用 F1=1.0
    assert results[0]["tool"]["tool_call_accuracy"] == 1.0
    # c2：min_tools_called=5 未满足 -> 工具调用 F1 被置 0
    assert results[1]["tool"]["tool_call_accuracy"] == 0.0
    assert results[1]["tool"]["min_tools_called"] == 5
