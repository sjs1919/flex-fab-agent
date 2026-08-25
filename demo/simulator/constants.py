"""simulator 包业务常量（seed.py / events.py 共用）。

集中定义避免同包内两个模块各自维护同一份常量，改一处漏另一处。
"""

# 客户等级 → 优先级基础分
LEVEL_SCORE: dict[str, int] = {"S": 50, "A": 40, "B": 25, "C": 10}

# 各工艺的零件尺寸范围（mm）—— 与 seed 口径一致，保证可装舱
PART_DIM_RANGE: dict[str, tuple[int, int]] = {
    "SLA": (80, 400),
    "MJS": (150, 500),
    "SLM": (50, 300),
}

# 各工艺的零件重量范围（kg）
PART_WEIGHT_RANGE: dict[str, tuple[float, float]] = {
    "SLA": (0.5, 8),
    "MJS": (2, 25),
    "SLM": (1, 30),
}


def calc_priority(level: str, urgent: bool, amount: float,
                  default_score: int = 10) -> int:
    """统一的订单优先级计算。

    优先级 = 等级基础分 + 加急加分(30) + 大订单加分(20, ≥5万)。

    Args:
        level: 客户等级 S/A/B/C
        urgent: 是否加急
        amount: 订单金额
        default_score: 未知等级时的默认基础分
    """
    base = LEVEL_SCORE.get(level, default_score)
    return base + (30 if urgent else 0) + (20 if amount >= 50000 else 0)
