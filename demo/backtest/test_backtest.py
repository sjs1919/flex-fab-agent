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
