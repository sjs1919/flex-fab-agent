"""缓存层单元测试：LLM 精确缓存（L1）+ 语义缓存（L2）。

L1 用临时 SQLite（monkeypatch _DB_PATH），不污染 flex_fab_agent/data/llm_cache.db。
L2 用 mock Chroma collection。
"""
import json

from flex_fab_agent.cache import llm_cache
from flex_fab_agent.cache.semantic_cache import is_enabled, get, put


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
    from flex_fab_agent.cache import llm_cache as lc
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
    from flex_fab_agent.cache import llm_cache as lc
    monkeypatch.setattr(lc, "_DB_PATH", tmp_path / "test_llm_cache2.db")
    lc._conn = None
    assert lc.get(_msgs("nope"), None, "model", 100, 0.3) is None


def test_llm_cache_disabled(monkeypatch, tmp_path):
    """LLM_CACHE=off 时 get/put 均 no-op。"""
    monkeypatch.setenv("LLM_CACHE", "off")
    from flex_fab_agent.cache import llm_cache as lc
    monkeypatch.setattr(lc, "_DB_PATH", tmp_path / "test_llm_cache3.db")
    lc._conn = None
    lc.put(_msgs("q"), None, "m", 100, 0.3, content="a", tool_calls=None, prompt_tokens=1, completion_tokens=1)
    assert lc.get(_msgs("q"), None, "m", 100, 0.3) is None


def test_tool_calls_roundtrip(monkeypatch, tmp_path):
    """tool_calls 序列化往返。"""
    from flex_fab_agent.cache import llm_cache as lc
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


def test_semantic_cache_chinese_discrimination(monkeypatch, tmp_path):
    """中文区分度回归（踩坑 #14）：近义命中、不同状态问句不误命中。

    MiniLM 时代「有哪些订单在打印？」与「有哪些订单在排队？」距离 0.0（张冠李戴），
    换 bge-small-zh-v1.5 + 阈值 0.25 后必须干净分离。真模型跑（~3s）。
    """
    import flex_fab_agent.cache.semantic_cache as sc
    monkeypatch.setattr(sc, "_DB_DIR", tmp_path / "cache_db")
    sc._collection = None
    try:
        sc.put("有哪些订单在排队？", "排队答案")
        hit = sc.get("哪些订单还在排队？")            # 近义改写 -> 命中
        assert hit is not None and hit[0] == "排队答案"
        assert sc.get("现在有哪些订单在排队") is not None   # 近义改写 -> 命中
        assert sc.get("有哪些订单在打印？") is None        # 不同状态问句 -> 不命中
        assert sc.get("有哪些订单已经打印完成？") is None   # 不同状态问句 -> 不命中
    finally:
        sc._collection = None


class _FakeTime:
    """可控时钟：monkeypatch semantic_cache.time，模拟 TTL 流逝。"""
    def __init__(self) -> None:
        self.now = 1000.0

    def time(self) -> float:
        return self.now


def test_state_sensitive_ttl_expiry(monkeypatch, tmp_path):
    """状态类条目短 TTL：超过 SEMANTIC_CACHE_STATE_TTL 后 get 视为 miss。"""
    import flex_fab_agent.cache.semantic_cache as sc
    monkeypatch.setattr(sc, "_DB_DIR", tmp_path / "cache_db")
    monkeypatch.setenv("SEMANTIC_CACHE_STATE_TTL", "60")
    sc._collection = None
    fake = _FakeTime()
    monkeypatch.setattr(sc, "time", fake)
    try:
        sc.put("订单001状态", "生产中", sensitive=True)
        assert sc.get("订单001状态") is not None        # TTL 内命中
        fake.now += 61                                   # 前进 61s
        assert sc.get("订单001状态") is None             # 过期 miss
    finally:
        sc._collection = None


def test_knowledge_no_expiry(monkeypatch, tmp_path):
    """知识类条目不过期（SEMANTIC_CACHE_TTL=0，现状保持）。"""
    import flex_fab_agent.cache.semantic_cache as sc
    monkeypatch.setattr(sc, "_DB_DIR", tmp_path / "cache_db2")
    monkeypatch.setenv("SEMANTIC_CACHE_TTL", "0")
    sc._collection = None
    fake = _FakeTime()
    monkeypatch.setattr(sc, "time", fake)
    try:
        sc.put("什么是排产", "排产是排程排产的意思", sensitive=False)
        fake.now += 100000                              # 很久以后
        assert sc.get("什么是排产") is not None          # 仍命中
    finally:
        sc._collection = None


def test_clear_state_entries_keeps_knowledge(monkeypatch, tmp_path):
    """clear_state_entries() 只删状态类条目，知识类保留。"""
    import flex_fab_agent.cache.semantic_cache as sc
    monkeypatch.setattr(sc, "_DB_DIR", tmp_path / "cache_db3")
    sc._collection = None
    try:
        sc.put("订单001状态", "生产中", sensitive=True)
        sc.put("什么是排产", "排产是排程排产的意思", sensitive=False)
        sc.clear_state_entries()
        assert sc.get("订单001状态") is None             # 状态类已删
        assert sc.get("什么是排产") is not None           # 知识类保留
    finally:
        sc._collection = None
