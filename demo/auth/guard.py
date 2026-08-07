"""工具层权限校验 -- 洋葱型防御的第 3 层（工具层二次验证）。

为什么单独建 guard：
  week4 的缺口#7--STS 签发了子 Token，但工具调用前不校验、子 Agent 不传 Token，
  鉴权代码写了却没生效。本模块把 RBAC 校验落到工具执行入口（ToolRegistry.execute），
  让"有鉴权代码"变成"鉴权真生效"。

策略：
  - 传入 token 则强制校验 can_access；无权则拒绝并审计。
  - 不传 token 则放行（兼容单 Agent 无鉴权模式）。

R8 缺陷修复（2026-08-07）：增加 tenant_id 校验维度（FORCE_TENANT=true 时强制）。
"""
import os
from ..auth.token_exchange import Token
from ..auth.audit_logger import AuditLogger


def check_tool_permission(token: Token | None, tool_name: str,
                          audit: AuditLogger | None = None) -> tuple[bool, str]:
    """工具层 RBAC 校验。返回 (allowed, reason)。

    token=None 时放行（单 Agent 模式无鉴权）；
    token 过期或权限不足则拒绝，并写审计 WARN。

    R8：FORCE_TENANT=true 时，无 tenant_id 拒绝（多租户隔离强制模式）。
    """
    if token is None:
        # R8：强制租户模式下，单 Agent 无 Token 也拒绝
        if os.getenv("FORCE_TENANT", "false").lower() == "true":
            return False, "强制租户模式：需要有效的 Token"
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
    return True, "ok"
