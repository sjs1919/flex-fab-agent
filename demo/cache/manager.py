"""缓存统一入口 -- L1 精确 + L2 语义，两级缓存的 facade（P0-3 改造）。

为什么要有统一入口：
  - L1 / L2 之前各自为政，调用方分别 import 两个模块，自己判断顺序
  - stats / clear 接口不统一，管理困难
  - 新增 L3（如 Redis）时不会继续碎片化

调用方式：
  from ..cache.manager import cache_manager

  # L1 精确缓存（messages 级，嵌在 llm_client 内部用）
  cached = cache_manager.lookup_exact(messages, tools, model, ...)
  if cached: return cached
  cache_manager.store_exact(messages, ..., result)

  # L2 语义缓存（query 级，agent 层用）
  hit = cache_manager.lookup_semantic(query)
  if hit: answer, dist = hit
  cache_manager.store_semantic(query, answer)
"""
from __future__ import annotations

from typing import Any

from . import llm_cache
from . import semantic_cache


class CacheManager:
    """两级缓存统一入口。

    - L1: 精确匹配（SQLite + MD5 key），零 token，<1ms
    - L2: 语义匹配（Chroma + cosine），省 token，~50ms

    两层独立管理，调用方按需选择。
    """

    # ---- L1 精确缓存 ----

    def lookup_exact(self, messages: list[dict], tools: list[dict] | None,
                     model: str, max_tokens: int, temperature: float) -> dict | None:
        """L1 精确查找。命中返回缓存 dict，否则 None。

        返回结构同 llm_cache.get(): {content, tool_calls, prompt_tokens, completion_tokens}
        """
        return llm_cache.get(messages, tools, model, max_tokens, temperature)

    def store_exact(self, messages: list[dict], tools: list[dict] | None,
                    model: str, max_tokens: int, temperature: float,
                    content: str, tool_calls: Any,
                    prompt_tokens: int, completion_tokens: int) -> None:
        """写入 L1 精确缓存。"""
        llm_cache.put(
            messages, tools, model, max_tokens, temperature,
            content=content, tool_calls=tool_calls,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        )

    # ---- L2 语义缓存 ----

    def lookup_semantic(self, query: str, threshold: float | None = None):
        """L2 语义查找。命中返回 (answer, distance)，否则 None。

        Args:
            query: 用户问题
            threshold: cosine distance 上限，不传用默认
        """
        return semantic_cache.get(query, threshold)

    def store_semantic(self, query: str, answer: str) -> None:
        """写入 L2 语义缓存（upsert）。"""
        semantic_cache.put(query, answer)

    def semantic_enabled(self) -> bool:
        """L2 语义缓存是否启用。"""
        return semantic_cache.is_enabled()

    # ---- 统一管理接口 ----

    def stats(self) -> dict:
        """两层缓存统计。"""
        l1_stats = llm_cache.stats()
        return {
            "l1": l1_stats,
            "l2": {
                "enabled": semantic_cache.is_enabled(),
            },
        }

    def clear(self) -> None:
        """清空 L1 精确缓存。L2 语义缓存数据量小且重建成本高，不自动清空。"""
        llm_cache.clear()

    def bump_scene_version(self) -> int:
        """推进场景版本（模拟器每 tick 调用），使状态相关 L1 缓存失效。"""
        return llm_cache.bump_scene_version()

    def get_scene_version(self) -> int:
        """读当前场景版本。"""
        return llm_cache.get_scene_version()


# 模块级单例
cache_manager = CacheManager()
