"""工具层权限校验 -- 洋葱型防御的第 3 层（工具层二次验证）。

为什么单独建 guard：
  week4 的缺口#7--STS 签发了子 Token，但工具调用前不校验、子 Agent 不传 Token，
  鉴权代码写了却没生效。本模块把 RBAC 校验落到工具执行入口（ToolRegistry.execute），
  让"有鉴权代码"变成"鉴权真生效"。

策略：
  - 传入 token 则强制校验 can_access；无权则拒绝并审计。
  - 不传 token：只读工具放行（兼容单 Agent 无鉴权模式）；写工具一律拒绝（R-2/R-7）。
  - 写工具（read_only=False）走配额 R-D2（quota.py，5min 滑窗 >3 拒）。

R8 缺陷修复（2026-08-07）：增加 tenant_id 校验维度（FORCE_TENANT=true 时强制）。
M4a（v2 D3）：校验顺序 token -> RBAC -> 配额 -> execute。
"""
import os
from ..auth.token_exchange import Token
from ..auth.audit_logger import AuditLogger


def check_tool_permission(token: Token | None, tool_name: str,
                          audit: AuditLogger | None = None,
                          read_only: bool = True) -> tuple[bool, str]:
    """工具层 RBAC 校验。返回 (allowed, reason)。

    token=None 时：只读工具放行（单 Agent 模式无鉴权）；写工具拒绝（R-2）。
    token 过期或权限不足则拒绝，并写审计 WARN。
    写工具额外过配额（R-D2），超限写审计 quota_exceeded + tracer span。

    R8：FORCE_TENANT=true 时，无 tenant_id 拒绝（多租户隔离强制模式）。
    """
    if token is None:
        # R8：强制租户模式下，单 Agent 无 Token 也拒绝
        if os.getenv("FORCE_TENANT", "false").lower() == "true":
            return False, "强制租户模式：需要有效的 Token"
        # R-2/R-7：写工具禁止匿名执行
        if not read_only:
            if audit:
                audit.log("deny", "anonymous", tool_name, {},
                          "写工具需要 token（R-2）", "WARN")
            return False, f"写工具 '{tool_name}' 需要 token（R-2/R-7：写操作禁止匿名）"
        return True, "无 token（未鉴权模式）"

    subject = token.subject

    # R8：租户隔离校验（FORCE_TENANT 模式）
    if os.getenv("FORCE_TENANT", "false").lower() == "true":
        if not token.tenant_id:
            if audit:
                audit.log("deny", subject, tool_name, {}, "缺少 tenant_id", "WARN")
            return False, "强制租户模式：Token 缺少 tenant_id"

    if token.is_expired():
        if audit:
            audit.log("deny", subject, tool_name, {}, "Token 过期", "WARN")
        return False, "Token 过期"
    if not token.can_access(tool_name):
        if audit:
            audit.log("deny", subject, tool_name, {"role": token.role}, "权限不足", "WARN")
        return False, f"权限不足：角色 {token.role} 无权调用 {tool_name}"
    if not read_only:
        from ..auth.quota import write_quota
        allowed, qreason = write_quota.check_and_consume(subject, tool_name)
        if not allowed:
            if audit:
                audit.log("quota_exceeded", subject, tool_name,
                          {"role": token.role}, qreason, "WARN")
            from ..observability.tracer import tracer
            tracer.record("quota_exceeded", 0, subject=subject, tool=tool_name)
            return False, qreason
    return True, "ok"
