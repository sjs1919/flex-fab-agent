"""统一 LLM 调用层 -- 一份 call_llm，内置主备 fallback + 连接池 + 精确缓存。

为什么统一：
  week1 的 call_llm(system, user) 和 week3 的 call_llm(messages, tools) 是两份签名，
  重复且不一致。本模块统一为 messages 签名（更通用，支持 Function Calling），
  并提供 call_llm_simple(system, user) 便捷形式给 RAG / 子 Agent 用。
  主备 fallback 内置，调用方无需关心切 provider。

连接池设计：
  - 每个 provider 维护一个带连接池的 httpx.Client（复用 TCP 连接，避免频繁握手）
  - OpenAI 客户端按 provider 缓存为模块级单例，不再每次调用重建
  - 连接池参数：10 连接/provider，keep-alive 60s，适合 Agent 场景（单轮可能 3-5 次 LLM 调用）

缓存设计（两层）：
  - L1 精确缓存（本模块）：SQLite 存储，相同 prompt 命中 <1ms，0 token
  - L2 语义缓存（cache/semantic_cache.py）：近义改写命中，~50ms，省 token
"""
from dataclasses import dataclass
from typing import Any

import httpx
from openai import OpenAI

from ..cache import llm_cache
from ..config import PROVIDERS, _is_real_key
from ..observability import tracer, cost_tracker

# 每个 provider 的 OpenAI 客户端缓存（模块级单例，复用 TCP 连接池）
_client_cache: dict[str, OpenAI] = {}
# 共享的 httpx 连接池配置（每个 provider 独立 pool）
_LIMITS = httpx.Limits(max_keepalive_connections=10, max_connections=20, keepalive_expiry=60.0)
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


# ── 缓存命中时返回的 mock 响应（下游代码不感知差异）──

@dataclass
class _CachedFunction:
    name: str
    arguments: str

@dataclass
class _CachedToolCall:
    id: str
    type: str
    function: _CachedFunction

@dataclass
class _CachedMessage:
    content: str | None
    tool_calls: list[_CachedToolCall] | None = None

@dataclass
class _CachedChoice:
    message: _CachedMessage

@dataclass
class _CachedUsage:
    prompt_tokens: int
    completion_tokens: int

class _CachedResponse:
    """模拟 OpenAI ChatCompletion，让下游 .choices[0].message.content / .tool_calls / .function.name 正常工作。"""
    def __init__(self, content: str | None, tool_calls_raw: list[dict] | None,
                 prompt_tokens: int, completion_tokens: int):
        tcs = None
        if tool_calls_raw:
            tcs = [_CachedToolCall(
                id=tc.get("id", ""),
                type=tc.get("type", "function"),
                function=_CachedFunction(
                    name=tc.get("function", {}).get("name", ""),
                    arguments=tc.get("function", {}).get("arguments", "{}"),
                ),
            ) for tc in tool_calls_raw]
        self.choices = [_CachedChoice(_CachedMessage(content, tcs))]
        self.usage = _CachedUsage(prompt_tokens, completion_tokens)


def _build_client(provider: dict) -> OpenAI:
    """创建带连接池的 OpenAI 兼容客户端（复用 TCP 连接）。

    trust_env=False 是关键：绕过 Windows 系统代理（cc-switch 退出后注册表可能残留），
    避免死代理导致 SSL EOF。详见 cc-switch 启动模式记忆。
    注意：只有 LLM 调用走 trust_env=False 直连国产 API；
    RAG 下载模型时反而需要走 Clash 代理（见 rag/retriever.py）。
    """
    return OpenAI(
        api_key=provider["api_key"],
        base_url=provider["base_url"],
        http_client=httpx.Client(
            trust_env=False,
            limits=_LIMITS,
            timeout=_TIMEOUT,
        ),
    )


