"""合同知识库 -- 文档加载 + 分块 + Chroma 向量库。

数据在 demo/data/：
  contracts/             3 份合同特殊条款 txt
  历史延期记录.txt        历史延期案例
  chroma_db/             已灌好的 Chroma 向量库（直接复用，无需重建）

Embedding 模型：BAAI/bge-small-zh-v1.5（中文效果好，与语义缓存层统一，
避免 Chroma 默认 all-MiniLM-L6-v2（英文）对中文检索质量差的问题。
首次构建自动灌库，已缓存模型则零联网。
"""
import logging
from pathlib import Path

import chromadb

from ..config import DATA_DIR, RUNTIME_DIR
from ..core.hf_utils import load_st_embedding

logger = logging.getLogger(__name__)

DB_DIR = RUNTIME_DIR / "chroma_db"
CONTRACTS_DIR = DATA_DIR / "contracts"
DELAY_RECORD = DATA_DIR / "历史延期记录.txt"
COLLECTION_NAME = "kb_contracts_delay"
EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"

# E6（M5a）：文档级权限映射。缺省 public，仅列出的文件受限。
# 广州航天精工合同特殊条款含违约金等敏感条款，仅 admin/reviewer 可检索。
DOC_PERMISSION: dict[str, str] = {"广州航天精工_合同特殊条款.txt": "confidential"}


def doc_permission(source: str) -> str:
    """返回文档权限：confidential（机密）或 public（公开）。"""
    return DOC_PERMISSION.get(source, "public")


_embedding_function = None


def _get_ef():
    """单例懒加载 embedding function。"""
    global _embedding_function
    if _embedding_function is None:
        _embedding_function = load_st_embedding(EMBEDDING_MODEL)
    return _embedding_function


def load_documents() -> list[tuple[str, str]]:
    """加载知识库文档：历史延期记录 + contracts/ 下所有合同 txt。返回 [(filename, text)]。"""
    docs = []
    if DELAY_RECORD.exists():
        docs.append((DELAY_RECORD.name, DELAY_RECORD.read_text(encoding="utf-8")))
    for f in sorted(CONTRACTS_DIR.glob("*.txt")):
        docs.append((f.name, f.read_text(encoding="utf-8")))
    return docs


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> list[str]:
    """字符级滑动窗口分块。overlap 解决关键句被切在边界的问题。"""
    chunks = []
    start = 0
    step = max(1, chunk_size - overlap)
    while start < len(text):
        chunk = text[start:start + chunk_size]
        if chunk.strip():
            chunks.append(chunk)
        if start + chunk_size >= len(text):
            break
        start += step
    return chunks


def get_or_build_vectorstore():
    """获取或构建 Chroma 向量库：已有数据则复用，否则加载->分块->灌入。"""
    ef = _get_ef()
    client = chromadb.PersistentClient(path=str(DB_DIR))
    collection = client.get_or_create_collection(
        COLLECTION_NAME, embedding_function=ef
    )

    if collection.count() > 0:
        logger.info("向量库已有 %d 条向量，直接复用（%s/）", collection.count(), DB_DIR.name)
        return collection

    logger.info("首次构建向量库：加载文档 -> 分块 -> 向量化 -> 灌入")
    docs = load_documents()
    if not docs:
        raise RuntimeError(f"知识库为空，请检查 {DATA_DIR}")
    ids, texts, metas = [], [], []
    for doc_idx, (filename, text) in enumerate(docs):
        for chunk_idx, chunk in enumerate(chunk_text(text)):
            ids.append(f"doc{doc_idx}_chunk{chunk_idx}")
            texts.append(chunk)
            metas.append({"source": filename})
    collection.add(ids=ids, documents=texts, metadatas=metas)
    logger.info("灌入 %d 个文本块（来自 %d 个文档）", len(ids), len(docs))
    return collection


def retrieve(collection, query: str, top_k: int = 3) -> list[dict]:
    """纯向量检索：query -> Chroma 找 top-k。返回 [{text, source, distance, rank}]。"""
    results = collection.query(query_texts=[query], n_results=top_k)
    hits = []
    for doc, meta, dist in zip(
        results["documents"][0], results["metadatas"][0], results["distances"][0]
    ):
        hits.append({"text": doc, "source": meta.get("source", "?"), "distance": dist})
    return hits
