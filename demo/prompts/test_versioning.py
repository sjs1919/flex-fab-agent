"""Prompt 版本化（R-4，M4a T4a.4）测试。

覆盖：load_system_prompt 返回 v1 全文（与原 system_prompts.py 一致）、
rollback 幂等 + 未知版本报错 + 审计 prompt_rollback。
"""
import pytest

from demo.prompts.system_prompts import SINGLE_AGENT_PROMPT
from demo.prompts.versioning import load_system_prompt, rollback
from demo.auth.audit_logger import AuditLogger


def test_load_v1_matches_legacy_prompt():
    """v1 纯搬家：加载器返回内容与原 SINGLE_AGENT_PROMPT 完全一致。"""
    assert load_system_prompt() == SINGLE_AGENT_PROMPT


def test_rollback_idempotent():
    """rollback("v1") 幂等（当前已是 v1）。"""
    assert rollback("v1") == "v1"
    assert load_system_prompt() == SINGLE_AGENT_PROMPT


def test_rollback_unknown_version_raises():
    with pytest.raises(ValueError, match="未知"):
        rollback("v999")


def test_rollback_audits():
    audit = AuditLogger(log_path=None)
    rollback("v1", audit=audit)
    assert any(e["action"] == "prompt_rollback" for e in audit._entries)
