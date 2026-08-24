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
from datetime import datetime

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .agents.single_agent import _get_app, run_single_agent
from .cache import semantic_cache
from .config import available_providers
from .observability import tracer, cost_tracker
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

# 模拟器心跳进程级单例（M4a /sim/*）
_sim_runner = None


def _get_sim_runner():
    global _sim_runner
    if _sim_runner is None:
        from .simulator.runner import SimulatorRunner
        _sim_runner = SimulatorRunner()
    return _sim_runner


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
    """就绪探针：报 provider/工具/缓存/checkpointer/sim 配置，不调 LLM。"""
    runner = _get_sim_runner()
    return {
        "status": "ok",
        "providers": [p["name"] for p in available_providers()],
        "tools": len(_registry),
        "tool_names": _registry.list_all(),
        "cache": "on" if semantic_cache.is_enabled() else "off",
        "checkpointer": os.getenv("CHECKPOINTER", "sqlite"),
        "sim": {"running": runner.is_alive(), "tick_count": runner.tick_count},
    }


# ---- 模拟器控制（M4a，v2 C6） ----

@app.post("/sim/start")
def sim_start() -> dict:
    """启动模拟器心跳。sim_clock 未初始化时从当前整点起跳。"""
    from .simulator import clock
    from .tools.data import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sim_clock")
            initialized = cur.fetchone()[0] > 0
        if not initialized:
            clock.init_clock(conn, datetime.now().replace(minute=0, second=0,
                                                          microsecond=0))
            conn.commit()
    runner = _get_sim_runner()
    runner.start()
    return {"running": True, "tick_seconds": runner.tick_seconds}


@app.post("/sim/stop")
def sim_stop() -> dict:
    runner = _get_sim_runner()
    runner.stop()
    return {"running": runner.is_alive(), "tick_count": runner.tick_count}


@app.get("/sim/status")
def sim_status() -> dict:
    """模拟器运行态 + 当前 sim 时间（未初始化时 sim_time=null）。"""
    from .simulator import clock
    from .tools.data import get_connection

    sim_time = None
    try:
        with get_connection() as conn:
            sim_time = clock.get_sim_time(conn).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    runner = _get_sim_runner()
    return {
        "running": runner.is_alive(),
        "tick_count": runner.tick_count,
        "tick_seconds": runner.tick_seconds,
        "sim_time": sim_time,
    }


# ---- 排产查询/触发（M4a） ----

@app.get("/schedule/latest")
def schedule_latest() -> dict:
    """最新排产版本 + 批次（无版本时 version=null）。"""
    from .tools.data import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, created_at, triggered_by, status "
                        "FROM schedule_versions ORDER BY id DESC LIMIT 1")
            vrow = cur.fetchone()
            version = None
            batches = []
            if vrow:
                version = {"id": vrow[0], "created_at": str(vrow[1]),
                           "triggered_by": vrow[2], "status": vrow[3]}
                cur.execute(
                    "SELECT id, order_ids, process, model_type, machine_id, "
                    "start_time, end_time, status, approval_status "
                    "FROM batches WHERE schedule_version_id=%s ORDER BY start_time",
                    (vrow[0],))
                cols = [d[0] for d in cur.description]
                batches = [{k: (str(v) if isinstance(v, datetime) else v)
                            for k, v in zip(cols, r)} for r in cur.fetchall()]
    return {"version": version, "batches": batches}


@app.post("/schedule/load")
def schedule_load(x_admin_token: str = Header(default="")) -> dict:
    """触发一轮排产求解并落库（写端点，强制 admin token，R-7）。"""
    _require_admin(x_admin_token)
    from .tools.scheduler_tools import run_scheduling
    return {"result": run_scheduling(triggered_by="api")}


def _require_admin(token_id: str) -> None:
    """写端点鉴权（R-7）：X-Admin-Token 头必须是有效且未过期的 admin token。"""
    if not token_id:
        raise HTTPException(401, "写端点需要 admin token（R-7）：缺 X-Admin-Token 头")
    from .auth.token_exchange import STS
    token = STS().get_token(token_id)
    if token is None or token.is_expired():
        raise HTTPException(401, "admin token 无效或已过期")
    if token.role != "admin":
        raise HTTPException(403, f"需要 admin 角色（当前 {token.role}）")


# ---- 订单跟踪 + KPI（M4b，v2 C6；只读，与 /schedule/latest 同级） ----

@app.get("/order/{order_id}/tracking")
def order_tracking(order_id: str) -> dict:
    """订单状态跟踪（只读）：当前环节、在途预计完成/排队队列、前面单据清单。"""
    from .tools.scheduler_tools import query_order_tracking
    report = query_order_tracking(order_id)
    if report.startswith("❌ 订单不存在"):
        raise HTTPException(404, f"订单不存在：{order_id}")
    return {"order_id": order_id, "report": report}


@app.get("/kpi")
def kpi() -> dict:
    """排产 KPI（只读）：准交率/延期金额/舱利用率/良率/前道瓶颈占用，DB 实时聚合。"""
    from .tools.scheduler_tools import query_kpi
    return {"report": query_kpi()}


# ---- 看板只读端点（M5b T5b.7；匿名可读，B8 前端消费） ----

def _cap_limit(limit: int, max_limit: int = 2000) -> int:
    """limit 参数夹取（只读端点防全表拉取）。"""
    return min(max(limit, 1), max_limit)


@app.get("/dashboard/kpi-history")
def dashboard_kpi_history(limit: int = 500) -> dict:
    """KPI 快照历史（只读，升序）：sim tick 落点 + kpi_metrics 全量。"""
    from .observability import dashboard
    return {"items": dashboard.kpi_history(limit=_cap_limit(limit))}


@app.get("/dashboard/costs")
def dashboard_costs(limit: int = 500) -> dict:
    """成本历史（只读，倒序）+ 跨记录按 model 聚合。"""
    from .observability import dashboard
    return dashboard.cost_by_model(limit=_cap_limit(limit))  # 已含 items + by_model


@app.get("/dashboard/traces")
def dashboard_traces(limit: int = 200) -> dict:
    """trace 摘要历史（只读，倒序）。"""
    from .observability import dashboard
    return {"items": dashboard.trace_summary(limit=_cap_limit(limit))}


def _persist_dashboard(trace_id: str, trace: dict, cost: dict) -> None:
    """看板历史落库（M5b T5b.6）：/ask 后落 cost_record + trace_record。

    旁路观测，失败不影响 /ask 响应（只打警告）。
    """
    try:
        from .observability import dashboard
        dashboard.record_cost(cost, trace_id=trace_id)
        dashboard.record_trace(trace, trace_id=trace_id)
    except Exception as e:
        print(f"⚠️ 看板落库失败（不影响 /ask 响应）：{e}")


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    """单次或多轮提问。带 thread_id 即多轮（checkpointer 恢复历史）。"""
    tracer.reset()
    cost_tracker.reset()
    result = run_single_agent(req.query, registry=_registry, thread_id=req.thread_id)
    trace = tracer.get_summary()
    cost = cost_tracker.get_summary()
    tracer.flush()
    _persist_dashboard(tracer.trace_id, trace, cost)
    # 成本摘要输出到 stdout（docker logs 可见）
    print(cost_tracker.format_text())
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
