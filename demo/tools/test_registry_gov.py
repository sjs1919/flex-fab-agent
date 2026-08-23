"""registry 治理字段 + 11 工具注册测试（M4a T4a.2）。

覆盖：工具数 18（7 旧 + 11 新）、read_only 标记、占位工具 execute、
timeout/max_retries_override 透传（R-1/R-6）。
"""
import pytest

from demo.tools.registry import ToolRegistry, build_default_registry


def test_registry_has_18_tools():
    """--check 口径：7 旧工具 + 11 排产工具 = 18。"""
    r = build_default_registry()
    assert len(r) == 18
    tools = set(r.list_all())
    sched = {"run_scheduling", "query_schedule", "query_sim_events", "approve_schedule",
             "query_ctp", "query_load_assessment", "query_order_tracking",
             "query_preprocess_load", "query_kpi", "query_forecast", "query_yield"}
    assert sched <= tools


def test_read_only_flags():
    """写工具 read_only=False（run_scheduling/approve_schedule），只读=True。"""
    r = build_default_registry()
    assert r.get_schema("run_scheduling").read_only is False
    assert r.get_schema("approve_schedule").read_only is False
    for name in ("query_schedule", "query_sim_events", "query_ctp", "query_kpi",
                 "query_forecast", "query_yield", "query_orders"):
        assert r.get_schema(name).read_only is True, name


def test_placeholder_tools_execute():
    """M5 占位已全部实装：query_forecast/query_yield 均返回真实输出而非占位文案。"""
    r = build_default_registry()
    out = r.execute("query_forecast", {})  # 已实装：预测输出或无历史说明，非 M5 占位
    assert "M5" not in out
    out = r.execute("query_yield", {})     # 已实装：良率报告，非 M5 占位
    assert "M5" not in out and "良率" in out
    # query_ctp 已实装（T4b.3）：缺参返回明确提示而非 M4b 占位文案
    out = r.execute("query_ctp", {})
    assert "M4b" not in out and "参数不完整" in out


def test_search_kb_token_injection(monkeypatch):
    """E6：execute 带 token 时服务端注入 search_knowledge_base（不进 Schema 防伪造）。"""
    from demo.auth.token_exchange import ROLE_PERMISSIONS, Token
    r = build_default_registry()
    schema = r.get_schema("search_knowledge_base")
    assert "token" not in schema.parameters["properties"], "token 不得暴露给 LLM"
    captured = {}

    def _fake_search(query, top_k=3, token=None):
        captured["token"] = token
        return f"ok {query}"

    monkeypatch.setattr("demo.rag.retriever.search_knowledge_base", _fake_search)
    t = Token(subject="李四", role="reviewer",
              permissions=ROLE_PERMISSIONS["reviewer"], source="user")
    r.execute("search_knowledge_base", {"query": "违约金条款"}, token=t)
    assert captured["token"] is t, "白名单工具须收到注入的 token"
    # 无 token -> handler 收到 None（回落 public）
    r.execute("search_knowledge_base", {"query": "违约金条款"})
    assert captured["token"] is None


def test_timeout_override_passthrough(monkeypatch):
    """timeout_override/max_retries_override 透传 run_with_retry（R-6）。"""
    captured = {}

    def _fake_retry(handler, args, tool_name="", timeout=None, max_retries=None):
        captured["timeout"] = timeout
        captured["max_retries"] = max_retries
        return "ok", True, 0

    from demo.tools import sandbox
    monkeypatch.setattr(sandbox, "run_with_retry", _fake_retry)

    r = ToolRegistry()
    r.register("slow_tool", "测试工具", {"type": "object", "properties": {}},
               lambda **kw: "ok", "test", timeout_override=120, max_retries_override=1)
    r.register("normal_tool", "测试工具2", {"type": "object", "properties": {}},
               lambda **kw: "ok", "test")
    r.execute("slow_tool", {})
    assert captured["timeout"] == 120 and captured["max_retries"] == 1
    r.execute("normal_tool", {})
    assert captured["timeout"] is None and captured["max_retries"] is None


def test_run_scheduling_timeout_override():
    """run_scheduling timeout_override=240（> 3 工艺组×60s 串行预算，v2 §7.1 的
    120 按"总预算 60s"假设设定；实际 model 层按工艺分组各 60s，实测墙钟 ~180s，
    沙箱须 > 求解器总预算防先杀）+ max_retries=1（v2 §6 solver 重试降为 1）。"""
    r = build_default_registry()
    s = r.get_schema("run_scheduling")
    assert s.timeout_override == 240
    assert s.max_retries_override == 1
