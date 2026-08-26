"""LLM 精确缓存 -- SQLite 存储，完全相同 prompt → 直接返回缓存结果（0 token 消耗）。

与语义缓存互补：
  - 精确缓存（本模块）：相同 prompt 命中，<1ms，零 token，适合重复调用
  - 语义缓存（semantic_cache.py）：近义改写命中，~50ms，省 token，适合用户提问

缓存 key = MD5(messages + tools + model + max_tokens + temperature)
缓存值   = (content, tool_calls_json, prompt_tokens, completion_tokens, model)

环境变量：
  LLM_CACHE=on/off   -- 默认 on
  LLM_CACHE_TTL       -- 缓存过期秒数，默认 3600（1 小时），0 永不过期
"""
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

from ..config import RUNTIME_DIR

_DB_PATH = RUNTIME_DIR / "llm_cache.db"
_conn: sqlite3.Connection | None = None

# R-3 scene_version（M3 T3.6）：模拟器每 tick bump 一次，使状态相关查询的
# 精确缓存自动失效（同 prompt 不同版本 -> 不同 key）。默认 0，非模拟场景自洽。
_scene_version: int = 0


def bump_scene_version() -> int:
    """推进场景版本（模拟器每 tick 调用），返回新版本号。"""
    global _scene_version
    _scene_version += 1
    return _scene_version


def get_scene_version() -> int:
    """读当前场景版本。"""
    return _scene_version


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _conn.execute(
            "CREATE TABLE IF NOT EXISTS llm_cache ("
            "  cache_key TEXT PRIMARY KEY,"
            "  content TEXT,"
            "  tool_calls TEXT,"
            "  prompt_tokens INTEGER,"
            "  completion_tokens INTEGER,"
            "  model TEXT,"
            "  created_at REAL"
            ")"
        )
        _conn.commit()
    return _conn


def is_enabled() -> bool:
    """调用时读环境变量（运行时可切换，且测试可 monkeypatch.setenv）。"""
    return os.getenv("LLM_CACHE", "on").lower() != "off"


def _ttl() -> int:
    """调用时读 LLM_CACHE_TTL（秒），默认 3600，0 表示永不过期。"""
    return int(os.getenv("LLM_CACHE_TTL", "3600"))


def _cache_key(messages: list[dict], tools: list[dict] | None,
               model: str, max_tokens: int, temperature: float) -> str:
    """计算缓存 key：MD5(请求参数)。"""
    payload = json.dumps({
        "messages": messages,
        "tools": tools or [],
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "scene_version": _scene_version,
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def get(messages: list[dict], tools: list[dict] | None,
        model: str, max_tokens: int, temperature: float) -> dict | None:
    """查精确缓存。命中返回 {content, tool_calls, prompt_tokens, completion_tokens, model}，未命中返回 None。"""
    if not is_enabled():
        return None
    key = _cache_key(messages, tools, model, max_tokens, temperature)
    conn = _get_conn()
    row = conn.execute(
        "SELECT content, tool_calls, prompt_tokens, completion_tokens, model, created_at "
        "FROM llm_cache WHERE cache_key=?", (key,)
    ).fetchone()
    if not row:
        return None
    # TTL 检查
    ttl = _ttl()
    if ttl > 0 and time.time() - row[5] > ttl:
        conn.execute("DELETE FROM llm_cache WHERE cache_key=?", (key,))
        conn.commit()
        return None
    return {
        "content": row[0],
        "tool_calls": json.loads(row[1]) if row[1] else None,
        "prompt_tokens": row[2],
        "completion_tokens": row[3],
        "model": row[4],
    }


def put(messages: list[dict], tools: list[dict] | None,
        model: str, max_tokens: int, temperature: float,
        content: str, tool_calls: list[dict] | None,
        prompt_tokens: int, completion_tokens: int) -> None:
    """写入精确缓存。"""
    if not is_enabled():
        return
    key = _cache_key(messages, tools, model, max_tokens, temperature)
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO llm_cache VALUES (?,?,?,?,?,?,?)",
        (key, content, json.dumps(tool_calls) if tool_calls else None,
         prompt_tokens, completion_tokens, model, time.time()),
    )
    conn.commit()


def stats() -> dict:
    """缓存统计。"""
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0]
    # 清理过期
    ttl = _ttl()
    expired = 0
    if ttl > 0:
        cutoff = time.time() - ttl
        expired = conn.execute("SELECT COUNT(*) FROM llm_cache WHERE created_at < ?", (cutoff,)).fetchone()[0]
    return {"total": total, "expired": expired, "valid": total - expired, "ttl": ttl}


def clear() -> int:
    """清空缓存，返回删除条数。"""
    conn = _get_conn()
    count = conn.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0]
    conn.execute("DELETE FROM llm_cache")
    conn.commit()
    return count