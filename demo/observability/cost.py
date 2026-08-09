"""成本监控 -- Token 用量计费 + 预算熔断（week5 #1 企业级缺口补齐）。

设计要点：
  - CostTracker 是模块级单例，在 call_llm 中自动记录每次 LLM 调用的 token 用量和费用。
  - 定价来自各 provider 官方（¥/百万 token），输入输出分开计。
  - 预算熔断（circuit breaker）：累计费用超预算后拒绝新请求，防止失控。
  - 与 tracer 集成：每轮 flush 时输出费用摘要，OTel 档下可导出到成本看板。

使用方式：
  from ..observability import cost_tracker
  cost_tracker.record("火山豆包(coding)", prompt_tokens=500, completion_tokens=200)

环境变量：
  LLM_BUDGET_LIMIT  -- 单次会话预算上限（¥），默认 5.0；设 0 禁用熔断
  LLM_BUDGET_WARN   -- 预算预警阈值（0~1），默认 0.8（80% 时开始警告）
"""
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Literal


# ──────────────────────────────────────────────
# 定价表：各 provider 的输入/输出价格（¥/百万 token）
# 数据来源：各平台官方定价页，最后更新 2026-08
# ──────────────────────────────────────────────
PRICE_PER_MILLION: dict[str, dict[str, float]] = {
    "火山豆包(coding)":  {"input": 2.0, "output": 2.0},   # 字节编程套餐
    "DeepSeek":          {"input": 1.0, "output": 1.0},   # deepseek-v4-flash
    "Kimi(coding)":      {"input": 2.0, "output": 2.0},   # 月之暗面编程
    # 默认：未知 provider 按 2.0 估算
}
DEFAULT_PRICE = {"input": 2.0, "output": 2.0}

# 预算上限（¥），0 表示不限制
BUDGET_LIMIT = float(os.getenv("LLM_BUDGET_LIMIT", "5.0"))
# 预警阈值（0~1），达到预算的这个比例时开始警告
BUDGET_WARN = float(os.getenv("LLM_BUDGET_WARN", "0.8"))


@dataclass
class CostEntry:
    """单次 LLM 调用的费用记录。"""
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_input: float       # 输入费用（¥）
    cost_output: float      # 输出费用（¥）
    cost_total: float       # 本次总费用（¥）
    timestamp: float = field(default_factory=time.time)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class BudgetExceededError(RuntimeError):
    """预算熔断异常。"""
    def __init__(self, spent: float, limit: float):
        super().__init__(
            f"LLM 预算已耗尽：已花费 ¥{spent:.4f}，上限 ¥{limit:.2f}。"
            f"请检查调用链路或调高 LLM_BUDGET_LIMIT。"
        )
        self.spent = spent
        self.limit = limit


class CostTracker:
    """Token 成本追踪器（单例）。"""

    def __init__(self) -> None:
        self._entries: list[CostEntry] = []
        self._lock = threading.Lock()
        self._budget_exceeded = False

    def record(self, provider: str, model: str = "",
               prompt_tokens: int = 0, completion_tokens: int = 0) -> CostEntry:
        """记录一次 LLM 调用的费用。预算超限时抛出 BudgetExceededError。"""
        # 查询定价
        prices = PRICE_PER_MILLION.get(provider, DEFAULT_PRICE)
        cost_input = (prompt_tokens / 1_000_000) * prices["input"]
        cost_output = (completion_tokens / 1_000_000) * prices["output"]

        entry = CostEntry(
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_input=cost_input,
            cost_output=cost_output,
            cost_total=cost_input + cost_output,
        )

        with self._lock:
            self._entries.append(entry)
            total = round(sum(e.cost_total for e in self._entries), 6)

        # 预算预警
        if BUDGET_LIMIT > 0:
            if total >= BUDGET_LIMIT:
                self._budget_exceeded = True
                raise BudgetExceededError(total, BUDGET_LIMIT)
            if total >= BUDGET_LIMIT * BUDGET_WARN:
                remaining = BUDGET_LIMIT - total
                print(f"  💰 [成本预警] 已花费 ¥{total:.4f} / ¥{BUDGET_LIMIT:.2f}，剩余 ¥{remaining:.4f}")

        return entry

    @property
    def total_cost(self) -> float:
        with self._lock:
            return round(sum(e.cost_total for e in self._entries), 6)

    @property
    def total_tokens(self) -> int:
        with self._lock:
            return sum(e.total_tokens for e in self._entries)

    @property
    def is_budget_exceeded(self) -> bool:
        return self._budget_exceeded

    def by_provider(self) -> dict[str, dict]:
        """按 provider 分组统计。"""
        with self._lock:
            result: dict[str, dict] = {}
            for e in self._entries:
                if e.provider not in result:
                    result[e.provider] = {"calls": 0, "tokens": 0, "cost": 0.0}
                result[e.provider]["calls"] += 1
                result[e.provider]["tokens"] += e.total_tokens
                result[e.provider]["cost"] += e.cost_total
            # round costs
            for v in result.values():
                v["cost"] = round(v["cost"], 6)
            return result

    def get_summary(self) -> dict:
        """返回本轮会话的费用摘要。"""
        return {
            "total_cost": self.total_cost,
            "total_tokens": self.total_tokens,
            "total_calls": len(self._entries),
            "by_provider": self.by_provider(),
            "budget": {"limit": BUDGET_LIMIT, "exceeded": self._budget_exceeded},
        }

    def format_text(self) -> str:
        """文本版费用摘要。"""
        sm = self.get_summary()
        lines = [
            f"💰 费用摘要：总计 ¥{sm['total_cost']:.4f}，{sm['total_tokens']} tokens，{sm['total_calls']} 次调用",
        ]
        if BUDGET_LIMIT > 0:
            pct = sm["total_cost"] / BUDGET_LIMIT * 100
            bar = "▓" * int(pct / 5) + "░" * (20 - int(pct / 5))
            lines.append(f"   预算: [{bar}] {pct:.0f}%  (¥{sm['total_cost']:.4f} / ¥{BUDGET_LIMIT:.2f})")
        for name, stats in sm["by_provider"].items():
            lines.append(f"   {name}: {stats['calls']} 次, {stats['tokens']} tokens, ¥{stats['cost']:.4f}")
        return "\n".join(lines)

    def reset(self) -> None:
        """重置当前会话的统计（每轮 query 开始前调用）。"""
        with self._lock:
            self._entries.clear()
            self._budget_exceeded = False


# 模块级单例
cost_tracker = CostTracker()