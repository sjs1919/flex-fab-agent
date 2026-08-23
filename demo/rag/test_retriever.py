"""RAG 层单元测试：分块（纯函数）+ RRF 融合 + 重排边界 + E6 权限过滤。"""
import jieba
from rank_bm25 import BM25Okapi

from demo.rag import retriever
from demo.rag.knowledge_base import chunk_text, doc_permission, load_documents
from demo.rag.retriever import bm25_search, rerank, rrf_fuse


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


# ---- E6（M5a）：RAG 文档级权限过滤 ----

def test_doc_permission_mapping():
    """广州航天保密条款 -> confidential；其余/未知 -> public。"""
    assert doc_permission("广州航天精工_合同特殊条款.txt") == "confidential"
    assert doc_permission("历史延期记录.txt") == "public"
    assert doc_permission("未知.txt") == "public"


def test_allowed_sources_roles():
    """admin/reviewer -> confidential+public；其余/无 token -> public。"""
    assert retriever._allowed_sources("admin") == {"public", "confidential"}
    assert retriever._allowed_sources("reviewer") == {"public", "confidential"}
    assert retriever._allowed_sources("viewer") == {"public"}
    assert retriever._allowed_sources("operator") == {"public"}
    assert retriever._allowed_sources(None) == {"public"}


def test_role_from_token_object_and_none():
    """Token 对象 -> role；None -> None；过期 reviewer -> None（回落 public）。"""
    from demo.auth.token_exchange import Token
    assert retriever._role_from_token(None) is None
    assert retriever._role_from_token(
        Token(subject="a", role="admin", permissions=[], source="user")) == "admin"
    assert retriever._role_from_token(
        Token(subject="v", role="viewer", permissions=[], source="user")) == "viewer"
    expired = Token(subject="r", role="reviewer", permissions=[], source="user",
                    expires_at=1)
    assert retriever._role_from_token(expired) is None  # 过期回落 public


def test_role_from_token_string_id():
    """token_id 字符串 -> 复用 STS 解析 role；非法 id -> None（不崩不泄露）。"""
    from demo.auth.token_exchange import STS
    tid = STS().issue_user_token("u-role", "reviewer")
    assert retriever._role_from_token(tid) == "reviewer"
    assert retriever._role_from_token("no-such-token") is None
    assert retriever._role_from_token(object()) is None  # 非 Token 对象回落


class _FakeReranker:
    """假 reranker：全部给 1.0 分，不排序（隔离 1.1GB 重模型）。"""

    def predict(self, pairs):
        return [1.0] * len(pairs)


_CONFIDENTIAL_TEXT = "广州航天精工违约金条款：每逾期一日按合同金额的 5‰ 支付违约金。"
_PUBLIC_DELAY_TEXT = "历史延期记录：深圳精密 2026-05 延期 3 天，违约金按 3‰ 日费率。"
_PUBLIC_NORMAL_TEXT = "普通合同交期条款：如遇不可抗力，交期顺延。"


def _fake_rag():
    """小型 RAG 环境（真实 BM25 + 假 reranker），monkeypatch _ensure_rag/retrieve 使用。"""
    chunks = [_CONFIDENTIAL_TEXT, _PUBLIC_DELAY_TEXT, _PUBLIC_NORMAL_TEXT]
    metas = [{"source": "广州航天精工_合同特殊条款.txt"},
             {"source": "历史延期记录.txt"},
             {"source": "普通合同.txt"}]
    bm25 = BM25Okapi([list(jieba.cut(c)) for c in chunks])
    return None, bm25, chunks, metas, _FakeReranker()


def _patch_rag(monkeypatch):
    """把 RAG 换成小型假环境：检索返回全部 chunk，BM25 走真实小索引。"""
    collection, bm25, chunks, metas, reranker = _fake_rag()

    def _fake_retrieve(collection, query, top_k=10):
        return [{"text": t, "source": m["source"], "distance": i}
                for i, (t, m) in enumerate(zip(chunks, metas))]

    monkeypatch.setattr(retriever, "_ensure_rag",
                        lambda: (collection, bm25, chunks, metas, reranker))
    monkeypatch.setattr(retriever, "retrieve", _fake_retrieve)


def test_search_kb_reviewer_sees_confidential(monkeypatch):
    """reviewer token 检索'违约金条款'命中广州航天保密条款（confidential 放行）。"""
    from demo.auth.token_exchange import Token
    _patch_rag(monkeypatch)
    token = Token(subject="r1", role="reviewer", permissions=[], source="user")
    out = retriever.search_knowledge_base("违约金条款", top_k=3, token=token)
    assert "广州航天精工" in out and "违约金" in out


def test_search_kb_viewer_no_confidential(monkeypatch):
    """viewer token 同问题命不中广州航天保密条款，其余 public 正常返回。"""
    from demo.auth.token_exchange import Token
    _patch_rag(monkeypatch)
    token = Token(subject="v1", role="viewer", permissions=[], source="user")
    out = retriever.search_knowledge_base("违约金条款", top_k=3, token=token)
    assert "广州航天精工" not in out, "viewer 不得命中 confidential 片段"
    assert "历史延期记录" in out  # public 违约金记录正常返回


def test_search_kb_no_token_public_only(monkeypatch):
    """无 token：仅 public，confidential 片段不泄露。"""
    _patch_rag(monkeypatch)
    out = retriever.search_knowledge_base("违约金条款", top_k=3)
    assert "广州航天精工" not in out


def test_search_kb_invalid_token_falls_back_public(monkeypatch):
    """非法 token（乱字符串/过期 Token 对象）回落 public：不崩、不泄露。"""
    from demo.auth.token_exchange import Token
    _patch_rag(monkeypatch)
    out = retriever.search_knowledge_base("违约金条款", top_k=3, token="invalid-token-id")
    assert "广州航天精工" not in out
    expired = Token(subject="r2", role="reviewer", permissions=[], source="user",
                    expires_at=1)
    out2 = retriever.search_knowledge_base("违约金条款", top_k=3, token=expired)
    assert "广州航天精工" not in out2
