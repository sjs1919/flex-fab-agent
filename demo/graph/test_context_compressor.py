"""上下文压缩器单元测试（纯逻辑 + mock LLM）。"""
from demo.graph.context_compressor import (
    estimate_chars, should_compress, build_compression_prompt, compress_messages,
    MAX_CHARS, KEEP_RECENT,
)


def _msg(role, content):
    return {"role": role, "content": content}


def test_estimate_chars():
    msgs = [_msg("user", "hello"), _msg("assistant", "world")]
    assert estimate_chars(msgs) == 10


def test_should_compress_over_threshold():
    # 用大段文本超过 MAX_CHARS
    big = [_msg("user", "x" * (MAX_CHARS + 100))]
    assert should_compress(big)


def test_should_compress_under_threshold():
    small = [_msg("user", "short")]
    assert not should_compress(small)


def test_build_compression_prompt_structure():
    msgs = [_msg("user", "ORD001 交期 07-25")]
    prompt = build_compression_prompt(msgs)
    assert prompt[0]["role"] == "system"
    assert "摘要" in prompt[0]["content"]
    assert "ORD001" in prompt[1]["content"]


def test_compress_messages_below_threshold_noop():
    """未超阈值 -> 原样返回。"""
    msgs = [_msg("user", "hi"), _msg("assistant", "hello")]
    assert compress_messages(msgs, lambda *a, **k: None) == msgs


def test_compress_messages_above_threshold(monkeypatch):
    """超阈值 -> system + 摘要 + 最近消息，LLM 生成摘要。"""
    from demo.graph import context_compressor
    monkeypatch.setattr(context_compressor, "MAX_CHARS", 50)
    monkeypatch.setattr(context_compressor, "KEEP_RECENT", 2)

    msgs = [
        _msg("system", "你是排产助手"),
        _msg("user", "ORD001 今天排产" + "x" * 80),  # 超长
        _msg("assistant", "好的，ORD001 安排今天"),
        _msg("user", "ORD003 呢"),
    ]
    class FakeResp:
        def __init__(self):
            self.choices = [type("C", (), {"message": type("M", (), {"content": "摘要: ORD001 已排产"})()})()]
    result = compress_messages(msgs, lambda *a, **k: FakeResp())
    # system + 摘要 + 最近 KEEP_RECENT 条
    assert result[0]["role"] == "system"
    assert "历史对话摘要" in result[1]["content"]


def test_compress_messages_llm_failure_fallback(monkeypatch):
    """LLM 摘要失败 -> 降级为占位文本，不中断。"""
    from demo.graph import context_compressor
    monkeypatch.setattr(context_compressor, "MAX_CHARS", 50)
    monkeypatch.setattr(context_compressor, "KEEP_RECENT", 2)

    # 足够多消息，让 old 非空触发摘要
    msgs = [_msg("system", "sys")] + [_msg("user", f"历史消息{i}内容" + "x" * 20) for i in range(5)]

    def boom(*a, **k):
        raise RuntimeError("LLM down")

    result = compress_messages(msgs, boom)
    # 降级成功：历史对话摘要占位出现在结果里，不抛异常
    assert any("历史对话摘要" in str(m.get("content", "")) for m in result)


def test_compress_messages_drops_orphan_tool_messages(monkeypatch):
    """压缩后不得残留孤儿 tool 消息（无对应 assistant tool_calls 前置）。

    背景：压缩按位置切片保留最近 N 条，若切片起点落在 tool 消息上，
    它对应的 assistant(tool_calls) 已被摘要替代 -> OpenAI 报 400
    "role 'tool' must be a response to a preceding message with 'tool_calls'"。
    """
    from demo.graph import context_compressor
    monkeypatch.setattr(context_compressor, "MAX_CHARS", 50)
    monkeypatch.setattr(context_compressor, "KEEP_RECENT", 2)

    # 场景：KEEP_RECENT=2 时 recent = 最后 2 条（一条 tool + 一条 user），
    # tool 消息对应的 assistant(tool_calls) 落在 old 里被摘要掉 -> 孤儿
    msgs = [
        _msg("system", "你是排产助手"),
        _msg("user", "查订单" + "x" * 80),  # 超长触发压缩
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "type": "function",
             "function": {"name": "query_orders", "arguments": "{}"}}]},
        _msg("tool", "共 15 条订单"),  # 这条是对应 assistant 的响应
        _msg("user", "OK"),
    ]

    class FakeResp:
        def __init__(self):
            self.choices = [type("C", (), {"message": type("M", (), {"content": "摘要: 查询订单"})()})()]
    result = compress_messages(msgs, lambda *a, **k: FakeResp())

    # 关键断言：压缩结果里不允许出现孤立的 tool 消息
    # （它的 assistant tool_calls 已不在保留范围内）
    tool_msgs = [m for m in result if m.get("role") == "tool"]
    for m in tool_msgs:
        assert any(
            prev.get("role") == "assistant" and prev.get("tool_calls")
            and any(tc.get("id") == m.get("tool_call_id") for tc in prev["tool_calls"])
            for prev in result[:result.index(m)]
        ), f"孤儿 tool 消息残留: {m}"


def test_compress_messages_idempotent(monkeypatch):
    """压缩后若仍超阈值，不应只靠 next 轮再压（会无限叠加摘要）。

    背景：recent 里保留了大段 tool 结果（>MAX_CHARS），压缩只摘要化旧消息，
    总字数不变 -> should_compress 仍 True -> 每次 select 前都压缩一次 -> 摘要不断叠加膨胀。
    """
    from demo.graph import context_compressor
    monkeypatch.setattr(context_compressor, "MAX_CHARS", 200)
    monkeypatch.setattr(context_compressor, "KEEP_RECENT", 4)

    # recent 从 assistant(tool_calls) 开始，大 tool 结果完整保留在 recent 内
    msgs = [
        _msg("system", "sys"),
        _msg("user", "u1" + "x" * 30),
        _msg("user", "u2" + "x" * 30),
        _msg("user", "u3" + "x" * 30),
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "q", "arguments": "{}"}}]},
        {"role": "tool", "content": "|" * 500, "tool_call_id": "c1"},
        _msg("user", "好"),
    ]

    class FakeResp:
        def __init__(self):
            self.choices = [type("C", (), {"message": type("M", (), {"content": "摘要"})()})()]
    result = compress_messages(msgs, lambda *a, **k: FakeResp())

    # 关键断言：压缩后总字符数必须下降（不再超阈值）
    assert estimate_chars(result) <= context_compressor.MAX_CHARS, (
        f"压缩后仍超阈值 {estimate_chars(result)} > {context_compressor.MAX_CHARS}"
    )
