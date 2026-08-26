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
import logging
import os
import time

# 必须在 import chromadb（其内部 import huggingface_hub）之前设：hub 的 endpoint
# 常量在 import 时冻结，晚了不生效。huggingface.co 直连被墙且 DNS 污染
# （解析到 Facebook 网段 -> SYN_SENT 挂死），统一走国内镜像；模型已缓存时离线可用。
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import chromadb

from ..config import (
    CACHE_THRESHOLD,
    RUNTIME_DIR,
    SEMANTIC_CACHE,
)
from ..core.hf_utils import load_st_embedding

logger = logging.getLogger(__name__)

_DB_DIR = RUNTIME_DIR / "cache_db"
_COLLECTION_NAME = "semantic_cache"
_EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
_collection = None


def is_enabled() -> bool:
    return SEMANTIC_CACHE.lower() != "off"


def _ttl(sensitive: bool) -> int:
    """调用时读 TTL 秒数（运行时可切换，测试可 monkeypatch.setenv；对齐 llm_cache._ttl()）。

    状态类 SEMANTIC_CACHE_STATE_TTL 默认 60（对齐模拟器 tick），知识类
    SEMANTIC_CACHE_TTL 默认 0 = 不过期。禁止 import 时固化（见 config.py 定义处）。
    """
    if sensitive:
        return int(os.getenv("SEMANTIC_CACHE_STATE_TTL", "60"))
    return int(os.getenv("SEMANTIC_CACHE_TTL", "0"))


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
    状态类条目按短 TTL（SEMANTIC_CACHE_STATE_TTL）过期，避免返回过时数据；
    知识类按 SEMANTIC_CACHE_TTL（默认 0 = 不过期，保持现状）。
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
        meta = res["metadatas"][0][0]
        sensitive = bool(meta.get("sensitive", False))
        ttl = _ttl(sensitive)
        ts = meta.get("ts", 0)
        if ttl and (time.time() - float(ts)) > ttl:
            return None  # 已过期视为 miss，走真实执行
        answer = meta.get("answer", "")
        return answer, dist
    return None


def put(query: str, answer: str, sensitive: bool = False) -> None:
    """存入缓存（upsert，同 id 覆盖）。

    sensitive=True 标记为状态类：get 时按短 TTL 过期（SEMANTIC_CACHE_STATE_TTL），
    且 clear_state_entries() 可整体清除（数据变更即失效）。
    """
    if not is_enabled() or not answer:
        return
    col = _get_collection()
    qid = hashlib.md5(query.encode("utf-8")).hexdigest()[:16]
    col.upsert(
        ids=[qid],
        documents=[query],
        metadatas=[{
            "answer": answer,
            "query": query,
            "sensitive": bool(sensitive),
            "ts": time.time(),
        }],
    )


def clear_state_entries() -> None:
    """清空状态类（sensitive=True）语义缓存条目。

    模拟器 tick / 排产完成等数据变更时调用，使状态类缓存立即失效，不等 TTL 自然过期。
    """
    if not is_enabled():
        return
    col = _get_collection()
    if col.count() == 0:
        return
    try:
        col.delete(where={"sensitive": True})
    except Exception as e:  # 清理失败不阻断主流程
        logger.warning("清空状态类语义缓存失败: %s", e)
