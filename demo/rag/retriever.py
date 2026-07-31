"""混合检索 -- 向量 + BM25(RRF 融合) + Cross-Encoder 重排。

为什么混合：
  纯向量（MiniLM）中文召回弱（top1 常召回"历史延期记录"而非目标合同）。
  BM25 补关键词精确匹配（"广州航天"必须字面命中），RRF 融合两路排名，
  Cross-Encoder 对 (query, chunk) 精排，把目标合同顶到 top1。

search_knowledge_base 是暴露给 Agent 的工具函数，懒加载向量库/reranker
（首次调用才加载 ~1.1GB reranker，之后秒载）。
"""
import os

import jieba
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

from .knowledge_base import get_or_build_vectorstore, retrieve

RERANKER_MODEL = "BAAI/bge-reranker-base"
# reranker 未缓存时走 Clash 代理下载（LLM 调用不受影响，用 trust_env=False 直连）
_PROXY = os.environ.get("HTTPS_PROXY", os.environ.get("HTTP_PROXY", "http://127.0.0.1:7890"))

_rag_state = None  # 懒加载单例：(collection, bm25, chunks, metas, reranker)


def load_reranker(model_name: str = RERANKER_MODEL) -> CrossEncoder:
    """加载 Cross-Encoder reranker。

    离线优先：已缓存则跳过 HF 联网 HEAD 检查（避免代理 SSL EOF）。
    关键坑：huggingface_hub 在 import 时把 HF_HUB_OFFLINE 固化到 constants，
    运行时设 os.environ 无效，必须直接 patch constants 才能跳过 HEAD
    （否则每个 modules.json HEAD 要等 Windows TCP 超时 ~21s ×5 retry）。
    未缓存则走 Clash 代理 3450 从 HF 下载，之后秒载。
    """
    print(f"  ⏬ 加载 reranker（{model_name}）...")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        import huggingface_hub.constants as _hf_const
        _hf_const.HF_HUB_OFFLINE = True
    except Exception:
        pass
    try:
        model = CrossEncoder(model_name)
        print("  ✅ reranker 就绪（离线缓存）")
        return model
    except Exception as offline_err:
        # 离线失败（未缓存）-> 走代理下载
        os.environ.pop("HF_HUB_OFFLINE", None)
        os.environ.pop("TRANSFORMERS_OFFLINE", None)
        try:
            import huggingface_hub.constants as _hf_const
            _hf_const.HF_HUB_OFFLINE = False
        except Exception:
            pass
        os.environ["HTTPS_PROXY"] = _PROXY
        os.environ["HTTP_PROXY"] = _PROXY
        try:
            model = CrossEncoder(model_name)
        except Exception as e:
            raise RuntimeError(
                f"reranker 加载失败（离线: {offline_err}; 代理: {e}）\n"
                f"可能原因：① 模型未缓存且 Clash 代理未开（3450）；② 网络不通。"
            )
        finally:
            os.environ.pop("HTTPS_PROXY", None)
            os.environ.pop("HTTP_PROXY", None)
        print("  ✅ reranker 就绪（走代理下载并缓存）")
        return model


def build_bm25_index(collection) -> tuple:
    """从向量库取出全部 chunk，jieba 分词后建 BM25 索引。返回 (bm25, chunks, metas)。"""
    data = collection.get(include=["documents", "metadatas"])
    chunks = data["documents"]
    metas = data["metadatas"]
    tokenized = [list(jieba.cut(c)) for c in chunks]
    bm25 = BM25Okapi(tokenized)
    print(f"  📚 BM25 索引建好：{len(chunks)} 个 chunk")
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


def retrieve_hybrid(collection, bm25, chunks, metas, reranker, query, top_k=3) -> list[dict]:
    """混合检索四步：向量召回 -> BM25 召回 -> RRF 融合 -> Cross-Encoder 精排。"""
    vector_hits = retrieve(collection, query, top_k=10)
    for i, h in enumerate(vector_hits, 1):
        h["rank"] = i
    bm25_hits = bm25_search(bm25, chunks, metas, query, top_k=10)
    fused = rrf_fuse(vector_hits, bm25_hits, k=60, top_k=10)
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


def search_knowledge_base(query: str, top_k: int = 3) -> str:
    """搜索合同知识库（混合检索 + 重排）。Agent 工具函数。

    Args:
        query: 检索问题，如"广州航天合同有什么特殊条款"
        top_k: 返回最相关片段数，默认 3
    """
    collection, bm25, chunks, metas, reranker = _ensure_rag()
    hits = retrieve_hybrid(collection, bm25, chunks, metas, reranker, query, top_k=top_k)
    if not hits:
        return "知识库中未找到相关条款。"
    lines = [f"命中 {len(hits)} 条合同条款（按相关性排序）：\n"]
    for i, h in enumerate(hits, 1):
        lines.append(f"【片段{i}】(来源:{h['source']}  rerank分:{h['rerank_score']:.4f})")
        lines.append(h["text"])
        lines.append("")
    return "\n".join(lines)
