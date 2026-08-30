"""E2E M4a 验收（T4a.6，需 WSL MySQL）-- 对照 todo-M4a 七项与验收清单 M4 组条 1/2/11/12/13/14。

① 工具数 18（--check 输出见 test_main_entry.py）
② 审批流：scheduler token run_scheduling -> reviewer token approve -> 版本已审核；
   scheduler token 调 approve 被拒（RBAC）
③ 治理：写工具无 token 被拒；写操作入审计
④ R-D2 配额：同 subject 对同一写工具第 4 次被拒 + quota_exceeded 审计 + tracer span
⑤ Prompt 版本化 rollback + 审计（--rollback CLI 见 test_main_entry.py）
⑥ solver span 含 耗时/目标值/约束违反数
⑦ /sim 与 /schedule/load 端点（见 test_api_sim.py，此处不重复）
"""
import re

import pytest

from flex_fab_agent.auth.audit_logger import AuditLogger
from flex_fab_agent.auth.token_exchange import STS
from flex_fab_agent.observability.tracer import tracer
from flex_fab_agent.prompts.versioning import rollback
from flex_fab_agent.simulator import seed as seed_mod
from flex_fab_agent.tools.data import get_connection
from flex_fab_agent.tools.registry import build_default_registry

sts = STS()


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    seed_mod.reset()


def _rows(sql, params=()):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def _exec(sql, params=()):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()


def test_1_registry_18_tools():
    """① 验收条 1：11 排产工具注册齐全，总数 18。"""
    r = build_default_registry()
    assert len(r) == 18


def test_2_3_approval_flow_and_governance():
    """②③ 验收条 2/11：审批流 + 写 token 治理 + 审计，端到端走 registry.execute。"""
    r = build_default_registry()
    audit = AuditLogger(log_path=None)
    sched_token = sts.get_token(sts.issue_user_token("e2e-sched", "scheduler"))
    rev_token = sts.get_token(sts.issue_user_token("e2e-reviewer", "reviewer"))

    # ③ 写工具无 token 被拒（R-2）
    out = r.execute("run_scheduling", {}, audit=audit)
    assert out.startswith("❌") and "token" in out

    # ② scheduler 触发求解（写工具 + token）
    out = r.execute("run_scheduling", {}, token=sched_token, audit=audit)
    assert "版本" in out and "待审核" in out, out
    vid = int(re.search(r"版本 (\d+)", out).group(1))
    try:
        assert any(e["action"] == "write" and e["subject"] == "e2e-sched"
                   for e in audit._entries), "写操作必须入审计"

        # ② scheduler 调 approve 被拒（RBAC）
        out = r.execute("approve_schedule", {"version_id": vid, "action": "通过"},
                        token=sched_token, audit=audit)
        assert "权限不足" in out

        # ② reviewer 审批通过 -> 版本已审核
        out = r.execute("approve_schedule", {"version_id": vid, "action": "通过"},
                        token=rev_token, audit=audit)
        assert "已审核" in out, out
        v = _rows("SELECT status FROM schedule_versions WHERE id=%s", (vid,))[0]
        assert v["status"] == "已审核"
        # approver 由 token.subject 注入（R8 同款机制）
        a = _rows("SELECT approver, action FROM approvals WHERE schedule_version_id=%s",
                  (vid,))
        assert a and a[0]["approver"] == "e2e-reviewer" and a[0]["action"] == "通过"

        # ⑥ 验收条 14：solver span 含耗时/目标值/约束违反数
        spans = [s for s in tracer._spans if s.name == "solver:run_scheduling"]
        assert spans, "run_scheduling 后 trace 必须含 solver span"
        attrs = spans[-1].attributes
        for k in ("objective", "timed_out", "verify_violations"):
            assert k in attrs, f"solver span 缺属性 {k}"
    finally:
        _exec("DELETE FROM approvals WHERE schedule_version_id=%s", (vid,))
        _exec("DELETE FROM preprocess_tasks WHERE batch_id LIKE %s", (f"{vid}-%",))
        _exec("DELETE FROM batches WHERE schedule_version_id=%s", (vid,))
        _exec("DELETE FROM schedule_versions WHERE id=%s", (vid,))


def test_4_quota_r_d2():
    """④ 验收条 12：同 subject 5min 内第 4 次写操作被拒 + 审计 + tracer span。"""
    r = build_default_registry()
    audit = AuditLogger(log_path=None)
    rev_token = sts.get_token(sts.issue_user_token("e2e-quota", "reviewer"))
    # approve_schedule 是写工具：4 次调用（前 3 次无论业务成败均计数，第 4 次配额拦截）
    outs = [r.execute("approve_schedule", {"version_id": 999999, "action": "通过"},
                      token=rev_token, audit=audit) for _ in range(4)]
    assert "配额超限" in outs[3], outs[3]
    assert any(e["action"] == "quota_exceeded" and e["subject"] == "e2e-quota"
               for e in audit._entries)
    spans = [s for s in tracer._spans if s.name == "quota_exceeded"]
    assert spans and spans[-1].attributes.get("subject") == "e2e-quota"


def test_5_prompt_rollback():
    """⑤ 验收条 13：rollback 生效 + 审计 prompt_rollback。"""
    audit = AuditLogger(log_path=None)
    assert rollback("v1", audit=audit) == "v1"
    assert any(e["action"] == "prompt_rollback" for e in audit._entries)
