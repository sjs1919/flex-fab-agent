"""M4a T4a.3 写工具治理测试：RBAC 扩展 + 写 token 强制（R-2）+ 配额（R-D2）。

覆盖验收清单 M4 组条 2/11/12：
  - scheduler 可 run_scheduling、不可 approve_schedule；reviewer 反之
  - 写工具无 token 被拒；只读工具无 token 放行（单 Agent 兼容）
  - 同 subject 5min 内对同一写工具第 4 次调用被拒 + 审计 quota_exceeded + tracer span
  - registry.execute 写工具成功入审计；approver 从 token.subject 注入
"""
from flex_fab_agent.auth.audit_logger import AuditLogger
from flex_fab_agent.auth.guard import check_tool_permission
from flex_fab_agent.auth.quota import WriteQuota
from flex_fab_agent.auth.token_exchange import ROLE_PERMISSIONS, Token
from flex_fab_agent.tools.registry import ToolRegistry


def _token(role, subject="u1"):
    return Token(subject=subject, role=role,
                 permissions=ROLE_PERMISSIONS[role], source="user")


# ---- RBAC 矩阵（验收条 2/14） ----

def test_scheduler_can_schedule_not_approve():
    t = _token("scheduler")
    assert t.can_access("run_scheduling")
    assert t.can_access("query_schedule")
    assert t.can_access("query_sim_events")
    assert not t.can_access("approve_schedule")


def test_reviewer_can_approve_not_schedule():
    t = _token("reviewer")
    assert t.can_access("approve_schedule")
    assert t.can_access("query_schedule")
    assert not t.can_access("run_scheduling")


# ---- 写 token 强制（R-2/R-7，验收条 11） ----

def test_write_tool_without_token_denied():
    audit = AuditLogger(log_path=None)
    ok, reason = check_tool_permission(None, "run_scheduling", audit, read_only=False)
    assert not ok
    assert "token" in reason
    assert any(e["action"] == "deny" for e in audit._entries)


def test_read_tool_without_token_allowed():
    ok, _ = check_tool_permission(None, "query_schedule", read_only=True)
    assert ok


def test_write_tool_with_token_allowed():
    t = _token("scheduler")
    ok, _ = check_tool_permission(t, "run_scheduling", read_only=False)
    assert ok


# ---- 配额 R-D2（验收条 12） ----

def test_quota_fourth_write_rejected():
    q = WriteQuota(limit=3, window=300.0)
    for i in range(3):
        ok, _ = q.check_and_consume("u1", "run_scheduling")
        assert ok, f"第 {i + 1} 次应放行"
    ok, reason = q.check_and_consume("u1", "run_scheduling")
    assert not ok and "配额" in reason
    # 不同 subject / 不同工具互不影响
    assert q.check_and_consume("u2", "run_scheduling")[0]
    assert q.check_and_consume("u1", "approve_schedule")[0]


def test_quota_window_slides():
    q = WriteQuota(limit=3, window=0.05)
    assert q.check_and_consume("u1", "run_scheduling")[0]
    import time
    time.sleep(0.06)
    assert q.check_and_consume("u1", "run_scheduling")[0]


def test_guard_quota_denial_audits_and_spans():
    from flex_fab_agent.observability.tracer import tracer
    audit = AuditLogger(log_path=None)
    t = _token("scheduler", subject="quota-user")
    for _ in range(3):
        ok, _ = check_tool_permission(t, "run_scheduling", audit, read_only=False)
        assert ok
    ok, reason = check_tool_permission(t, "run_scheduling", audit, read_only=False)
    assert not ok
    assert any(e["action"] == "quota_exceeded" and e["subject"] == "quota-user"
               for e in audit._entries)
    spans = [s for s in tracer._spans if s.name == "quota_exceeded"]
    assert spans and spans[-1].attributes.get("subject") == "quota-user"


# ---- registry.execute 集成（治理层统一审计 + approver 注入） ----

def _write_registry(handler):
    r = ToolRegistry()
    r.register("fake_write", "测试写工具", {"type": "object", "properties": {
        "approver": {"type": "string"},
    }}, handler, "test", read_only=False)
    return r


def test_registry_write_without_token_denied():
    r = _write_registry(lambda **kw: "done")
    out = r.execute("fake_write", {})
    assert out.startswith("❌") and "token" in out


def test_registry_write_success_audited():
    captured = {}

    def _handler(approver="", **_kw):
        captured["approver"] = approver
        return "done"

    audit = AuditLogger(log_path=None)
    r = _write_registry(_handler)
    out = r.execute("fake_write", {}, token=_token("admin", subject="李四"), audit=audit)
    assert out == "done"
    assert captured["approver"] == "李四", "approver 应从 token.subject 注入"
    assert any(e["action"] == "write" and e["subject"] == "李四"
               for e in audit._entries)
