"""统一 LLM 调用层 -- 一份 call_llm，内置主备 fallback。

为什么统一：
  week1 的 call_llm(system, user) 和 week3 的 call_llm(messages, tools) 是两份签名，
  重复且不一致。本模块统一为 messages 签名（更通用，支持 Function Calling），
  并提供 call_llm_simple(system, user) 便捷形式给 RAG / 子 Agent 用。
  主备 fallback 内置，调用方无需关心切 provider。
"""
import httpx
from openai import OpenAI

from ..config import PROVIDERS, _is_real_key
from ..observability import tracer


def _build_client(provider: dict) -> OpenAI:
    """创建 OpenAI 兼容客户端。

    trust_env=False 是关键：绕过 Windows 系统代理（cc-switch 退出后注册表可能残留），
    避免死代理导致 SSL EOF。详见 cc-switch 启动模式记忆。
    注意：只有 LLM 调用走 trust_env=False 直连国产 API；
    RAG 下载模型时反而需要走 Clash 代理（见 rag/retriever.py）。
    """
    return OpenAI(
        api_key=provider["api_key"],
        base_url=provider["base_url"],
        http_client=httpx.Client(trust_env=False),
    )


def call_llm(messages: list[dict], tools: list[dict] | None = None,
             max_tokens: int = 500, temperature: float = 0.3):
    """统一 LLM 调用，内置主备自动降级。

    遍历 PROVIDERS，第一个成功即返回；失败自动切下一个。
      messages    -- OpenAI 消息列表（system/user/assistant/tool）
      tools       -- 可选，Function Calling 的工具 schema 列表
      返回 OpenAI ChatCompletion 响应对象。
    """
    last_err = None
    for p in PROVIDERS:
        if not p.get("enabled") or not _is_real_key(p["api_key"]):
            continue
        try:
            client = _build_client(p)
            kwargs: dict = {
                "model": p["model"],
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            with tracer.span("llm:call", provider=p["name"], model=p["model"]) as s:
                resp = client.chat.completions.create(**kwargs)
            # 记录 token 用量到 span（生产级会随 span 一起导出到 OTel）
            if resp.usage:
                s.attributes["tokens_in"] = resp.usage.prompt_tokens
                s.attributes["tokens_out"] = resp.usage.completion_tokens
            return resp
        except Exception as e:
            last_err = e
            print(f"  ⚠️  [{p['name']}] 失败: {type(e).__name__}: {str(e)[:80]}，切下一个...")
    raise RuntimeError(f"所有 provider 均失败。最后错误: {last_err}")


def call_llm_simple(system_prompt: str, user_prompt: str, **kwargs):
    """便捷形式：system + user 两参 -> 组装 messages -> call_llm。

    供 RAG / 子 Agent 等无需工具调用的场景使用。
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return call_llm(messages, **kwargs)
