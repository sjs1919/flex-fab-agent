"""回测场景定义 -- 从历史延期记录提取真实复盘案例。

回测理念：demo 的静态 CSV 是"单时间点快照"，无法做"随时间演进的决策验证"。
本模块用 历史延期记录.txt 的 5 个真实案例作为回测场景——让 Agent 对这些
历史事件做"复盘决策"，对照人工复盘结论，验证 Agent 的排产/风险识别能力。

每个场景定义：
  - query: 给 Agent 的提问（模拟复盘会议的问题）
  - expected_keypoints: 人工复盘里的关键要点（Agent 答案应覆盖）
  - context_hint: 数据层提示（可选，引导 Agent 查哪些工具）
"""
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def load_scenarios() -> list[dict]:
    """从历史延期记录提取回测场景。当前为手写 5 个（对应案例 1-5）。"""
    return [
        {
            "id": "bt_001",
            "title": "设备故障逾期",
            "query": "复盘：2025 年深圳精密 CNC 设备主轴故障导致 4 个订单连带逾期。"
                     "作为排产助手，你会如何提前识别并规避此类设备故障风险？",
            "expected_keypoints": ["设备故障", "预防性维护", "备件库存", "风险预警"],
            "context": "设备负载 data/machines.csv 含预计空闲时间/状态；历史延期记录有故障复盘。",
            "must_not": ["不知道", "无法识别"],
        },
        {
            "id": "bt_002",
            "title": "物料延迟到货",
            "query": "复盘：2025 年东莞模具厂因客户物料（Cr12MoV）延迟到货 5 天导致订单顺延。"
                     "排产时如何规避物料到货风险？",
            "expected_keypoints": ["物料到货", "预警", "提前备料", "顺延"],
            "context": "库存 data/inventory.csv 含安全库存/采购周期；可查材料库存。",
            "must_not": ["不知道"],
        },
        {
            "id": "bt_003",
            "title": "质检报废返工",
            "query": "复盘：2025 年广州航天五轴加工件质检发现 12 件内部气孔缺陷，报废重做逾期 2 天。"
                     "航天级精密件排产应如何留足缓冲？",
            "expected_keypoints": ["质检", "报废", "缓冲", "全检"],
            "context": "历史延期记录提示航天级件延期赔付成本极高，须留足缓冲。",
            "must_not": ["不知道"],
        },
        {
            "id": "bt_004",
            "title": "加急订单插单",
            "query": "复盘：2025 年深圳精密加急订单在热处理排队险些逾期，调度组紧急插队才按期交付。"
                     "排产如何为加急订单设绿色通道？",
            "expected_keypoints": ["加急", "绿色通道", "插队", "预留产能"],
            "context": "设备负载可查当前任务；紧急订单状态在 orders.csv。",
            "must_not": ["不知道"],
        },
        {
            "id": "bt_005",
            "title": "设计变更顺延",
            "query": "复盘：2025 年东莞模具厂因客户中途变更模具设计，报废 30 件、交期顺延 10 天。"
                     "排产如何评估设计变更对交期的影响？",
            "expected_keypoints": ["设计变更", "交期影响", "顺延", "评估"],
            "context": "订单交期在 orders.csv；历史延期记录有变更复盘。",
            "must_not": ["不知道"],
        },
    ]


def score_backtest(answer: str, scenario: dict) -> dict:
    """评估回测答案覆盖度：命中关键要点数 / 触发禁止词。

    Args:
        answer: Agent 对 query 的回复
        scenario: 回测场景定义

    Returns:
        {"hits": int, "total": int, "coverage": float, "forbidden_hit": bool}
    """
    keypoints = scenario["expected_keypoints"]
    hits = sum(1 for kp in keypoints if kp in answer)
    must_not = scenario.get("must_not", [])
    forbidden_hit = any(mn in answer for mn in must_not)
    return {
        "hits": hits,
        "total": len(keypoints),
        "coverage": round(hits / len(keypoints), 3) if keypoints else 1.0,
        "forbidden_hit": forbidden_hit,
    }
