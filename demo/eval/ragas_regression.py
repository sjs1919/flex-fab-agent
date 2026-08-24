"""RAG 四指标回归（M5a T5a.15⑦，验收条 75）。

基线（docs/demo/09-reports/评测报告-RAG质量-ragas-v1-2026-08-21.md，Q1-Q5）：
  context_precision 0.60 / faithfulness 0.80 / answer_relevancy 0.80 / context_recall 0.90

评估对象为重构后 demo/rag 管线（E5 调参 + E6 权限过滤后的 retrieve_hybrid）。
四指标方法同 scripts/week4/ragas_eval.py（RAGAS 方法论 LLM-as-Judge 手写实现）；
Q2/Q4 涉保密文档（广州航天精工），用 reviewer 子 Token 检索（confidential 可检）。

用法：python -m demo.eval.ragas_regression（真实 LLM API，单独执行，不入 run_all_tests）
"""
import json
import re

from ..core.llm_client import call_llm_simple
from ..rag.retriever import (
    build_bm25_index,
    get_or_build_vectorstore,
    load_reranker,
    retrieve_hybrid,
)

# 基线：重构前 ragas 评测均值（验收清单 §0：四指标回归不劣化）
BASELINE = {
    "context_precision": 0.60,
    "faithfulness": 0.80,
    "answer_relevancy": 0.80,
    "context_recall": 0.90,
}

RAG_ANSWER_PROMPT = """你是 3D 打印/CNC 加工生产调度助手。
请只根据下方"检索片段"回答用户问题，不要凭空编造。
规则：
- 完整覆盖问题所问的所有要点（子问题全部答到），但不要展开问题未问及的内容
- 若检索片段中有相关条款，引用其来源文件回答
- 若检索片段中没有相关信息，明确说"知识库中未找到相关条款"
- 回答简洁专业，用中文
"""

# Q1-Q5 与基线评测完全一致（scripts/week4/ragas_eval.py GROUND_TRUTH）
GROUND_TRUTH = [
    {
        "id": "Q1",
        "question": "深圳精密五金合同中，逾期赔付比例是多少？累计逾期多少天可以解约？",
        "answer": "逾期按订单金额的0.5%/日赔付；累计逾期超过5个工作日，客户可解除合同。",
    },
    {
        "id": "Q2",
        "question": "广州航天精工对不合格件如何处理？",
        "answer": "实行100%全检（不抽检），不合格件直接报废，不得返工或让步接收，报废费用由供方承担。",
    },
    {
        "id": "Q3",
        "question": "东莞模具厂的大批量订单有什么折扣？",
        "answer": "单批次500件以上享95折，1000件以上享9折，折扣不与加急费叠加。",
    },
    {
        "id": "Q4",
        "question": "广州航天精工的加工精度要求是什么？",
        "answer": "采用五轴CNC加工，尺寸公差±0.01mm，致密度≥99.5%。",
    },
    {
        "id": "Q5",
        "question": "历史延期记录中，广州航天精工那次延期总共赔付了多少？",
        "answer": "报废件费用36000元由供方承担，另按1%/日赔付订单金额2%共15000元，合计51000元。",
    },
]


def _llm_json(system_prompt: str, user_prompt: str, max_tokens: int = 800) -> dict:
    """LLM 返回解析后的 JSON。解析失败重试一次（追加只输出 JSON 指令）。"""
    for attempt in range(2):
        resp = call_llm_simple(system_prompt, user_prompt,
                               max_tokens=max_tokens, temperature=0.0)
        raw = (resp.choices[0].message.content or "").strip()
        m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
        payload = m.group(1).strip() if m else raw
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            if attempt == 0:
                user_prompt = user_prompt + "\n\n（请只输出合法 JSON，不要任何解释文字）"
            else:
                return {}
    return {}


def average_precision(relevance: list[bool]) -> float:
    """Average Precision：相关片段排得越靠前分越高。无相关片段返回 0。"""
    relevant = sum(relevance)
    if not relevant:
        return 0.0
    cum, ap_sum = 0, 0.0
    for i, rel in enumerate(relevance, 1):
        if rel:
            cum += 1
            ap_sum += cum / i
    return ap_sum / relevant


# ---- 指标 1：faithfulness（答案陈述被检索内容支持的比例） ----

def faithfulness(answer: str, contexts: list[str]) -> float:
    if not answer.strip():
        return 0.0
    stmts = _llm_json(
        "你是事实抽取助手。把给定回答拆成【原子事实陈述】（每条只含一个事实）。"
        '输出 JSON：{"statements": ["陈述1", "陈述2", ...]}。',
        f"回答：\n{answer}")
    statements = stmts.get("statements", [])
    if not statements:
        return 0.0
    context_text = "\n---\n".join(f"[片段{i}] {c}" for i, c in enumerate(contexts, 1))
    judge = _llm_json(
        "你是事实核查员。对每条【陈述】，判断它能否从【检索内容】直接推出或被支持。\n"
        "能推出 -> supported=true；未提及/矛盾/需外部知识 -> supported=false。\n"
        '输出 JSON：{"results": [{"statement": "...", "supported": true/false}]}。',
        f"检索内容：\n{context_text}\n\n待核查陈述：\n"
        f"{json.dumps(statements, ensure_ascii=False)}")
    results = judge.get("results", [])
    supported = sum(1 for r in results if r.get("supported"))
    return supported / len(statements) if statements else 0.0


# ---- 指标 2：answer_relevancy（由答案反推问题与原问题主题一致率） ----

