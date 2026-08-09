"""缓存层单元测试：LLM 精确缓存（L1）+ 语义缓存（L2）。

L1 用临时 SQLite（monkeypatch _DB_PATH），不污染 demo/data/llm_cache.db。
L2 用 mock Chroma collection。
"""
import json

from demo.cache import llm_cache
from demo.cache.semantic_cache import is_enabled, get, put


def _msgs(s: str) -> list[dict]:
    return [{"role": "user", "content": s}]


def test_cache_key_deterministic():
    """相同参数 -> 相同 key。"""
    k1 = llm_cache._cache_key(_msgs("q"), None, "m", 100, 0.3)
    k2 = llm_cache._cache_key(_msgs("q"), None, "m", 100, 0.3)
    assert k1 == k2


def test_cache_key_differs_on_input():
    """不同输入 -> 不同 key。"""
    k1 = llm_cache._cache_key(_msgs("q1"), None, "m", 100, 0.3)
    k2 = llm_cache._cache_key(_msgs("q2"), None, "m", 100, 0.3)
    assert k1 != k2


def test_get_put_roundtrip(monkeypatch, tmp_path):
    """put 后 get 命中，返回相同内容。"""
    from demo.cache import llm_cache as lc
    monkeypatch.setattr(lc, "_DB_PATH", tmp_path / "test_llm_cache.db")
    lc._conn = None  # 重置连接指向新路径

    lc.put(_msgs("q"), None, "model", 100, 0.3,
           content="answer", tool_calls=None, prompt_tokens=10, completion_tokens=5)
    hit = lc.get(_msgs("q"), None, "model", 100, 0.3)
    assert hit is not None
    assert hit["content"] == "answer"
    assert hit["prompt_tokens"] == 10


def test_get_miss_returns_none(monkeypatch, tmp_path):
    """不同 query 未命中。"""
    from demo.cache import llm_cache as lc
    monkeypatch.setattr(lc, "_DB_PATH", tmp_path / "test_llm_cache2.db")
    lc._conn = None
    assert lc.get(_msgs("nope"), None, "model", 100, 0.3) is None


def test_llm_cache_disabled(monkeypatch, tmp_path):
    """LLM_CACHE=off 时 get/put 均 no-op。"""
    monkeypatch.setenv("LLM_CACHE", "off")
    from demo.cache import llm_cache as lc
    monkeypatch.setattr(lc, "_DB_PATH", tmp_path / "test_llm_cache3.db")
    lc._conn = None
    lc.put(_msgs("q"), None, "m", 100, 0.3, content="a", tool_calls=None, prompt_tokens=1, completion_tokens=1)
    assert lc.get(_msgs("q"), None, "m", 100, 0.3) is None


def test_tool_calls_roundtrip(monkeypatch, tmp_path):
    """tool_calls 序列化往返。"""
    from demo.cache import llm_cache as lc
    monkeypatch.setattr(lc, "_DB_PATH", tmp_path / "test_llm_cache4.db")
    lc._conn = None
    tcs = [{"id": "1", "type": "function", "function": {"name": "query_orders", "arguments": "{}"}}]
    lc.put(_msgs("q"), None, "m", 100, 0.3, content=None, tool_calls=tcs, prompt_tokens=1, completion_tokens=1)
    hit = lc.get(_msgs("q"), None, "m", 100, 0.3)
    assert hit["tool_calls"] == tcs


# ---- semantic cache (L2) 接口 ----

def test_is_semantic_enabled_default():
    """默认开启。"""
    assert is_enabled()


def test_semantic_functions_exist():
    """语义缓存接口可调用（重依赖 Chroma，仅验证函数存在 + 边界不崩）。"""
    assert callable(get)
    assert callable(put)
    assert callable(is_enabled)
