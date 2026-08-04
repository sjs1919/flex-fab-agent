"""语义缓存层 -- 相似问题直接返回缓存答案，跳过 LLM 调用（#6）。

教学版用 Chroma 独立 collection（cosine 空间，复用其默认 ONNX MiniLM embedding），
生产换 Redis + 更强的中文 embedding（如 bge-large-zh）。

仅对无多轮上下文的独立问题（thread_id None）生效，避免上下文污染：
多轮对话里同一句话的答案依赖前文，不能复用首轮缓存。

阈值校准（MiniLM cosine distance，越小越相似）：
  完全相同 0.00 · 多标点 0.04 · 近义改写 0.17 · 较远改写 0.37 · 不相关 0.46+
默认 0.20：catches 同义/标点/近义改写，排除较远与不相关。
"""
import hashlib
import os

import chromadb

from ..config import DATA_DIR

_DB_DIR = DATA_DIR / "cache_db"
_COLLECTION_NAME = "semantic_cache"
_collection = None


def is_enabled() -> bool:
    return os.getenv("SEMANTIC_CACHE", "on").lower() != "off"


def _get_collection():
    """懒加载缓存 collection（cosine 空间，持久化到 demo/data/cache_db/）。"""
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=str(_DB_DIR))
        _collection = client.get_or_create_collection(
            _COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
        )
    return _collection


def get(query: str, threshold: float | None = None):
    """查相似问题。

    threshold 为 cosine distance 上限（越小越严）。返回 (answer, distance) 或 None。
    """
    if not is_enabled():
        return None
    col = _get_collection()
    if col.count() == 0:
        return None
    if threshold is None:
        threshold = float(os.getenv("CACHE_THRESHOLD", "0.20"))
    res = col.query(query_texts=[query], n_results=1)
    if not res["ids"][0]:
        return None
    dist = res["distances"][0][0]
    if dist <= threshold:
        answer = res["metadatas"][0][0].get("answer", "")
        return answer, dist
    return None


def put(query: str, answer: str) -> None:
    """存入缓存（upsert，同 id 覆盖）。"""
    if not is_enabled() or not answer:
        return
    col = _get_collection()
    qid = hashlib.md5(query.encode("utf-8")).hexdigest()[:16]
    col.upsert(ids=[qid], documents=[query], metadatas=[{"answer": answer, "query": query}])
