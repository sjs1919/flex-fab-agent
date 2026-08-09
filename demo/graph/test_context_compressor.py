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
