"""Token Exchange 鉴权 -- 用户身份透传 + 工具级权限（RFC 8693）。

流程：用户 Token -> STS（Security Token Service）-> 受限子 Token -> Agent 调用。
洋葱型防御：网关层(JWT 验证) -> 运行时层(RBAC) -> 工具层(二次验证，见 guard.py)。

关键设计：
  - 子 Token 权限 ≤ 父 Token（防权限升级）
  - 子 Token 5 分钟过期（最小权限，泄漏影响有限）
  - source="token_exchange" 标记来源，审计可追溯
  - 持久化：SQLite 存储（重启不丢），由 TOKEN_STORE 环境变量控制（sqlite 默认 / memory）
"""
import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

from ..config import RUNTIME_DIR

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
    """JWT Token 的简化表示。R8：新增 tenant_id 字段。"""
    subject: str                # 用户/Agent 身份
    role: RoleType
    permissions: list[str]
    source: str                 # "user" | "token_exchange"
    tenant_id: str = ""         # R8 新增：租户 ID
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


class TokenStore:
    """Token 持久化存储抽象。"""

    def save(self, token: Token) -> None:
        raise NotImplementedError

    def get(self, token_id: str) -> Token | None:
        raise NotImplementedError

    def delete(self, token_id: str) -> None:
        raise NotImplementedError

    def delete_all(self) -> int:
        raise NotImplementedError


class MemoryTokenStore(TokenStore):
    """内存存储（进程重启丢失）。"""

    def __init__(self):
        self._tokens: dict[str, Token] = {}

    def save(self, token: Token) -> None:
        self._tokens[token.token_id] = token

    def get(self, token_id: str) -> Token | None:
        return self._tokens.get(token_id)

    def delete(self, token_id: str) -> None:
        self._tokens.pop(token_id, None)

    def delete_all(self) -> int:
        count = len(self._tokens)
        self._tokens.clear()
        return count


class SqliteTokenStore(TokenStore):
    """SQLite 持久化存储（重启不丢）。过期 Token 读时自动清理。"""

    def __init__(self, db_path: str):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS tokens ("
            "  token_id TEXT PRIMARY KEY,"
            "  subject TEXT, role TEXT, permissions TEXT, source TEXT,"
            "  parent_trace TEXT, issued_at REAL, expires_at REAL,"
            "  tenant_id TEXT DEFAULT ''"  # R8 新增
            ")"
        )
        self._conn.commit()

    def save(self, token: Token) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO tokens VALUES (?,?,?,?,?,?,?,?,?)",
            (token.token_id, token.subject, token.role,
             json.dumps(token.permissions), token.source,
             token.parent_trace, token.issued_at, token.expires_at,
             token.tenant_id),  # R8 新增
        )
        self._conn.commit()

    def get(self, token_id: str) -> Token | None:
        row = self._conn.execute(
            "SELECT * FROM tokens WHERE token_id=?", (token_id,)
        ).fetchone()
        if not row:
            return None
        token = Token(
            subject=row[1], role=row[2], permissions=json.loads(row[3]),
            source=row[4], parent_trace=row[5], issued_at=row[6],
            expires_at=row[7], token_id=row[0],
            tenant_id=row[8] if len(row) > 8 else "",  # R8 兼容旧表无此列
        )
        if token.is_expired():
            self.delete(token_id)
            return None
        return token

    def delete(self, token_id: str) -> None:
        self._conn.execute("DELETE FROM tokens WHERE token_id=?", (token_id,))
        self._conn.commit()

    def delete_all(self) -> int:
        count = self._conn.execute("SELECT COUNT(*) FROM tokens").fetchone()[0]
        self._conn.execute("DELETE FROM tokens")
        self._conn.commit()
        return count


def _build_token_store() -> TokenStore:
    """按 TOKEN_STORE 环境变量构建存储后端（默认 sqlite）。"""
    mode = os.getenv("TOKEN_STORE", "sqlite").lower()
    if mode == "memory":
        return MemoryTokenStore()
    db_path = str(RUNTIME_DIR / "tokens.db")
    return SqliteTokenStore(db_path)


class STS:
    """Security Token Service - Token 签发与交换。"""

    def __init__(self) -> None:
        self._store = _build_token_store()

    def issue_user_token(self, user_id: str, role: RoleType,
                         tenant_id: str = "",    # R8 新增
                         ttl: int = 3600) -> str:
        """签发用户 Token（1 小时有效）。R8：支持 tenant_id。"""
        token = Token(
            subject=user_id, role=role,
            permissions=ROLE_PERMISSIONS.get(role, []),
            source="user",
            tenant_id=tenant_id,  # R8 新增
            expires_at=time.time() + ttl,
        )
        self._store.save(token)
        return token.token_id

    def exchange(self, parent_token_id: str, requested_role: RoleType,
                 target_trace: str = "") -> tuple[str | None, str]:
        """Token Exchange：父 Token -> 受限子 Token（5 分钟有效）。"""
        parent = self._store.get(parent_token_id)
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
            tenant_id=parent.tenant_id,  # R8：子 Token 继承父 Token 的租户
            parent_trace=parent.parent_trace or parent.token_id,
            expires_at=time.time() + 300,
        )
        self._store.save(child)
        return child.token_id, "ok"

    def get_token(self, token_id: str) -> Token | None:
        return self._store.get(token_id)

    def revoke(self, token_id: str) -> None:
        self._store.delete(token_id)
        print(f"[鉴权] Token {token_id[:8]}... 已吊销")

    def revoke_all(self) -> None:
        count = self._store.delete_all()
        print(f"[鉴权] 已吊销 {count} 个 Token（通用注销）")
