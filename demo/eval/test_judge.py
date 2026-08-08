"""LLM-as-Judge 单元测试（mock call_llm，不发起真实调用）。"""
import json

import pytest

from demo.eval.judge import judge_semantic_quality, parse_judge_response, _extract_context
from demo.eval.judge_prompt import build_judge_messages, JUDGE_SYSTEM_PROMPT


class FakeResponse:
    """模拟 call_llm 返回。"""
    def __init__(self, content: str):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]


def test_build_judge_messages_structure():
    """构造的消息含 system + user 两段。"""
    msgs = build_judge_messages("问题", "上下文", "回答")
    assert msgs[0]["role"] == "system"
    assert "问题" in msgs[1]["content"]
    assert "上下文" in msgs[1]["content"]


def test_parse_judge_response_valid_json():
    """解析合法 JSON。"""
    r = parse_judge_response('{"faithfulness": 0.9, "answer_relevancy": 0.8}')
    assert r == {"faithfulness": 0.9, "answer_relevancy": 0.8}


def test_parse_judge_response_malformed():
    """解析非法 JSON -> 返回 0 分，不抛异常。"""
    r = parse_judge_response("not json at all")
    assert r == {"faithfulness": 0.0, "answer_relevancy": 0.0}


def test_parse_judge_response_empty():
    """空字符串 -> 0 分。"""
    r = parse_judge_response("")
    assert r == {"faithfulness": 0.0, "answer_relevancy": 0.0}


def test_judge_semantic_quality_calls_llm(monkeypatch):
    """judge_semantic_quality 调用 call_llm 并解析结果。"""
    from demo.eval import judge as judge_mod

    def fake_call_llm(messages, **kwargs):
        assert messages[0]["content"] == JUDGE_SYSTEM_PROMPT
        return FakeResponse(json.dumps({"faithfulness": 0.9, "answer_relevancy": 0.8}))

    monkeypatch.setattr(judge_mod, "call_llm", fake_call_llm)
    result = judge_semantic_quality("问题", "上下文", "回答")
    assert result == {"faithfulness": 0.9, "answer_relevancy": 0.8}


def test_judge_semantic_quality_llm_failure(monkeypatch):
    """call_llm 抛异常 -> 优雅降级为 0 分，不中断。"""
    from demo.eval import judge as judge_mod

    def boom(messages, **kwargs):
        raise RuntimeError("LLM 挂了")

    monkeypatch.setattr(judge_mod, "call_llm", boom)
    result = judge_semantic_quality("问题", "上下文", "回答")
    assert result == {"faithfulness": 0.0, "answer_relevancy": 0.0}


def test_extract_context_extracts_from_tool_result():
    """从 tool_results 提取 search_knowledge_base 的结果作为检索上下文。"""
    tool_results = [
        {"tool": "query_orders", "result": "订单数据"},
        {"tool": "search_knowledge_base", "result": "合同条款：广州航天..."},
    ]
    ctx = _extract_context(tool_results)
    assert "合同条款" in ctx
    assert "订单数据" not in ctx  # 只取检索工具的上下文


def test_extract_context_empty():
    """无检索工具结果 -> 空上下文。"""
    tool_results = [{"tool": "query_orders", "result": "订单数据"}]
    ctx = _extract_context(tool_results)
    assert ctx == ""
