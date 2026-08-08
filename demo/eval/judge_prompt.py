"""LLM-as-Judge 提示词模板（自研，不依赖 ragas）。

设计要点：
  - 用结构化输出（JSON），让 judge 打分可解析。
  - faithfulness：答案是否忠实于检索上下文（不 hallucinate）。
  - answer_relevancy：答案是否直接回答用户问题。
  - 打分范围 0-1，保留 1 位小数。
"""

JUDGE_SYSTEM_PROMPT = """你是一名专业的 RAG 评估专家。请对以下 Agent 回答进行打分。

评分维度：
1. faithfulness（忠实度，0-1）：回答是否完全基于给定的检索上下文，没有编造上下文之外的事实。
   0.0 = 严重编造，1.0 = 完全忠实于上下文。
2. answer_relevancy（相关性，0-1）：回答是否直接、完整地回答了用户的问题。
   0.0 = 答非所问，1.0 = 精准命中问题核心。

只输出一个 JSON 对象，格式：
{"faithfulness": 0.9, "answer_relevancy": 0.8}

不要输出任何其他内容。
"""


def build_judge_messages(question: str, context: str, answer: str) -> list[dict]:
    """构造 judge 的输入消息。"""
    user_content = f"""用户问题：{question}

检索上下文：
{context}

Agent 回答：
{answer}

请打分。"""
    return [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
