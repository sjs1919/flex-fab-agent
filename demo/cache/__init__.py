"""语义缓存层 -- 相似问题命中缓存则跳过 LLM 调用（#6）。

教学版用 Chroma 独立 collection（cosine），生产换 Redis + 更强中文 embedding。
仅对无多轮上下文的独立问题生效，避免上下文污染。
"""
from .semantic_cache import get, is_enabled, put

__all__ = ["get", "put", "is_enabled"]
