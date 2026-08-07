"""上下文压缩器 -- 长对话 messages 自动摘要压缩（R4 缺陷修复）。

策略：summarization buffer（LangGraph 推荐）。
  - messages 超过 MAX_CHARS（按字符估算）→ 触发压缩
  - 压缩后 messages = [system] + [摘要] + [最近 N 条原始消息]
  - 摘要由 LLM 生成（自动用便宜的 provider / 小 max_tokens）

阈值说明（demo 教学版用字符数近似，生产用 tiktoken 精确计数）：
  - 中文约 1.5 字符/token
  - 默认 8000 字符 → 约 5300 tokens（远低于模型 128K 上下文但有效控制成本）
"""
import os

MAX_CHARS = int(os.getenv("CONTEXT_MAX_CHARS", "8000"))
KEEP_RECENT = int(os.getenv("CONTEXT_KEEP_RECENT", "6"))       # 保留最近 N 条原始消息
COMPRESS_CHUNK_SIZE = int(os.getenv("CONTEXT_COMPRESS_CHUNK", "10"))  # 每次压缩 N 条


def estimate_chars(messages: list[dict]) -> int:
    """估算 messages 总字符数。"""
    return sum(len(str(m.get("content", ""))) for m in messages)


def should_compress(messages: list[dict]) -> bool:
    """判断是否需要压缩。"""
    return estimate_chars(messages) > MAX_CHARS


def _messages_to_text(messages: list[dict]) -> str:
    """把 messages 转成可读文本，供 LLM 摘要。"""
    lines = []
    for m in messages:
        role = m.get("role", "?")
        content = str(m.get("content", ""))[:500]
        if m.get("tool_calls"):
            tool_names = [tc.get("function", {}).get("name", "?") for tc in m["tool_calls"]]
            content += f" [调用了工具: {', '.join(tool_names)}]"
        lines.append(f"[{role}] {content}")
    return "\n".join(lines)


def build_compression_prompt(messages_to_compress: list[dict]) -> list[dict]:
    """构造摘要请求的 messages。"""
    text = _messages_to_text(messages_to_compress)
    return [
        {"role": "system", "content": (
            "你是一个对话摘要助手。请用 2-3 句话（不超过 150 字）把以下对话片段中的关键信息总结出来。"
            "保留：订单号、客户名、交期、材料名、库存状态、设备负载、关键决策。"
            "丢弃：系统消息、问候语、重复内容。"
            "只输出摘要，不要加任何前缀。"
        )},
        {"role": "user", "content": f"请总结以下对话片段：\n{text}"},
    ]


def compress_messages(messages: list[dict], llm_call) -> list[dict]:
    """压缩 messages：保留 system + 最近消息，中间部分用摘要替代。

    Args:
        messages: 原始消息列表
        llm_call: LLM 调用函数（call_llm）

    Returns:
        压缩后的消息列表
    """
    if not should_compress(messages):
        return messages

    # 1. 分离 system prompt（永远保留）
    system_msgs = [m for m in messages if m.get("role") == "system"]
    other_msgs = [m for m in messages if m.get("role") != "system"]

    # 2. 保留最近 KEEP_RECENT 条
    recent = other_msgs[-KEEP_RECENT:] if len(other_msgs) > KEEP_RECENT else other_msgs
    old = other_msgs[:-KEEP_RECENT] if len(other_msgs) > KEEP_RECENT else []

    if not old:
        return messages

    # 3. 对早期消息分批做摘要（每 COMPRESS_CHUNK_SIZE 条一批）
    summaries = []
    for i in range(0, len(old), COMPRESS_CHUNK_SIZE):
        chunk = old[i:i + COMPRESS_CHUNK_SIZE]
        prompt = build_compression_prompt(chunk)
        try:
            resp = llm_call(prompt, max_tokens=200, temperature=0.1)
            summary = resp.choices[0].message.content or ""
            summaries.append(summary)
        except Exception:
            # 摘要失败 → 保留原始消息引用（降级）
            summaries.append(f"[对话片段 {i // COMPRESS_CHUNK_SIZE + 1}，共 {len(chunk)} 条消息]")

    # 4. 组装压缩后的 messages
    summary_text = "【历史对话摘要】\n" + "\n".join(
        f"· {s}" for s in summaries
    )
    compressed = list(system_msgs) + [
        {"role": "system", "content": summary_text},
    ] + list(recent)

    old_chars = estimate_chars(other_msgs)
    new_chars = estimate_chars(compressed)
    print(f"  📦 [上下文压缩] {len(old)} 条历史消息 → {len(summaries)} 段摘要（{old_chars} → {new_chars} 字符）")

    return compressed
