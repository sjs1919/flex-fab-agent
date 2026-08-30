"""混合检索 -- 向量 + BM25(RRF 融合) + Cross-Encoder 重排。

为什么混合：
  纯向量（MiniLM）中文召回弱（top1 常召回"历史延期记录"而非目标合同）。
  BM25 补关键词精确匹配（"广州航天"必须字面命中），RRF 融合两路排名，
  Cross-Encoder 对 (query, chunk) 精排，把目标合同顶到 top1。

search_knowledge_base 是暴露给 Agent 的工具函数，懒加载向量库/reranker
（首次调用才加载 ~1.1GB reranker，之后秒载）。
"""
import logging
import os

import jieba
from rank_bm25 import BM25Okapi

from ..core.hf_utils import load_cross_encoder
from .knowledge_base import doc_permission, get_or_build_vectorstore, retrieve

logger = logging.getLogger(__name__)

RERANKER_MODEL = "BAAI/bge-reranker-base"
# reranker 未缓存时走 Clash 代理下载（LLM 调用不受影响，用 trust_env=False 直连）
_PROXY = os.environ.get("HTTPS_PROXY", os.environ.get("HTTP_PROXY", "http://127.0.0.1:7890"))

# E6（M5a）：confidential 文档仅 admin/reviewer 可检，其余角色/无 token 仅 public。
CONFIDENTIAL_ROLES = {"admin", "reviewer"}

_rag_state = None  # 懒加载单例：(collection, bm25, chunks, metas, reranker)


def load_reranker(model_name: str = RERANKER_MODEL):
    """加载 Cross-Encoder reranker（离线优先 + 代理回落）。"""
    logger.info("加载 reranker（%s）...", model_name)
    model = load_cross_encoder(model_name, proxy=_PROXY)
    logger.info("reranker 就绪")
    return model


def build_bm25_index(collection) -> tuple:
    """从向量库取出全部 chunk，jieba 分词后建 BM25 索引。返回 (bm25, chunks, metas)。"""
    data = collection.get(include=["documents", "metadatas"])
    chunks = data["documents"]
    metas = data["metadatas"]
    tokenized = [list(jieba.cut(c)) for c in chunks]
    bm25 = BM25Okapi(tokenized)
    logger.info("BM25 索引建好：%d 个 chunk", len(chunks))
    return bm25, chunks, metas


def bm25_search(bm25, chunks, metas, query, top_k=10) -> list[dict]:
    """BM25 检索：query 分词 -> 算分 -> 取 top_k。"""
    query_tokens = list(jieba.cut(query))
    scores = bm25.get_scores(query_tokens)
    ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    hits = []
    for idx, score in ranked[:top_k]:
        if score <= 0:
            continue
        hits.append({"text": chunks[idx], "source": metas[idx].get("source", "?"),
                     "score": float(score), "rank": len(hits) + 1})
    return hits


def rrf_fuse(vector_hits, bm25_hits, k=60, top_k=10) -> list[dict]:
    """RRF 融合：两路结果按排名打分 1/(k+rank)，相同 chunk 分数累加。"""
    scores, info = {}, {}
    for h in vector_hits:
        key = h["text"]
        scores[key] = scores.get(key, 0) + 1.0 / (k + h.get("rank", 1))
        info[key] = {"text": h["text"], "source": h["source"]}
    for h in bm25_hits:
        key = h["text"]
        scores[key] = scores.get(key, 0) + 1.0 / (k + h.get("rank", 1))
        info[key] = {"text": h["text"], "source": h["source"]}
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    result = []
    for key, score in ranked[:top_k]:
        item = dict(info[key])
        item["rrf_score"] = score
        result.append(item)
    return result


def rerank(reranker, query, candidates, top_k=3) -> list[dict]:
    """Cross-Encoder 重排：对每个 (query, chunk) 对算相关分，按分排序取 top_k。"""
    if not candidates:
        return []
    pairs = [[query, c["text"]] for c in candidates]
    scores = reranker.predict(pairs)
    ranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
    result = []
    for c, score in ranked[:top_k]:
        item = dict(c)
        item["rerank_score"] = float(score)
        result.append(item)
    return result


def _role_from_token(token) -> str | None:
    """从 token 解析角色；无 token/非法/过期回落 None（仅 public，不泄露）。"""
    from ..auth.token_exchange import STS, Token
    if token is None:
        return None
    if isinstance(token, Token):
        return None if token.is_expired() else token.role
    if isinstance(token, str):
        resolved = STS().get_token(token)
        return resolved.role if resolved else None
    return None


def _allowed_sources(role: str | None) -> set[str]:
    """角色 -> 允许的文档权限集。admin/reviewer -> confidential+public；其余 -> public。"""
    return {"public", "confidential"} if role in CONFIDENTIAL_ROLES else {"public"}


def retrieve_hybrid(collection, bm25, chunks, metas, reranker, query, top_k=3,
                    allowed_perms: set[str] | None = None) -> list[dict]:
    """混合检索四步：向量召回 -> BM25 召回 -> RRF 融合 -> 权限过滤 -> Cross-Encoder 精排。

    E6（M5a）：allowed_perms 权限过滤发生在融合后、重排前，越权片段不进 rerank
    （防 reranker 因保密片段相关度高把它顶上去）。None = 不过滤（内部直调用）。
    """
    vector_hits = retrieve(collection, query, top_k=10)
    for i, h in enumerate(vector_hits, 1):
        h["rank"] = i
    bm25_hits = bm25_search(bm25, chunks, metas, query, top_k=10)
    fused = rrf_fuse(vector_hits, bm25_hits, k=60, top_k=10)
    if allowed_perms is not None:
        fused = [h for h in fused if doc_permission(h["source"]) in allowed_perms]
    return rerank(reranker, query, fused, top_k=top_k)


def _ensure_rag():
    """懒加载 RAG 组件（向量库 + BM25 + reranker），首次调用才初始化。"""
    global _rag_state
    if _rag_state is None:
        collection = get_or_build_vectorstore()
        bm25, chunks, metas = build_bm25_index(collection)
        reranker = load_reranker()
        _rag_state = (collection, bm25, chunks, metas, reranker)
    return _rag_state


def search_knowledge_base(query: str, top_k: int = 3, token=None) -> str:
    """搜索合同知识库（混合检索 + 重排）。Agent 工具函数。

    E6（M5a）：token -> 角色 -> 文档权限过滤（admin/reviewer 可检 confidential，
    其余角色/无 token 仅 public）。过滤在重排前，越权片段不进 rerank。
    无 token/非法 token 回落 public（不崩、不泄露）。

    Args:
        query: 检索问题，如"广州航天合同有什么特殊条款"
        top_k: 返回最相关片段数，默认 3
        token: Token 对象或 token_id（可选）；用于文档级权限过滤
    """
    allowed = _allowed_sources(_role_from_token(token))
    collection, bm25, chunks, metas, reranker = _ensure_rag()
    hits = retrieve_hybrid(collection, bm25, chunks, metas, reranker, query,
                           top_k=top_k, allowed_perms=allowed)
    if not hits:
        return "知识库中未找到相关条款。"
    lines = [f"命中 {len(hits)} 条合同条款（按相关性排序）：\n"]
    for i, h in enumerate(hits, 1):
        lines.append(f"【片段{i}】(来源:{h['source']}  rerank分:{h['rerank_score']:.4f})")
        lines.append(h["text"])
        lines.append("")
    return "\n".join(lines)
