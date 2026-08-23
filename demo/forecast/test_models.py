"""forecast/models.py 纯函数测试（M5a T5a.4，无 DB 依赖）。"""
import pytest

from demo.forecast.models import exponential_smoothing, moving_average


# ---- 指数平滑 ----

def test_es_constant_series_forecasts_constant():
    """恒定序列 -> 预测=常数（level 不漂移）。"""
    assert exponential_smoothing([5.0] * 10, 0.3, 5) == [5.0] * 5


def test_es_alpha_one_follows_latest():
    """α=1 -> level 全跟最新值（预测=末值）。"""
    assert exponential_smoothing([1.0, 2.0, 3.0, 9.0], 1.0, 3) == [9.0] * 3


def test_es_trend_series_continues_direction():
    """上行趋势 -> 预测 > 序列均值且 ≤ 最新值（level 平滑响应方向）；下行对称。"""
    up = [1.0, 2.0, 3.0, 4.0, 5.0]
    fc = exponential_smoothing(up, 0.5, 1)[0]
    assert sum(up) / len(up) < fc <= 5.0
    down = [5.0, 4.0, 3.0, 2.0, 1.0]
    fc2 = exponential_smoothing(down, 0.5, 1)[0]
    assert 1.0 <= fc2 < sum(down) / len(down)


def test_es_output_length_matches_n_forecast():
    """输出长度 = n_forecast（平坦预测逐日重复 level）。"""
    out = exponential_smoothing([2.0, 4.0, 6.0], 0.3, 5)
    assert len(out) == 5 and len(set(out)) == 1


def test_es_empty_and_single_element():
    """空序列返回 []；单元素返回 n 个首值（不崩溃）。"""
    assert exponential_smoothing([], 0.3, 5) == []
    assert exponential_smoothing([7.0], 0.3, 3) == [7.0] * 3


def test_es_alpha_clamped():
    """α 非法值（<0 / >1）截断到边界，不抛异常。"""
    assert exponential_smoothing([1.0, 5.0], 2.0, 1) == [5.0]  # 视同 α=1
    assert exponential_smoothing([3.0, 5.0], -1.0, 1) == [3.0]  # 视同 α=0


# ---- 移动平均 ----

def test_ma_window_truncation():
    """窗口截断：只取末尾 window 个值（前面的旧值不影响）。"""
    series = [0.0, 0.0, 0.0, 10.0, 20.0]
    assert moving_average(series, 2) == pytest.approx(15.0)


def test_ma_short_series_falls_back_to_full_mean():
    """序列短于窗口 -> 回落全序列均值。"""
    assert moving_average([1.0, 2.0], 5) == pytest.approx(1.5)


def test_ma_empty_and_single():
    """空序列返回 None；单元素返回自身。"""
    assert moving_average([], 3) is None
    assert moving_average([4.0], 3) == 4.0
