"""合同知识库 -- 文档加载 + 分块 + Chroma 向量库。

数据在 demo/data/：
  contracts/             3 份合同特殊条款 txt
  历史延期记录.txt        历史延期案例
  chroma_db/             已灌好的 Chroma 向量库（直接复用，无需重建）

为什么复用现成向量库：
  灌库要跑 onnx embedding（~80MB），首次构建慢。chroma_db/ 已有数据，
  get_or_build_vectorstore 检测到非空直接复用，开箱即跑。
"""
from pathlib import Path

import chromadb

from ..config import DATA_DIR

DB_DIR = DATA_DIR / "chroma_db"
CONTRACTS_DIR = DATA_DIR / "contracts"
DELAY_RECORD = DATA_DIR / "历史延期记录.txt"
COLLECTION_NAME = "kb_contracts_delay"


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
    client = chromadb.PersistentClient(path=str(DB_DIR))
    collection = client.get_or_create_collection(COLLECTION_NAME)

    if collection.count() > 0:
        print(f"  ♻️  向量库已有 {collection.count()} 条向量，直接复用（{DB_DIR.name}/）")
        return collection

    print("  📥 首次构建向量库：加载文档 -> 分块 -> 向量化 -> 灌入")
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
    print(f"  ✅ 灌入 {len(ids)} 个文本块（来自 {len(docs)} 个文档）")
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
