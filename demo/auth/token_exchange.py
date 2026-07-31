"""Token Exchange 鉴权 -- 用户身份透传 + 工具级权限（RFC 8693）。

流程：用户 Token -> STS（Security Token Service）-> 受限子 Token -> Agent 调用。
洋葱型防御：网关层(JWT 验证) -> 运行时层(RBAC) -> 工具层(二次验证，见 guard.py)。

关键设计：
  - 子 Token 权限 ≤ 父 Token（防权限升级）
  - 子 Token 5 分钟过期（最小权限，泄漏影响有限）
  - source="token_exchange" 标记来源，审计可追溯
"""
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

RoleType = Literal["admin", "scheduler", "reviewer", "operator", "viewer"]

# 5 角色 × 可调用工具集合。admin 通配。
ROLE_PERMISSIONS: dict[RoleType, list[str]] = {
    "admin":     ["*"],
    "scheduler": ["query_orders", "get_order_detail", "get_production_status",
                  "query_inventory", "query_machine_load", "query_customer"],
    "reviewer":  ["get_order_detail", "get_production_status", "query_customer"],
    "operator":  ["query_orders", "query_machine_load", "query_inventory"],
    "viewer":    ["query_orders"],
}


@dataclass
class Token:
    """JWT Token 的简化表示。"""
    subject: str                # 用户/Agent 身份
    role: RoleType
    permissions: list[str]
    source: str                 # "user" | "token_exchange"
    parent_trace: str = ""
    issued_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    token_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def is_expired(self) -> bool:
        return self.expires_at > 0 and time.time() > self.expires_at

    def can_access(self, tool_name: str) -> bool:
        """RBAC 校验：过期则拒；通配 * 则放；否则需在权限列表里。"""
        if self.is_expired():
            return False
        if "*" in self.permissions:
            return True
        return tool_name in self.permissions


class STS:
    """Security Token Service - Token 签发与交换。"""

    def __init__(self) -> None:
        # 内存存储（缺口#5：重启丢失，后续可换 SQLite 持久化）
        self._issued_tokens: dict[str, Token] = {}

    def issue_user_token(self, user_id: str, role: RoleType, ttl: int = 3600) -> str:
        """签发用户 Token（1 小时有效）。"""
        token = Token(
            subject=user_id, role=role,
            permissions=ROLE_PERMISSIONS.get(role, []),
            source="user", expires_at=time.time() + ttl,
        )
        self._issued_tokens[token.token_id] = token
        return token.token_id

    def exchange(self, parent_token_id: str, requested_role: RoleType,
                 target_trace: str = "") -> tuple[str | None, str]:
        """Token Exchange：父 Token -> 受限子 Token（5 分钟有效）。"""
        parent = self._issued_tokens.get(parent_token_id)
        if not parent:
            return None, "父 Token 不存在"
        if parent.is_expired():
            return None, "父 Token 已过期"

        # 权限收缩检查：子 Token 权限不能超过父 Token
        child_perms = ROLE_PERMISSIONS.get(requested_role, [])
        if "*" not in parent.permissions:
            for p in child_perms:
                if p not in parent.permissions:
                    return None, f"权限不足：子角色需要 {p}，父角色没有"

        child = Token(
            subject=f"{parent.subject}:{requested_role}",
            role=requested_role,
            permissions=child_perms,
            source="token_exchange",
            parent_trace=parent.parent_trace or parent.token_id,
            expires_at=time.time() + 300,
        )
        self._issued_tokens[child.token_id] = child
        return child.token_id, "ok"

    def get_token(self, token_id: str) -> Token | None:
        return self._issued_tokens.get(token_id)

    def revoke(self, token_id: str) -> None:
        if token_id in self._issued_tokens:
            del self._issued_tokens[token_id]
            print(f"[鉴权] Token {token_id[:8]}... 已吊销")

    def revoke_all(self) -> None:
        count = len(self._issued_tokens)
        self._issued_tokens.clear()
        print(f"[鉴权] 已吊销 {count} 个 Token（通用注销）")
