"""缓存层 -- 两级缓存减少 LLM API 调用。

  L1 精确缓存（llm_cache.py）：SQLite 存储，相同 prompt 命中 <1ms，0 token
  L2 语义缓存（semantic_cache.py）：Chroma cosine，近义改写命中 ~50ms，省 token
  仅 L2 对无多轮上下文的独立问题生效，避免上下文污染。
"""
from . import llm_cache
from .semantic_cache import get, is_enabled, put

__all__ = ["get", "put", "is_enabled", "llm_cache"]