def _get_client(provider: dict) -> OpenAI:
    """获取 provider 对应的 OpenAI 客户端（优先从缓存取，复用连接池）。"""
    name = provider["name"]
    if name not in _client_cache:
        _client_cache[name] = _build_client(provider)
    return _client_cache[name]


def clear_client_cache() -> None:
    """清空客户端缓存（provider 配置变更后调用，如密钥轮换）。"""
    for client in _client_cache.values():
        client.close()
    _client_cache.clear()


def call_llm(messages: list[dict], tools: list[dict] | None = None,
             max_tokens: int = 500, temperature: float = 0.3):
    """统一 LLM 调用，内置主备自动降级 + 连接池复用 + 精确缓存。

    两层缓存：
      1. 精确缓存（L1，本模块）：相同 prompt → SQLite 命中 <1ms，0 token
      2. 语义缓存（L2，agents/single_agent.py）：近义改写命中，~50ms

    遍历 PROVIDERS，第一个成功即返回；失败自动切下一个。
      messages    -- OpenAI 消息列表（system/user/assistant/tool）
      tools       -- 可选，Function Calling 的工具 schema 列表
      返回 OpenAI ChatCompletion 响应对象（或缓存的等价模拟对象）。
    """
    last_err = None
    for p in PROVIDERS:
        if not p.get("enabled") or not _is_real_key(p["api_key"]):
            continue
        model = p["model"]

        # L1 精确缓存：相同 prompt + model + 参数 → 直接返回
        cached = llm_cache.get(messages, tools, model, max_tokens, temperature)
        if cached is not None:
            with tracer.span("llm:call", provider=p["name"], model=model,
                             cache="L1_hit") as s:
                s.attributes["tokens_in"] = cached["prompt_tokens"]
                s.attributes["tokens_out"] = cached["completion_tokens"]
                s.attributes["cache"] = "exact"
                # 缓存命中不计费（无实际 API 消耗），但记录预估节省
                s.attributes["cost_saved"] = round(
                    (cached["prompt_tokens"] + cached["completion_tokens"]) / 1_000_000 * 2.0, 6
                )
            print(f"  ⚡ [L1缓存命中] {p['name']} {model}（省 {cached['prompt_tokens']}+{cached['completion_tokens']} tokens）")
            return _CachedResponse(
                content=cached["content"],
                tool_calls_raw=cached["tool_calls"],
                prompt_tokens=cached["prompt_tokens"],
                completion_tokens=cached["completion_tokens"],
            )

        try:
            client = _get_client(p)  # 复用连接池，不再每次 new
            kwargs: dict = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            with tracer.span("llm:call", provider=p["name"], model=model) as s:
                resp = client.chat.completions.create(**kwargs)
            # 记录 token 用量到 span（生产级会随 span 一起导出到 OTel）
            if resp.usage:
                s.attributes["tokens_in"] = resp.usage.prompt_tokens
                s.attributes["tokens_out"] = resp.usage.completion_tokens
                # 成本追踪：记录费用 + 预算熔断（week5 #1）
                try:
                    entry = cost_tracker.record(
                        provider=p["name"],
                        model=model,
                        prompt_tokens=resp.usage.prompt_tokens,
                        completion_tokens=resp.usage.completion_tokens,
                    )
                    s.attributes["cost"] = round(entry.cost_total, 6)
                except Exception as cost_err:
                    print(f"  💥 [成本熔断] {cost_err}")
                    raise

            # 写入 L1 精确缓存（下次相同请求直接命中）
            content = resp.choices[0].message.content
            tool_calls_raw = None
            if resp.choices[0].message.tool_calls:
                tool_calls_raw = [
                    {"id": tc.id, "type": tc.type,
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in resp.choices[0].message.tool_calls
                ]
            llm_cache.put(
                messages, tools, model, max_tokens, temperature,
                content=content or "",
                tool_calls=tool_calls_raw,
                prompt_tokens=resp.usage.prompt_tokens if resp.usage else 0,
                completion_tokens=resp.usage.completion_tokens if resp.usage else 0,
            )
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
