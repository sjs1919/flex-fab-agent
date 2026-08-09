"""runner 三层聚合测试（mock 单 Agent，不发起真实 LLM 调用）。"""
import pytest

from demo.eval.runner import _evaluate_single_case


def _fake_trace_with_tool_calls():
    """构造含 tool 调用的 trace summary。"""
    return {
        "spans": [
            {"name": "tool:query_orders", "ms": 50, "attrs": {"tool_success": True, "tool_retries": 0}},
        ],
        "total_ms": 50,
        "span_count": 1,
        "by_kind": {"tool": 1},
    }


def test_evaluate_single_case_three_layers(monkeypatch):
    """单个 case 应产出三层指标：tool + trajectory + semantic。"""
    from demo.eval import runner as runner_mod

    # mock run_single_agent 返回固定 state
    def fake_run_single_agent(query, **kwargs):
        return {
            "final_answer": "ORD003 今天优先排产，深圳精密订单紧急",
            "tool_results": [
                {"tool": "query_orders", "arguments": {"status": "紧急"}, "result": "ORD003 深圳精密"},
            ],
        }

    monkeypatch.setattr(runner_mod, "run_single_agent", fake_run_single_agent)
    # mock tracer / cost
    class FakeTracer:
        trace_id = "test-trace"
        def reset(self): pass
        def get_summary(self): return _fake_trace_with_tool_calls()
        def flush(self): pass
    class FakeCost:
        def reset(self): pass
        def get_summary(self): return {"total_tokens": 0, "total_cost": 0}
    monkeypatch.setattr(runner_mod, "tracer", FakeTracer())
    monkeypatch.setattr(runner_mod, "cost_tracker", FakeCost())

    # mock judge 打分
    monkeypatch.setattr(runner_mod, "judge_semantic_quality",
                        lambda q, c, a: {"faithfulness": 0.9, "answer_relevancy": 0.8})

    case = {
        "id": "eval_test",
        "scenario": "测试",
        "query": "今天先做哪些订单？",
        "expected_tools": ["query_orders"],
        "expected_order_ids": ["ORD003"],
        "checks": {"must_contain": ["ORD003"], "min_tools_called": 1},
    }
    result = _evaluate_single_case(case, mode="single")
    assert "trajectory" in result
    assert result["trajectory"]["trajectory_score"] is not None
    assert "semantic" in result
    assert result["semantic"]["faithfulness"] == 0.9
    assert "tool" in result
    assert result["overall_score"] is not None


def test_evaluate_single_case_judge_skippable(monkeypatch):
    """use_judge=False 时跳过 judge 打分（不调用 judge_semantic_quality）。"""
    from demo.eval import runner as runner_mod

    def fake_run_single_agent(query, **kwargs):
        return {
            "final_answer": "ORD003 优先",
            "tool_results": [
                {"tool": "query_orders", "arguments": {}, "result": "ORD003"},
            ],
        }

    monkeypatch.setattr(runner_mod, "run_single_agent", fake_run_single_agent)

    class FakeTracer:
        trace_id = "t2"
        def reset(self): pass
        def get_summary(self): return _fake_trace_with_tool_calls()
        def flush(self): pass
    class FakeCost:
        def reset(self): pass
        def get_summary(self): return {"total_tokens": 0, "total_cost": 0}
    monkeypatch.setattr(runner_mod, "tracer", FakeTracer())
    monkeypatch.setattr(runner_mod, "cost_tracker", FakeCost())

    def judge_should_not_be_called(q, c, a):
        raise AssertionError("use_judge=False 不应调用 judge")
    monkeypatch.setattr(runner_mod, "judge_semantic_quality", judge_should_not_be_called)

    case = {
        "id": "eval_test2", "scenario": "测试2", "query": "q",
        "expected_tools": ["query_orders"],
        "checks": {"min_tools_called": 1},
    }
    result = _evaluate_single_case(case, mode="single", use_judge=False)
    assert result["semantic"] == {"faithfulness": 0.0, "answer_relevancy": 0.0,
                                  "faithfulness_evaluated": False, "has_context": False}


