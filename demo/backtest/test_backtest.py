"""回测模块单元测试：场景加载 + 覆盖度评分（纯函数，不调 LLM）。"""
from demo.backtest.scenarios import load_scenarios, score_backtest


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
    from demo.backtest import runner as runner_mod
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
