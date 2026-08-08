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
    assert result["semantic"] == {"faithfulness": 0.0, "answer_relevancy": 0.0}
