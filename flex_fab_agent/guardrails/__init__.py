"""输出护栏模块 -- LLM 输出安全校验的统一入口（R2 缺陷修复）。

用法：
  from ..guardrails import run_guardrails
  result = run_guardrails(llm_output, context={"mode": "scheduling"})
  if result.is_valid:
      return result.text
  else:
      # 重试 LLM 或降级
"""
from dataclasses import dataclass, field
from .content_filter import GuardrailsViolation, filter_output
from .rules import check_missing_sections


@dataclass
class GuardrailsResult:
    """护栏检查结果。"""
    text: str
    is_valid: bool
    warnings: list[str] = field(default_factory=list)
    blocked_by: str = ""


def run_guardrails(text: str, context: dict | None = None) -> GuardrailsResult:
    """对 LLM 输出运行完整护栏检查。

    Args:
        text: LLM 原始输出
        context: 上下文信息 {"mode": "scheduling"|"query"|"rag"}

    Returns:
        GuardrailsResult — is_valid=True 表示通过所有检查
    """
    warnings: list[str] = []
    ctx = context or {}
    mode = ctx.get("mode", "scheduling")

    # 1. 安全过滤（越权/敏感信息）
    try:
        text, violations = filter_output(text, ctx)
        for v in violations:
            if "禁止内容" in v:
                return GuardrailsResult(
                    text="",
                    is_valid=False,
                    warnings=violations,
                    blocked_by=v,
                )
            warnings.append(v)
    except GuardrailsViolation as e:
        return GuardrailsResult(
            text="", is_valid=False, warnings=e.violations, blocked_by=str(e),
        )

    # 2. 排产模式 → 检查必要段落
    if mode == "scheduling":
        missing = check_missing_sections(text)
        if missing:
            warnings.extend(missing)
            print(f"  ⚠️  [护栏告警] {missing}")

    return GuardrailsResult(text=text, is_valid=True, warnings=warnings)
