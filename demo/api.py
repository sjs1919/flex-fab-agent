"""FastAPI 网关 -- 把 demo 暴露为 HTTP 服务（#10 容器化）。

把 run_single_agent 包成 REST API：
  POST /ask                  单次/多轮提问
  GET  /health               就绪探针（不调 LLM，只报配置）
  GET  /threads/{id}/history 多轮会话历史（checkpointer 持久化的 messages）

调用约定：
  - 不带 thread_id -> 单次提问（语义缓存生效，无状态，响应不回传 thread_id）
  - 带 thread_id   -> 多轮对话（从 checkpoint 恢复历史；语义缓存跳过）
    客户端自行生成 thread_id 发起多轮，后续轮次带上同一 id 即可续上下文。

run_single_agent 运行时的 print 进容器 stdout（docker logs 可见），
本接口只把结构化结果以 JSON 返回。trace 摘要复用 tracer.get_summary()。
"""
import os
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .agents.single_agent import _get_app, run_single_agent
from .cache import semantic_cache
from .config import available_providers
from .observability import tracer
from .tools.registry import build_default_registry

app = FastAPI(title="demo 排产助手 API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 工具注册表进程级单例（首次构建后复用，免去每请求重建）
_registry = build_default_registry()


class AskRequest(BaseModel):
    query: str
    thread_id: str | None = None


class AskResponse(BaseModel):
    answer: str
    tool_results: list[dict]
    thread_id: str | None
    trace: dict


@app.get("/health")
def health() -> dict:
    """就绪探针：报 provider/工具/缓存/checkpointer 配置，不调 LLM。"""
    return {
        "status": "ok",
        "providers": [p["name"] for p in available_providers()],
        "tools": len(_registry),
        "tool_names": _registry.list_all(),
        "cache": "on" if semantic_cache.is_enabled() else "off",
        "checkpointer": os.getenv("CHECKPOINTER", "sqlite"),
    }


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    """单次或多轮提问。带 thread_id 即多轮（checkpointer 恢复历史）。"""
    tracer.reset()
    result = run_single_agent(req.query, registry=_registry, thread_id=req.thread_id)
    trace = tracer.get_summary()
    tracer.flush()
    return AskResponse(
        answer=result.get("final_answer", ""),
        tool_results=result.get("tool_results", []),
        thread_id=req.thread_id,
        trace=trace,
    )


@app.get("/threads/{thread_id}/history")
def thread_history(thread_id: str) -> dict:
    """读某多轮会话的 checkpoint 历史 messages（仅 sqlite/memory checkpointer 有数据）。"""
    if os.getenv("CHECKPOINTER", "sqlite").lower() == "none":
        raise HTTPException(400, "checkpointer=none，无持久化历史")
    app_graph = _get_app(_registry)
    state = app_graph.get_state({"configurable": {"thread_id": thread_id}})
    if not state or not state.values:
        raise HTTPException(404, f"会话 {thread_id} 无历史记录")
    messages = state.values.get("messages", [])
    return {
        "thread_id": thread_id,
        "turns": len(messages),
        "messages": [{"role": m.get("role"), "content": m.get("content")} for m in messages],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("demo.api:app", host="0.0.0.0", port=8000, reload=False)
