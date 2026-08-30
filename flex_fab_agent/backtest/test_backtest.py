"""回测模块单元测试：场景加载 + 覆盖度评分（纯函数，不调 LLM）。"""
from flex_fab_agent.backtest.scenarios import load_scenarios, score_backtest


def test_load_scenarios_count():
    """应加载 5 个历史复盘场景。"""
    scenarios = load_scenarios()
    assert len(scenarios) == 5


def test_scenario_has_required_fields():
    """每个场景含 query + expected_keypoints。"""
    for s in load_scenarios():
        assert s["query"]
        assert s["expected_keypoints"]
        assert s["id"].startswith("bt_")


def test_scenario_context_no_csv_reference():
    """T5a.13（E3）：场景 context 数据源描述为 MySQL 表口径（data.py 读取），无 CSV 引用。"""
    for s in load_scenarios():
        ctx = s.get("context", "")
        assert "data/" not in ctx, f"{s['id']} context 含 data/ 路径: {ctx}"
        assert ".csv" not in ctx, f"{s['id']} context 含 .csv 引用: {ctx}"


def test_score_full_coverage():
    """答案覆盖全部关键要点 = 1.0。"""
    scenario = {
        "expected_keypoints": ["设备故障", "预防性维护"],
        "must_not": ["不知道"],
    }
    score = score_backtest("应关注设备故障，做好预防性维护", scenario)
    assert score["coverage"] == 1.0
    assert score["hits"] == 2
    assert score["forbidden_hit"] is False


def test_score_partial():
    """覆盖部分要点。"""
    scenario = {"expected_keypoints": ["设备故障", "预防性维护", "备件库存"]}
    score = score_backtest("要预防设备故障", scenario)
    assert score["hits"] == 1
    assert score["coverage"] == round(1 / 3, 3)


def test_score_zero():
    """答案不覆盖任何要点 = 0。"""
    scenario = {"expected_keypoints": ["设备故障", "备件库存"]}
    score = score_backtest("完全无关的回答", scenario)
    assert score["coverage"] == 0.0


def test_score_forbidden_word():
    """触发禁止词标记。"""
    scenario = {"expected_keypoints": ["设备"], "must_not": ["不知道"]}
    score = score_backtest("设备问题我不知道怎么处理", scenario)
    assert score["forbidden_hit"] is True


def test_run_backtest_disables_semantic_cache(monkeypatch):
    """① backtest runner 默认禁用语义缓存（避免陈旧缓存回放污染复盘）。

    测试后须还原 SEMANTIC_CACHE（run_backtest 直接改 os.environ，单进程 pytest
    共享 env，否则污染 test_is_semantic_enabled_default）。
    """
    import os
    from flex_fab_agent.backtest import runner as runner_mod
    orig = os.environ.get("SEMANTIC_CACHE")
    try:
        os.environ.pop("SEMANTIC_CACHE", None)
        monkeypatch.setattr(runner_mod, "load_scenarios", lambda: [])
        runner_mod.run_backtest()
        assert os.environ.get("SEMANTIC_CACHE") == "off", "backtest 必须默认禁语义缓存"
    finally:
        if orig is None:
            os.environ.pop("SEMANTIC_CACHE", None)
        else:
            os.environ["SEMANTIC_CACHE"] = orig


# ---- M6 T6.10：场景源扩展 cases.jsonl（G-15，只做可跑通映射） ----

def test_load_scenarios_default_unchanged():
    """缺省不传 cases_path -> 仍 5 个手写场景（不破坏既有行为/基线）。"""
    assert len(load_scenarios()) == 5


def test_load_scenarios_merges_cases(tmp_path):
    """传 cases_path：normal case 并入（id=trace_id），chitchat/empty 排除。"""
    import json
    p = tmp_path / "cases.jsonl"
    rows = [
        {"trace_id": "tc-normal", "type": "normal", "query": "查询订单风险",
         "answer": "风险分析", "good": None},
        {"trace_id": "tc-chat", "type": "chitchat", "query": "你好"},
        {"trace_id": "tc-empty", "type": "empty", "query": "  "},
        {"trace_id": "tc-normal2", "type": "normal", "query": "评估产能"},
    ]
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                 encoding="utf-8")

    scenarios = load_scenarios(p)
    base = [s for s in scenarios if s["id"].startswith("bt_")]
    case_s = [s for s in scenarios if not s["id"].startswith("bt_")]
    assert len(base) == 5
    assert [s["id"] for s in case_s] == ["tc-normal", "tc-normal2"]
    for s in case_s:
        assert s["query"] and s["expected_keypoints"] == []  # 可跑通映射，覆盖度不设
    # 派生场景评分不炸（空 keypoints coverage=1.0）
    score = score_backtest("任意答案", case_s[0])
    assert score["coverage"] == 1.0