def test_evaluate_single_case_no_context_uses_only_relevancy(monkeypatch):
    """无 context 的 case：语义分只用 answer_relevancy，不用 faithfulness 拖累。

    验证聚合逻辑：has_context=False 时 semantic_score = relevancy（而非 (0+rel)/2）。
    """
    from demo.eval import runner as runner_mod

    def fake_run_single_agent(query, **kwargs):
        return {
            "final_answer": "东莞模具厂订单总体良好，信用78分",
            "tool_results": [
                {"tool": "query_customer", "arguments": {}, "result": "东莞模具 C002 信用78"},
            ],
        }

    monkeypatch.setattr(runner_mod, "run_single_agent", fake_run_single_agent)

    class FakeTracer:
        trace_id = "t3"
        def reset(self): pass
        def get_summary(self): return _fake_trace_with_tool_calls()
        def flush(self): pass
    class FakeCost:
        def reset(self): pass
        def get_summary(self): return {"total_tokens": 0, "total_cost": 0}
    monkeypatch.setattr(runner_mod, "tracer", FakeTracer())
    monkeypatch.setattr(runner_mod, "cost_tracker", FakeCost())

    # 无 context：faithfulness 未评估，relevancy 0.8
    monkeypatch.setattr(runner_mod, "judge_semantic_quality",
                        lambda q, c, a: {"faithfulness": 0.0, "faithfulness_evaluated": False,
                                         "answer_relevancy": 0.8, "has_context": False})

    case = {
        "id": "eval_nc", "scenario": "无context", "query": "东莞客户信用？",
        "expected_tools": ["query_customer"],
        "checks": {"must_contain": ["东莞"], "min_tools_called": 1},
    }
    result = _evaluate_single_case(case, mode="single", use_judge=True)
    # 无 context：语义分只用 relevancy（0.8），而非 (0+0.8)/2 = 0.4
    assert result["semantic"]["answer_relevancy"] == 0.8
    assert result["semantic"]["faithfulness_evaluated"] is False
    assert result["semantic"]["has_context"] is False
    # 聚合验证：overall 的语义贡献 = 0.8*0.2（而非 0.4*0.2）
    # 工具层/轨迹层固定，反推语义贡献
    tool_contrib = result["tool"]["overall_score"] * 0.5
    traj_contrib = result["trajectory"]["trajectory_score"] * 0.3
    sem_contrib = result["overall_score"] - tool_contrib - traj_contrib
    assert abs(sem_contrib - 0.8 * 0.2) < 1e-6, f"语义贡献应为 0.16，实际 {sem_contrib}"


def test_print_summary_layer_health(monkeypatch, capsys):
    """print_summary 输出分层健康度：工具/轨迹/语义各设阈值，语义层仅统计有 context case。"""
    from demo.eval import runner as runner_mod

    results = [
        {"pass": True, "overall_score": 0.7,
         "tool": {"overall_score": 0.8},
         "trajectory": {"trajectory_score": 0.7},
         "semantic": {"has_context": True, "faithfulness": 0.8, "answer_relevancy": 0.9},
         "token_usage": {"total_cost": 0.1}, "elapsed_s": 1.0},
        {"pass": True, "overall_score": 0.7,
         "tool": {"overall_score": 0.7},
         "trajectory": {"trajectory_score": 0.7},
         "semantic": {"has_context": False, "faithfulness": 0.0, "answer_relevancy": 0.6},
         "token_usage": {"total_cost": 0.1}, "elapsed_s": 1.0},
    ]
    summary = runner_mod.print_summary(results)
    captured = capsys.readouterr().out
    # 分层健康度输出
    assert "分层健康度" in captured
    assert "工具层" in captured
    assert "轨迹层" in captured
    assert "语义层" in captured
    # 语义层只统计有 context 的 case（1 个）
    assert summary["layer_health"]["semantic"]["n_context"] == 1
    # 综合门禁仍在
    assert summary["passed"] == 2
