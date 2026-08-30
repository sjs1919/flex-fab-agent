"""统计预测纯函数（M5a T5a.4）。

无 IO、不依赖 DB——forecaster.py 负责聚合数据后调用本模块。
口径（用户 2026-08-23 确认）：默认指数平滑（α 可配），预测窗口 5 天。
"""
from __future__ import annotations


def moving_average(series: list[float], window: int) -> float | None:
    """移动平均预测：取序列末尾 window 个值的均值作为下一期预测。

    序列短于窗口时回落全序列均值（数学上与截断均值一致）。
    空序列返回 None（调用方判空）。
    """
    if not series:
        return None
    window = max(1, int(window))
    recent = series[-window:]
    return sum(recent) / len(recent)


def exponential_smoothing(series: list[float], alpha: float, n_forecast: int) -> list[float]:
    """指数平滑预测：level 型（无趋势项），输出未来 n_forecast 期平坦预测。

    初始值口径：s0 = 首值（不引入独立初始化参数；历史首日即为基线水平）。
    递推：s_t = alpha * x_t + (1 - alpha) * s_{t-1}；预测 = 最后一期 level。
    空序列返回 []；α 截断到 [0,1]（非法值按边界处理，不抛异常）。
    """
    if not series or n_forecast <= 0:
        return []
    alpha = min(1.0, max(0.0, float(alpha)))
    level = float(series[0])
    for x in series[1:]:
        level = alpha * float(x) + (1 - alpha) * level
    return [level] * int(n_forecast)
