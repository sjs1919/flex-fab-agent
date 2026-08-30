"""护栏规则定义 -- 可配置的输出校验规则集（R2 缺陷修复）。

每条规则是一个检查项。
severity: "block"（阻断+重试）| "warn"（告警但放行）| "sanitize"（替换后放行）
"""
import re


# ── 越权操作指令（不应出现在 Agent 输出中）──
BLOCKED_PATTERNS = [
    # 修改类操作（排产助手只给建议，不应直接修改数据）
    r"修改.*订单状态", r"删除.*订单", r"取消.*排产",
    r"UPDATE.*SET", r"DELETE.*FROM", r"DROP.*TABLE",
    # 系统指令注入防护
    r"忽略.*系统指令", r"ignore.*system prompt", r"你是.*新角色",
    r"reset.*your.*instructions",
]

# ── 敏感信息泄露模式 ──
SENSITIVE_PATTERNS = [
    r"\b\d{16}\b",              # 银行卡号
    r"\b\d{6}(19|20)\d{2}\b",   # 身份证片段
]

# ── 输出格式规则（排产建议必须包含的结构）──
REQUIRED_SECTIONS_FOR_SCHEDULING = [
    "关键发现", "优先排产", "可延后",
]


def check_blocked_content(text: str) -> list[str]:
    """检测是否包含禁止内容。返回匹配到的规则描述列表。"""
    hits = []
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            hits.append(f"检测到禁止内容: {pattern}")
    return hits


def check_missing_sections(text: str, required: list[str] | None = None) -> list[str]:
    """检测是否缺少必要的输出段落。"""
    if required is None:
        required = REQUIRED_SECTIONS_FOR_SCHEDULING
    missing = [s for s in required if s not in text]
    return [f"缺少必要段落: '{s}'" for s in missing]


def check_sensitive_info(text: str) -> list[str]:
    """检测是否包含敏感信息。返回发现的内容描述（脱敏后显示）。"""
    hits = []
    for pattern in SENSITIVE_PATTERNS:
        matches = re.findall(pattern, text)
        if matches:
            hits.append(f"疑似敏感信息: {pattern}（匹配 {len(matches)} 处）")
    return hits
