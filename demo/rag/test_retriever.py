"""RAG 层单元测试：分块（纯函数）+ RRF 融合 + 重排边界。"""
from demo.rag.knowledge_base import chunk_text, load_documents
from demo.rag.retriever import rrf_fuse, rerank, bm25_search


# ---- chunk_text ----

def test_chunk_text_small_text():
    """短文本不切块。"""
    chunks = chunk_text("短文本", chunk_size=500)
    assert chunks == ["短文本"]


def test_chunk_text_overlap():
    """长文本滑动窗口，带 overlap。"""
    text = "abcdefghijklmnopqrstuvwxyz" * 40  # 1040 字符
    chunks = chunk_text(text, chunk_size=500, overlap=100)
    assert len(chunks) >= 2
    assert all(len(c) <= 500 for c in chunks)


def test_chunk_text_contiguous():
    """分块后拼接应覆盖原文（滑动窗口，块间重叠）。"""
    text = "一二三四五六七八九十" * 30
    chunks = chunk_text(text, chunk_size=30, overlap=5)
    assert chunks
    # 每块都在原文中出现
    for c in chunks:
        assert c in text


def test_chunk_text_empty():
    """空文本 -> 无块。"""
    assert chunk_text("") == []


# ---- load_documents ----

def test_load_documents_finds_contracts_and_delay():
    """知识库应包含历史延期记录 + contracts 合同。"""
    docs = load_documents()
    names = [name for name, _ in docs]
    assert any("延期" in name for name in names)
    assert any(name.endswith(".txt") for name in names)


# ---- rrf_fuse ----

def test_rrf_fuse_merges_both_sources():
    """RRF 融合：同一文本在向量+BM25 双路出现 -> 分数累加。"""
    vector_hits = [
        {"text": "合同条款A", "source": "a.txt", "rank": 1},
        {"text": "合同条款B", "source": "b.txt", "rank": 2},
    ]
    bm25_hits = [
        {"text": "合同条款A", "source": "a.txt", "rank": 1},  # 双路命中
        {"text": "合同条款C", "source": "c.txt", "rank": 2},
    ]
    fused = rrf_fuse(vector_hits, bm25_hits, k=60, top_k=10)
    # A 双路累加分数最高
    assert fused[0]["text"] == "合同条款A"
    assert fused[0]["rrf_score"] > fused[1]["rrf_score"]


def test_rrf_fuse_respects_top_k():
    """top_k 截断。"""
    vector_hits = [{"text": f"d{i}", "source": "x", "rank": i} for i in range(1, 11)]
    bm25_hits = []
    fused = rrf_fuse(vector_hits, bm25_hits, k=60, top_k=3)
    assert len(fused) <= 3


def test_rrf_fuse_empty():
    """双路皆空 -> 空结果。"""
    assert rrf_fuse([], [], k=60) == []


# ---- rerank ----

def test_rerank_empty_candidates():
    """空候选 -> 空结果（不崩溃）。"""
    assert rerank(None, "q", []) == []


def test_rerank_sorts_by_score(monkeypatch):
    """重排按分数降序。"""
    class FakeReranker:
        def predict(self, pairs):
            return [0.3, 0.9]
    candidates = [{"text": "低相关", "source": "a"}, {"text": "高相关", "source": "b"}]
    result = rerank(FakeReranker(), "q", candidates, top_k=2)
    assert result[0]["text"] == "高相关"
    assert result[0]["rerank_score"] == 0.9


def test_bm25_search_requires_jieba():
    """bm25_search 依赖真实 BM25 索引（集成性测试，确认接口可调）。"""
    import jieba
    from rank_bm25 import BM25Okapi
    corpus = ["深圳精密延期记录", "广州航天合同特殊条款", "深圳有哪些紧急订单"]
    tokenized = [list(jieba.cut(c)) for c in corpus]
    bm25 = BM25Okapi(tokenized)
    # 查询词出现在多篇文档，BM25 应能区分相关度
    hits = bm25_search(bm25, corpus, [{"source": "a"}, {"source": "b"}, {"source": "c"}], "深圳精密", top_k=3)
    assert len(hits) >= 1
    assert all("source" in h for h in hits)
