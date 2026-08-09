"""鉴权层单元测试：Token RBAC + guard 工具权限校验。"""
import time

from demo.auth.token_exchange import Token, MemoryTokenStore
from demo.auth.guard import check_tool_permission


def _token(role="scheduler", permissions=None, expired=False, tenant_id=""):
    return Token(
        subject="user_001",
        role=role,
        permissions=permissions or [],
        source="user",
        tenant_id=tenant_id,
        expires_at=(time.time() - 1) if expired else (time.time() + 3600),
    )


# ---- Token.can_access ----

def test_token_can_access_allowed():
    t = _token(permissions=["query_orders", "query_inventory"])
    assert t.can_access("query_orders")
    assert not t.can_access("get_order_detail")  # 不在权限列表


def test_token_admin_wildcard():
    t = _token(role="admin", permissions=["*"])
    assert t.can_access("query_orders")
    assert t.can_access("any_tool")


def test_token_expired():
    t = _token(permissions=["query_orders"], expired=True)
    assert not t.can_access("query_orders")
    assert t.is_expired()


# ---- guard.check_tool_permission ----

def test_guard_no_token_passthrough(monkeypatch):
    """无 token 时放行（单 Agent 未鉴权模式）。"""
    monkeypatch.delenv("FORCE_TENANT", raising=False)
    allowed, reason = check_tool_permission(None, "query_orders")
    assert allowed is True


def test_guard_force_tenant_no_token_denied(monkeypatch):
    """FORCE_TENANT=true 时无 token 拒绝。"""
    monkeypatch.setenv("FORCE_TENANT", "true")
    allowed, reason = check_tool_permission(None, "query_orders")
    assert allowed is False
    assert "Token" in reason


def test_guard_force_tenant_missing_tenant_id(monkeypatch):
    """FORCE_TENANT=true 时有 token 但无 tenant_id 拒绝。"""
    monkeypatch.setenv("FORCE_TENANT", "true")
    t = _token(permissions=["query_orders"], tenant_id="")
    allowed, reason = check_tool_permission(t, "query_orders")
    assert allowed is False
    assert "tenant_id" in reason


def test_guard_force_tenant_with_tenant_ok(monkeypatch):
    """FORCE_TENANT=true 时有 token + tenant_id 放行。"""
    monkeypatch.setenv("FORCE_TENANT", "true")
    t = _token(permissions=["query_orders"], tenant_id="t1")
    allowed, reason = check_tool_permission(t, "query_orders")
    assert allowed is True


def test_guard_expired_token_denied():
    t = _token(permissions=["query_orders"], expired=True)
    allowed, reason = check_tool_permission(t, "query_orders")
    assert allowed is False
    assert "过期" in reason


def test_guard_insufficient_permission_denied():
    t = _token(role="reviewer", permissions=["get_order_detail"])
    allowed, reason = check_tool_permission(t, "query_orders")
    assert allowed is False
    assert "权限不足" in reason


def test_guard_audit_called_on_deny(monkeypatch):
    """拒绝时写审计。"""
    class FakeAudit:
        def __init__(self):
            self.logged = []
        def log(self, action, subject, obj, details, msg, level="INFO"):
            self.logged.append((action, level))
    audit = FakeAudit()
    t = _token(permissions=["query_orders"], expired=True)
    allowed, _ = check_tool_permission(t, "query_orders", audit=audit)
    assert allowed is False
    assert any(a == "deny" for a, _ in audit.logged)


# ---- MemoryTokenStore ----

def test_memory_token_store_save_get_delete():
    store = MemoryTokenStore()
    t = _token()
    store.save(t)
    assert store.get(t.token_id) == t
    store.delete(t.token_id)
    assert store.get(t.token_id) is None
