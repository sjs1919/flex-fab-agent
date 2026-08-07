"""内容过滤器 -- 敏感词 + 越权指令 + 有害内容检测（R2 缺陷修复）。

三层防御：
  1. 规则匹配（regex，零延迟）
  2. 可选：小模型分类器（有害内容检测，按需启用，当前未实现）
  3. 降级策略：原样返回 + 告警 或 替换敏感部分
"""
import os
from .rules import check_blocked_content, check_sensitive_info


GUARDRAILS_MODE = os.getenv("GUARDRAILS_MODE", "warn")  # block | warn | off


class GuardrailsViolation(Exception):
    """护栏违规异常。"""
    def __init__(self, violations: list[str], original_output: str):
        self.violations = violations
        self.original_output = original_output[:200]
        super().__init__(f"护栏违规（{len(violations)} 条）: {'; '.join(violations[:3])}")


def filter_output(text: str, context: dict | None = None) -> tuple[str, list[str]]:
    """对 LLM 输出做安全过滤。

    Returns:
        (filtered_text, violations) — violations 为空列表表示通过。
    """
    if GUARDRAILS_MODE == "off":
        return text, []

    violations: list[str] = []

    # 1. 越权指令检测
    blocked = check_blocked_content(text)
    violations.extend(blocked)

    # 2. 敏感信息检测
    sensitive = check_sensitive_info(text)
    violations.extend(sensitive)

    # 3. 按模式处理
    if violations:
        if GUARDRAILS_MODE == "block":
            raise GuardrailsViolation(violations, text)
        else:  # warn
            print(f"  ⚠️  [护栏告警] {len(violations)} 条违规: {'; '.join(violations[:3])}")

    return text, violations
