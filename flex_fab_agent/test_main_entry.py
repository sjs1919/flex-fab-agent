"""main.py 新入口测试（M4a T4a.5）：--check 工具数 18、--rollback、--init-schedule。

LLM/求解均 monkeypatch，聚焦入口路由与输出。
"""
from types import SimpleNamespace

import pytest


def _run_main(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["flex_fab_agent.main"] + argv)
    import flex_fab_agent.main as m
    m.main()


def test_check_prints_tool_count(monkeypatch, capsys):
    monkeypatch.setattr("flex_fab_agent.main.available_providers", lambda: [{"name": "fake"}])
    monkeypatch.setattr("flex_fab_agent.main.get_data_source", lambda: "csv")
    monkeypatch.setattr("flex_fab_agent.main.load_orders", lambda: [])
    import flex_fab_agent.core.llm_client as lc
    monkeypatch.setattr(lc, "call_llm_simple", lambda *a, **k: SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]))
    _run_main(monkeypatch, ["--check"])
    out = capsys.readouterr().out
    assert "工具数：18" in out
    assert "地基自检通过" in out


def test_rollback_ok(monkeypatch, capsys):
    _run_main(monkeypatch, ["--rollback", "v1"])
    out = capsys.readouterr().out
    assert "✅" in out and "v1" in out


def test_rollback_unknown_version(monkeypatch, capsys):
    _run_main(monkeypatch, ["--rollback", "v999"])
    out = capsys.readouterr().out
    assert "❌" in out


def test_init_schedule(monkeypatch, capsys):
    captured = {}

    def _fake(triggered_by="agent"):
        captured["triggered_by"] = triggered_by
        return "✅ 排产完成：版本 1（待审核）"

    monkeypatch.setattr("flex_fab_agent.tools.scheduler_tools.run_scheduling", _fake)
    _run_main(monkeypatch, ["--init-schedule"])
    out = capsys.readouterr().out
    assert "版本 1" in out
    assert captured["triggered_by"] == "init"
