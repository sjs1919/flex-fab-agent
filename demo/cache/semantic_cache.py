"""语义缓存层 -- 相似问题直接返回缓存答案，跳过 LLM 调用（#6）。

Chroma collection（cosine 空间）+ bge-small-zh-v1.5 中文 embedding（本地
sentence-transformers，~95MB；torch/sentence-transformers 依赖项目已装）。

仅对无多轮上下文的独立问题（thread_id None）生效，避免上下文污染：
多轮对话里同一句话的答案依赖前文，不能复用首轮缓存。

⚠️ 踩坑 #14（2026-08-24 实证）：Chroma 默认 MiniLM 对中文短问句几乎无区分度
（「有哪些订单在打印？」与「有哪些订单在排队？」距离 0.0，缓存张冠李戴），
必须用中文 embedding。换 embedding 模型后**必须清 demo/data/cache_db**
（向量维度/语义空间不同，旧缓存不可比）。

阈值校准（bge-small-zh cosine distance，越小越相似）：
  完全相同 0.00 · 近义改写 0.05~0.23 · 不同状态问句 0.32+ · 不相关 0.60+
默认 0.25：catches 同义/标点/近义改写，排除不同义问句。
"""
import hashlib
import os

# 必须在 import chromadb（其内部 import huggingface_hub）之前设：hub 的 endpoint
# 常量在 import 时冻结，晚了不生效。huggingface.co 直连被墙且 DNS 污染
# （解析到 Facebook 网段 -> SYN_SENT 挂死），统一走国内镜像；模型已缓存时离线可用。
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import chromadb

from ..config import RUNTIME_DIR, SEMANTIC_CACHE, CACHE_THRESHOLD
from ..core.hf_utils import load_st_embedding

_DB_DIR = RUNTIME_DIR / "cache_db"
_COLLECTION_NAME = "semantic_cache"
_EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
_collection = None


def is_enabled() -> bool:
    return SEMANTIC_CACHE.lower() != "off"


def _get_collection():
    """懒加载缓存 collection（cosine 空间，持久化到 demo/data/cache_db/）。"""
    global _collection
    if _collection is None:
        ef = load_st_embedding(_EMBEDDING_MODEL)
        client = chromadb.PersistentClient(path=str(_DB_DIR))
        _collection = client.get_or_create_collection(
            _COLLECTION_NAME, metadata={"hnsw:space": "cosine"},
            embedding_function=ef,
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
        threshold = CACHE_THRESHOLD
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
