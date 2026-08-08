"""自研 LLM-as-Judge 语义指标（不依赖 ragas 库）。

设计要点：
  - 复用 core.llm_client.call_llm，与 demo 同一调用层（主备 fallback + 缓存）。
  - faithfulness / answer_relevancy 两项，0-1 打分。
  - judge 失败（LLM 异常/解析失败）→ 优雅降级 0 分，不中断 eval。
"""
import json
import re
from typing import Any

from ..core.llm_client import call_llm
from .judge_prompt import build_judge_messages

# search_knowledge_base 工具名（RAG 检索上下文来源）
_CONTEXT_TOOLS = {"search_knowledge_base"}


def _extract_context(tool_results: list[dict]) -> str:
    """从 tool_results 提取检索工具的返回作为上下文。

    LLM-as-Judge 的 faithfulness 需要"检索上下文"做参照。
    当前 demo 只有 search_knowledge_base 一个 RAG 工具会返回结构化知识片段。
    """
    parts = []
    for tr in tool_results:
        if tr.get("tool") in _CONTEXT_TOOLS and tr.get("result"):
            parts.append(tr["result"])
    return "\n\n".join(parts)


def parse_judge_response(raw: str) -> dict[str, float]:
    """解析 judge 的 JSON 输出，失败返回 0 分。"""
    if not raw:
        return {"faithfulness": 0.0, "answer_relevancy": 0.0}
    try:
        # 提取 JSON 子串（LLM 可能输出多余文字）
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
        return {
            "faithfulness": float(data.get("faithfulness", 0.0)),
            "answer_relevancy": float(data.get("answer_relevancy", 0.0)),
        }
    except (ValueError, TypeError, AttributeError):
        return {"faithfulness": 0.0, "answer_relevancy": 0.0}


def judge_semantic_quality(question: str, context: str, answer: str) -> dict[str, float]:
    """对单个 case 的答案做 LLM-as-Judge 语义打分。

    Args:
        question: 用户问题
        context: 检索上下文（来自 tool_results 的 search_knowledge_base 结果）
        answer: Agent 生成的最终答案

    Returns:
        {"faithfulness": float, "answer_relevancy": float}
    """
    if not context:
        # 无检索上下文时，faithfulness 无法评估 -> 给 0，relevancy 仍可评
        return {"faithfulness": 0.0, "answer_relevancy": _judge_relevancy_only(question, answer)}

    messages = build_judge_messages(question, context, answer)
    try:
        response = call_llm(messages, max_tokens=200, temperature=0.0)
        raw = response.choices[0].message.content or ""
        return parse_judge_response(raw)
    except Exception as e:
        print(f"  ⚠️  [judge] LLM 打分失败，降级 0 分: {type(e).__name__}")
        return {"faithfulness": 0.0, "answer_relevancy": 0.0}


def _judge_relevancy_only(question: str, answer: str) -> float:
    """无检索上下文时，仅用简单启发式评估相关性（关键词命中率）。

    这是 LLM-as-Judge 失败/无上下文时的兜底，不做真实 LLM 调用。
    """
    q_terms = [t for t in re.split(r"[\s，。？、]+", question) if len(t) >= 2]
    if not q_terms:
        return 0.5
    hits = sum(1 for t in q_terms if t in answer)
    return round(hits / len(q_terms), 2)