def answer_relevancy(question: str, answer: str) -> float:
    if not answer.strip():
        return 0.0
    rq = _llm_json(
        "根据给定【回答】，反推它可能在回答什么问题。生成 2 个不同角度的问题。"
        '输出 JSON：{"questions": ["问题1", "问题2"]}。问题只基于回答内容。',
        f"回答：\n{answer}")
    reverse_qs = rq.get("questions", [])[:2]
    if not reverse_qs:
        return 0.0
    judge = _llm_json(
        "判断【反推问题】与【原问题】是否在问【同一主题】（宽松匹配，抓核心意图）。\n"
        "主体/主题一致即 match=true（多带细节不算否定）；明显主题偏移才 match=false。\n"
        '输出 JSON：{"results": [{"reverse": "...", "match": true/false}]}。',
        f"原问题：{question}\n\n反推问题列表：\n"
        f"{json.dumps(reverse_qs, ensure_ascii=False)}")
    matches = sum(1 for r in judge.get("results", []) if r.get("match"))
    return matches / len(reverse_qs)


# ---- 指标 3：context_precision（相关片段是否排在前面，AP） ----

def context_precision(contexts: list[str], ground_truth: str) -> float:
    if not contexts:
        return 0.0
    judge = _llm_json(
        "判断每个【检索片段】对回答【标准答案】是否有用（含答案所需关键事实）。"
        '输出 JSON：{"results": [{"index": 1, "relevant": true/false}]}。index 从 1 开始。',
        f"标准答案：\n{ground_truth}\n\n检索片段：\n"
        + "\n".join(f"[{i}] {c}" for i, c in enumerate(contexts, 1)))
    results = judge.get("results", [])
    flags = []
    for i in range(1, len(contexts) + 1):
        r = next((x for x in results if x.get("index") == i), None)
        flags.append(bool(r.get("relevant")) if r else False)
    return average_precision(flags)


# ---- 指标 4：context_recall（标准答案陈述被检索到的比例） ----

def context_recall(ground_truth: str, contexts: list[str]) -> float:
    stmts = _llm_json(
        "你是事实抽取助手。把给定【标准答案】拆成【原子事实陈述】。"
        '输出 JSON：{"statements": ["陈述1", ...]}。',
        f"标准答案：\n{ground_truth}")
    statements = stmts.get("statements", [])
    if not statements:
        return 0.0
    context_text = "\n---\n".join(f"[片段{i}] {c}" for i, c in enumerate(contexts, 1))
    judge = _llm_json(
        "你是事实核查员。对每条【陈述】，判断它是否能从【检索内容】中找到对应信息。\n"
        "检索内容含该信息（即使措辞不同）-> found=true；未含 -> found=false。\n"
        '输出 JSON：{"results": [{"statement": "...", "found": true/false}]}。',
        f"检索内容：\n{context_text}\n\n待核查陈述：\n"
        f"{json.dumps(statements, ensure_ascii=False)}")
    found = sum(1 for r in judge.get("results", []) if r.get("found"))
    return found / len(statements)


def _reviewer_perms() -> set[str]:
    """reviewer 角色权限集（confidential 可检，Q2/Q4 保密文档需要）。"""
    from ..rag.retriever import _allowed_sources
    return _allowed_sources("reviewer")


def run_ragas_regression() -> dict:
    """跑 Q1-Q5 四指标回归，返回 {rows, avg, baseline, pass}。"""
    print("=" * 70)
    print("RAGAS 四指标回归：评估重构后 demo/rag 管线（E5+E6）")
    print("=" * 70)
    print("\n📦 初始化检索管线（向量库 + BM25 + Reranker）...")
    collection = get_or_build_vectorstore()
    bm25, chunks, metas = build_bm25_index(collection)
    reranker = load_reranker()
    allowed = _reviewer_perms()

    rows = []
    agg = {k: [] for k in BASELINE}
    for gt in GROUND_TRUTH:
        q = gt["question"]
        print(f"\n{'─' * 70}\n【{gt['id']}】{q}")
        hits = retrieve_hybrid(collection, bm25, chunks, metas, reranker, q,
                               top_k=3, allowed_perms=allowed)
        contexts = [h["text"] for h in hits]
        context_text = "\n\n".join(
            f"【片段{i}】(来源:{h['source']})\n{h['text']}"
            for i, h in enumerate(hits, 1))
        resp = call_llm_simple(RAG_ANSWER_PROMPT,
                               f"检索片段：\n{context_text}\n\n用户问题：{q}",
                               max_tokens=500)
        answer = (resp.choices[0].message.content or "").strip()
        print(f"  命中 {len(hits)} 片段，回答：{answer[:80]}...")

        scores = {
            "faithfulness": faithfulness(answer, contexts),
            "answer_relevancy": answer_relevancy(q, answer),
            "context_precision": context_precision(contexts, gt["answer"]),
            "context_recall": context_recall(gt["answer"], contexts),
        }
        for k, v in scores.items():
            agg[k].append(v)
        rows.append({"id": gt["id"], **{k: round(v, 2) for k, v in scores.items()}})
        print("  " + "  ".join(f"{k}={v:.2f}" for k, v in scores.items()))

    avg = {k: round(sum(v) / len(v), 2) for k, v in agg.items()}
    passed = {k: avg[k] >= BASELINE[k] for k in BASELINE}
    print(f"\n{'=' * 70}\n📊 四指标汇总（基线 vs 本次）\n{'=' * 70}")
    for k in BASELINE:
        mark = "✅" if passed[k] else "❌"
        print(f" {mark} {k}: {avg[k]:.2f}（基线 {BASELINE[k]:.2f}）")
    ok = all(passed.values())
    print(f"\n{'✅ 四指标全部不劣化基线' if ok else '❌ 存在劣化，详见上方'}")
    return {"rows": rows, "avg": avg, "baseline": BASELINE, "pass": ok}


def main():
    run_ragas_regression()


if __name__ == "__main__":
    main()
