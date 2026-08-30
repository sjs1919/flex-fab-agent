"""call_llm B3 模型路由测试（T4b.6）。

mock 掉 client/cache/cost，只验证 task_type 路由：策略指定 provider 可用时
优先，否则回落默认遍历顺序（主备降级保持）。不发起真实 LLM 调用。
"""
import pytest

from flex_fab_agent.core import llm_client as lc

# 受控 provider 列表（3 家，含 1 家 disabled）——顺序即默认 fallback 顺序
TEST_PROVIDERS = [
    {"name": "火山豆包(coding)", "enabled": True, "api_key": "k-test", "model": "ark-code-latest"},
    {"name": "DeepSeek", "enabled": True, "api_key": "k-test", "model": "deepseek-v4-flash"},
    {"name": "Kimi(coding)", "enabled": False, "api_key": "k-test", "model": "kimi-for-coding"},
]

_COMPLEX_POLICY = {"simple": "DeepSeek", "complex": "火山豆包(coding)"}


class FakeResponse:
    """模拟 OpenAI ChatCompletion：记录 usage + 返回固定文本。"""

    def __init__(self):
        self.choices = [type("C", (), {"message": type("M", (), {
            "content": "ok", "tool_calls": None})()})()]
        self.usage = type("U", (), {"prompt_tokens": 5, "completion_tokens": 10})()


class FakeClient:
    """按 provider 记录 create() 调用（验证命中顺序）。"""

    def __init__(self, name: str, recorder: list):
        self.name = name
        self.recorder = recorder

    class _Completions:
        def __init__(self, name, recorder):
            self._name = name
            self._recorder = recorder

        def create(self, **kwargs):
            self._recorder.append((self._name, kwargs))
            return FakeResponse()

    @property
    def chat(self):
        return type("Chat", (), {"completions": self._Completions(self.name, self.recorder)})()


@pytest.fixture
def routed(monkeypatch):
    """组装 mock 环境：返回 (recorder, client_pool)，recorder 记录 (provider_name, kwargs)。"""
    recorder: list = []

    def _fake_get_client(p):
        return FakeClient(p["name"], recorder)

    monkeypatch.setattr(lc, "_is_real_key", lambda k: True)
    monkeypatch.setattr(lc, "_get_client", _fake_get_client)
    monkeypatch.setattr(lc.cache_manager, "lookup_exact", lambda *a, **k: None)
    monkeypatch.setattr(lc.cache_manager, "store_exact", lambda *a, **k: None)
    monkeypatch.setattr(lc.cost_tracker, "record",
                        lambda **k: type("E", (), {"cost_total": 0.0})())
    return recorder


def _invoke(task_type: str, policy: dict, monkeypatch):
    monkeypatch.setattr(lc, "PROVIDERS", [dict(p) for p in TEST_PROVIDERS])
    monkeypatch.setattr(lc, "get_routing_policy", lambda: policy)
    lc.call_llm([{"role": "user", "content": "hi"}], task_type=task_type)


def test_complex_prefers_configured_provider(routed, monkeypatch):
    _invoke("complex", _COMPLEX_POLICY, monkeypatch)
    assert routed[0][0] == "火山豆包(coding)"  # 第一个命中被提到最前的 complex 策略


def test_simple_prefers_configured_provider(routed, monkeypatch):
    _invoke("simple", _COMPLEX_POLICY, monkeypatch)
    assert routed[0][0] == "DeepSeek"


def test_no_policy_falls_back_default_order(routed, monkeypatch):
    _invoke("complex", {}, monkeypatch)
    assert routed[0][0] == "火山豆包(coding)"  # 默认列表第一


def test_partial_policy_missing_key_falls_back(routed, monkeypatch):
    """策略只配了 simple，task_type=complex -> 无 preferred -> 默认顺序。"""
    _invoke("complex", {"simple": "DeepSeek"}, monkeypatch)
    assert routed[0][0] == "火山豆包(coding)"


def test_unknown_preferred_falls_back_default_order(routed, monkeypatch):
    _invoke("complex", {"complex": "不存在的provider"}, monkeypatch)
    assert routed[0][0] == "火山豆包(coding)"


def test_preferred_disabled_skipped(routed, monkeypatch):
    """策略指向 disabled provider（Kimi）-> 跳过，走下一个可用（火山豆包）。"""
    _invoke("complex", {"complex": "Kimi(coding)"}, monkeypatch)
    assert routed[0][0] == "火山豆包(coding)"


def test_task_type_default_is_complex(routed, monkeypatch):
    """不传 task_type -> 默认 complex（向后兼容）。"""
    monkeypatch.setattr(lc, "PROVIDERS", [dict(p) for p in TEST_PROVIDERS])
    monkeypatch.setattr(lc, "get_routing_policy", lambda: _COMPLEX_POLICY)
    lc.call_llm([{"role": "user", "content": "hi"}])
    assert routed[0][0] == "火山豆包(coding)"
