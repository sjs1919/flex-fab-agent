# demo -- 制造业排产智能体（v2.0 · 2026-08-25）

> [AI:Claude] 架构设计 + 实现。从 week1-week5 的对话式 Agent 助手，演进为完整的制造业排产智能体系统：**约束求解器 + 生产模拟器 + Agent 调度闭环 + 统计预测 + KPI 看板**。
>
> 需求规格 v1：[docs/demo/02-specs/需求规格-v1-2026-08-21.md](../docs/demo/02-specs/需求规格-v1-2026-08-21.md)
> 部署指南 v1：[docs/demo/部署指南-v1-2026-08-25.md](../docs/demo/部署指南-v1-2026-08-25.md)
> 生产化蓝图：[docs/demo/生产化差距与部署蓝图-v1-2026-08-22.md](../docs/demo/生产化差距与部署蓝图-v1-2026-08-22.md)

## 1. 这个 demo 能做什么

一个面向**制造业 3D 打印排程排产**的完整智能体系统。从对话式问答（v1）升级为**排产求解 → 模拟执行 → Agent 调度 → 预测分析 → 看板观测**的闭环系统（v2）。

### v1 能力（对话式助手）
- **单 Agent 模式**：一个 Agent + 工具注册表，自主决定调用工具、循环调用直到拿到足够信息再回答（LangGraph 编排）
- **多 Agent 模式（Supervisor）**：主管 Agent 路由到专业子 Agent（订单评审 / 生产评估），子 Agent 持受限令牌调用工具，主管汇总，带 RBAC 鉴权 + 审计日志
- **合同知识库（RAG）**：向量 + BM25 + RRF + Cross-Encoder 混合检索，命中合同原文
- 能回答的问题：订单排期 / 订单详情 / 紧急情况 / 客户评估 / 库存影响

### v2 新增能力（制造业主线）🆕
- **M1 数据层改造**：CSV → MySQL 抽象层，连接池，事务管理，读写分离，租户过滤
- **M2 排产约束求解器**：OR-Tools CP-SAT 约束规划 + 装箱模型，支持 C1-C9 九大约束校验，输出结构化排产表（批次表 + 指标）
- **M3 生产模拟器**：事件驱动模拟引擎，订单到达 → 前道 → 打印 → 完成全流程，心跳线程持续推进仿真时间
- **M4a Agent 调度闭环**：18 个排产工具（求解/查排产/查模拟事件/审批/产能/CTP/跟踪/KPI），Agent 可触发求解、查询排产、审批版本
- **M4b 人机协同 + 产能评估**：排产版本审批流（待审核→已审核/已驳回），产能负载评估，可承诺交期（CTP），订单跟踪，前道负载
- **M5a 统计预测**：指数平滑 + 移动平均，需求预测按日分材料聚合（件数 + 机时）
- **M5b KPI 看板 Dashboard**：KPI 快照落库 + 成本记录 + trace 记录，只读查询端点，零 CDN 静态 HTML 看板
- **Schema 建表脚本**：15 张业务表，写方唯一原则，幂等建表，外键拓扑

## 2. 前置条件

### 基础依赖
```bash
# Python 3.11+
pip install openai httpx chromadb sentence-transformers rank-bm25 jieba langgraph
pip install mcp              # MCP 架构展示（非必需）
```

### v2 新增依赖 🆕
```bash
# 排产求解器（M2）
pip install ortools
# MySQL 数据层（M1）
pip install pymysql
# FastAPI 网关
pip install fastapi uvicorn
```

### 数据库（v2 必需）
MySQL 8.0+，库名 `demo_scheduling`，建表脚本见 `demo/schema/schema.sql`：
```bash
# 方式一：手动执行建表脚本
mysql -u root -p demo_scheduling < demo/schema/schema.sql

# 方式二：用 migrate.py
python -m demo.schema.migrate
```

### 环境变量（项目根目录 `.env`）
```ini
# LLM Provider
VOLC_API_KEY=...           # 火山豆包（主 provider）
VOLC_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
DEEPSEEK_API_KEY=...       # DeepSeek（备 provider，主挂了自动降级）

# MySQL（v2，M1）
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=...
DB_NAME=demo_scheduling
DATA_SOURCE=mysql          # mysql | csv（默认 csv，兼容 v1）
DB_POOL_SIZE=5             # 连接池大小
```

### 本地模型缓存（RAG 真连必需）
- 向量嵌入：Chroma 默认 ONNX MiniLM（`~/.cache/chroma/onnx_models/`）
- 重排器：`BAAI/bge-reranker-base`（`~/.cache/huggingface/hub/`）

## 3. 快速开始

```bash
cd projects/agent-training

# 0. 建表（首次，v2 必需）
python -m demo.schema.migrate

# 1. 地基自检（config / LLM / 工具 三层连通）
python -m demo.main --check

# 2. 单 Agent 问一个问题（v1 模式）
python -m demo.main "今天先做哪些订单？"

# 3. 多轮对话（状态持久化，重启可恢复）
python -m demo.main --chat

# 4. 多 Agent 模式（带鉴权 + 审计）
python -m demo.main "综合评估 ORD001" --mode multi

# 5. 跑预设场景（交互式选编号）
python -m demo.main --demo

# ── v2 新增命令 ──

# 6. 求解一轮排产并落库（M2 + M4a）
python -m demo.main --init-schedule

# 7. 启动生产模拟器心跳（M3 + M4a，Ctrl+C 停止）
python -m demo.main --sim

# 8. Prompt 版本回滚（R-4 安全回滚）
python -m demo.main --rollback v1

# 9. 启动 FastAPI 网关（含看板端点）
uvicorn demo.api:app --reload --port 8000
```

> Windows 用户无需手动设 `PYTHONIOENCODING`：`demo/__init__.py` 已把标准输出重配为 UTF-8。

## 4. 调用建议

| 场景 | 推荐命令 | 为什么 |
|------|---------|--------|
| 验证环境是否配好 | `--check` | 不调 LLM 也能确认工具/数据层 OK，最快排障 |
| 单一问题快速回答 | `python -m demo.main "问题"` | 单 Agent 足够，链路短、token 省 |
| 涉及多角色协同 | `--mode multi "..."` | Supervisor 分派子 Agent，各持权限令牌，演示 RBAC |
| 合同/条款类问题 | 任意模式问"合同""条款" | 自动触发 `search_knowledge_base`（RAG 工具） |
| **想看真实排产结果** 🆕 | `--init-schedule` | 跑 CP-SAT 求解器，产出结构化批次表 + 准交率指标 |
| **想看动态模拟** 🆕 | `--sim` + `--init-schedule` | 先求解 → 启模拟器，看订单在各环节流转、设备状态变化 |
| **看 KPI 看板** 🆕 | 起 API → 访问 `/dashboard/kpi-history` | KPI 时间序列 + 成本 + trace，零 CDN 静态 HTML |
| 看完整效果 | `--demo` | 5 个预设场景覆盖订单/资源/客户/RAG 各类工具 |

**v2 推荐体验路径**：先 `--check` → 建表 → `--init-schedule` 看求解 → `--sim` 看模拟 → 问 Agent "当前排产情况如何" → 访问 `/kpi` 看板。

## 5. 目录说明

```
demo/
├── __init__.py              # 包入口；UTF-8 输出修复（Windows GBK 兼容）
├── main.py                  # 统一入口：--check/--demo/--sim/--init-schedule/--rollback
├── api.py                   # FastAPI 网关：/ask + /sim/* + /schedule/* + /kpi + /dashboard/*
├── config.py                # 统一 .env 加载 + PROVIDERS 列表 + 数据源配置 + system_config
│
├── core/                    # 基座层
│   └── llm_client.py        #   call_llm(messages, tools) + 主备降级 + 连接池 + L1 精确缓存
│
├── cache/                   # 缓存层（两级缓存减少 LLM API 调用）
│   ├── llm_cache.py         #   L1 精确缓存（SQLite，相同 prompt 命中 <1ms，0 token）
│   └── semantic_cache.py    #   L2 语义缓存（Chroma cosine，近义改写命中 ~50ms）
│
├── tools/                   # 工具层（MCP 架构，18 个工具）
│   ├── data.py              #   数据层抽象：CSV + MySQL 双模式 + 连接池 + 事务 + 租户过滤 🆕M1
│   ├── order_tools.py       #   订单工具：query_orders（8 字段 AND 筛选/排序/limit）
│   ├── resource_tools.py    #   资源工具：库存 / 设备 / 客户
│   ├── scheduler_tools.py   #   ★ 排产工具（11 个，M4a/4b）：求解/查排产/模拟事件/审批/产能/CTP/跟踪/KPI 🆕
│   ├── registry.py          #   ToolRegistry：O(1) 查找 + 参数白名单 + RBAC 强制 + tracer + sandbox
│   ├── sandbox.py           #   工具沙箱（R1：超时控制 + 指数退避重试）
│   ├── mcp_client.py        #   MCP Client（R5：stdio 子进程通信）
│   └── mcp_servers.py       #   FastMCP server 构建（展示 MCP 协议）
│
├── scheduler/               # ★ 排产求解器（M2）🆕
│   ├── snapshot.py          #   读一致性快照（连库读取→内存数据结构）
│   ├── verify.py            #   C1-C9 约束校验（9 条硬约束前置检查）
│   ├── model.py             #   装箱模型 + CP-SAT 约束规划（OR-Tools）
│   ├── solver.py            #   求解入口：装箱 → CP-SAT → 排产表 + 指标计算
│   ├── assessment.py        #   产能评估（M4b）：负载/CTP/前道/订单跟踪/KPI
│   └── test_*.py            #   各模块单元测试
│
├── simulator/               # ★ 生产模拟器（M3）🆕
│   ├── clock.py             #   模拟时钟（加速比可配）
│   ├── events.py            #   事件定义（订单到达/上板/下板/完成/restock 等）
│   ├── states.py            #   状态管理（设备状态/订单状态流转）
│   ├── engine.py            #   模拟引擎：事件驱动，单事务推进 A/B 层
│   ├── runner.py            #   心跳运行器：独立线程主循环，连续失败熔断
│   ├── seed.py              #   初始数据播种（写方唯一：seed + B 层）
│   └── test_*.py            #   各模块单元测试 + e2e
│
├── forecast/                # ★ 统计预测（M5a）🆕
│   ├── models.py            #   预测模型：指数平滑 + 移动平均（纯函数）
│   └── forecaster.py        #   聚合入口：读 MySQL → 逐日分材料预测（件数 + 机时）
│
├── rag/                     # 合同知识库混合检索
│   ├── knowledge_base.py    #   文档加载/分块/Chroma 向量库（复用持久化）
│   └── retriever.py         #   BM25 + 向量 + RRF 融合 + Cross-Encoder 重排 + 离线防坑
│
├── guardrails/              # 输出护栏（R2）
│   ├── rules.py             #   护栏规则（越权/敏感/缺失段落）
│   └── content_filter.py    #   内容过滤器（regex + 降级策略）
│
├── eval/                    # Agent 三层评估体系（R6）
│   ├── ground_truth.json    #   10 组排产场景 ground truth Q&A
│   ├── metrics.py           #   工具层指标（F1/完整性/订单召回/min_tools_called）
│   ├── trajectory.py        #   轨迹层指标（路径效率/重试质量/循环检测）
│   ├── trajectory_capture.py#   从 tracer + tool_results 重建工具调用序列
│   ├── judge.py             #   语义层：自研 LLM-as-Judge（faithfulness/relevancy）
│   ├── judge_prompt.py      #   Judge 系统提示词（JSON 输出）
│   ├── report.py            #   单页 HTML 可视化报告
│   └── runner.py            #   评估运行器
│
├── backtest/                # 回测模块
│   ├── scenarios.py         #   5 个历史延期复盘场景
│   └── runner.py            #   回测运行器
│
├── graph/                   # LangGraph 编排层
│   ├── state.py             #   AgentState（TypedDict：messages/tool_results/iteration/final_answer 等）
│   ├── single_agent_graph.py#   单 Agent 状态图：分析→选工具执行→评估→生成答案（5 轮安全阀）
│   ├── context_compressor.py#   上下文压缩器（R4：summarization buffer）
│   └── checkpointer.py      #   状态持久化：sqlite/memory/none
│
├── agents/                  # Agent 层
│   ├── single_agent.py      #   单 Agent 入口
│   ├── router.py            #   AgentRouter：关键词路由
│   ├── review_agent.py      #   订单评审子 Agent（持 reviewer 令牌）
│   ├── production_agent.py  #   生产评估子 Agent（持 scheduler 令牌）
│   └── supervisor.py        #   SupervisorAgent：STS 签发+交换→分派→LLM 汇总→审计报告
│
├── auth/                    # 鉴权层（Harness 权限层）
│   ├── token_exchange.py    #   STS：签发用户令牌→交换受限子令牌（RFC 8693）
│   ├── guard.py             #   RBAC 守卫：工具层权限校验（洋葱第 3 层）
│   └── audit_logger.py      #   审计日志：trace_id 贯穿，JSONL 落盘
│
├── observability/           # 观测层（Harness 观测层）
│   ├── tracer.py            #   Span/Tracer：全链路计时与 token 用量（OTel 同构）
│   ├── exporter.py          #   导出 backend：none/console/otel(OTLP)
│   ├── cost.py              #   CostTracker：按 provider 计费 + 预算熔断
│   ├── dashboard.py         #   ★ Dashboard 数据层：KPI/成本/trace 落库 + 只读查询 + 静态 HTML 🆕M5b
│   └── case_collector.py    #   用例收集器（低分 case 归档）
│
├── schema/                  # 数据库 Schema（M1）🆕
│   ├── schema.sql           #   建表脚本（15 张表，写方唯一，幂等）
│   └── migrate.py           #   迁移工具：schema_version 管理 + 增量迁移
│
├── prompts/
│   └── system_prompts.py    # 各 Agent 系统提示词
│
└── data/                    # 运行数据（CSV 模式用，MySQL 模式可忽略）
    ├── *.csv                #   订单/库存/设备/客户数据
    ├── contracts/*.txt      #   3 份合同特殊条款
    ├── 历史延期记录.txt      #   延期复盘
    └── chroma_db/           #   Chroma 向量库（首次自动重建）
```

## 6. 架构图

```
                        ┌────────────┐
                        │  FastAPI   │  api.py: /ask /sim /schedule /kpi /dashboard
                        │   网关      │
                        └─────┬──────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
  ┌──────────────┐    ┌──────────────┐    ┌───────────────┐
  │  对话 Agent   │    │  排产工具链   │    │   Dashboard   │
  │ LangGraph     │    │  18 个工具   │    │ KPI/成本/trace│
  │ 单/多 Agent   │    │  scheduler_  │    │ observability│
  └──────┬───────┘    │  tools.py    │    └───────┬───────┘
         │            └──────┬───────┘            │
         │                   │                    │
         └──────────┬────────┘                    │
                    ▼                             │
         ┌─────────────────────┐                  │
         │    ToolRegistry     │  O(1) 查找 + RBAC + sandbox + tracer
         └──────────┬──────────┘                  │
                    │                             │
    ┌───────────────┼───────────────┐             │
    ▼               ▼               ▼             │
┌─────────┐  ┌───────────┐  ┌──────────┐          │
│ 订单/资源│  │  排产求解  │  │ RAG 检索  │          │
│ 工具     │  │  solver   │  │ retriever│          │
└────┬────┘  └─────┬─────┘  └────┬─────┘          │
     │             │              │                │
     ▼             ▼              ▼                ▼
  ┌──────────────────────────────────────────────────┐
  │              数据层  data.py  (M1)               │
  │     CSV / MySQL 双模式 + 连接池 + 事务 + 租户      │
  └──────────────────────────────────────────────────┘
                    ▲
                    │ 事件写入（B 层）
         ┌──────────┴──────────┐
         │   生产模拟器 (M3)    │
         │  engine + runner    │
         │  事件驱动 · 心跳线程  │
         └─────────────────────┘

  ════════════════════ Harness 三层 ════════════════════
       权限层              编排层              观测层
    auth/（STS+RBAC） graph/+agents/    observability/（trace+cost+dashboard）
```

## 7. 核心模块详解

### 7.1 数据层（M1）：从 CSV 到 MySQL

`tools/data.py` 提供统一数据访问接口，支持 CSV 和 MySQL 双模式，由 `DATA_SOURCE` 环境变量切换。

**关键能力**：
- `get_connection()`：从连接池取连接（MySQL 模式）
- `transaction()`：上下文管理器，单事务自动提交/回滚
- `load_orders() / load_parts() / load_machines() / ...`：统一加载函数，CSV/MySQL 透明切换
- 租户过滤：`FORCE_TENANT=true` 时所有查询强制加 `tenant_id` 条件
- `format_table()`：Dict 列表 → Markdown 表格（LLM 友好）

**写方唯一原则**（schema.sql 中每张表标注写方）：
| 表组 | 写方 | 读方 |
|------|------|------|
| 业务表（customer/orders/parts/machines/...） | seed + 模拟器 B 层 | solver / tools / forecast |
| 求解输出（schedule_versions/batches/...） | solver + approve_schedule | tools / dashboard |
| 模拟/审计（sim_clock/state_change_log/sim_events） | simulator | tools / dashboard |
| 配置（system_config） | 运维 / 配置 API | 全部模块 |

### 7.2 排产求解器（M2）

`scheduler/` 模块，基于 OR-Tools CP-SAT 的约束规划求解器。

**求解流程**：
```
snapshot（读一致性快照）
  → verify（C1-C9 前置校验，不满足直接返回冲突）
  → 装箱（按设备分组，版子装箱，单版单材料）
  → CP-SAT 建模（决策变量 + 约束 + 目标函数）
  → 求解（solver_max_time_seconds 预算，默认 60s）
  → 指标计算（准交率/延期数/目标值/批次统计）
  → persist 落库（schedule_versions + batches，状态=待审核）
```

**C1-C9 九大约束**：
- C1 订单完整性 / C2 材料匹配 / C3 设备能力 / C4 版子容量 / C5 承重上限
- C6 单版单材料 / C7 设备并行 / C8 产能上限 / C9 前道约束

**CLI 直接调用**：
```bash
python -m demo.scheduler.solver --solve --out result.json
```

### 7.3 生产模拟器（M3）

`simulator/` 模块，事件驱动的生产流程模拟器。

**核心机制**：
- **事件驱动**：订单到达 → 前道处理 → 上板 → 打印 → 下板 → 后道 → 完成，每个状态变更是一个事件
- **心跳线程**：`SimulatorRunner` 独立线程，每 `SIM_TICK_SECONDS`（默认 60s = 1 sim 小时）推进一拍
- **单事务推进**：每 tick 单事务内推进 sim 时钟 + A/B 层状态变更，失败整体回滚
- **连续失败熔断**：同一事件连续失败 10 次停止心跳，防脏数据卡死
- **缓存失效**：每 tick bump `llm_cache` 的 `scene_version`，状态相关精确缓存自动失效

**与排产求解器的关系**：
- 求解器（solver）：静态快照 → 最优排产方案（批次表）
- 模拟器（simulator）：动态推进真实生产，设备状态随时间变化
- Agent 同时有两类工具：`run_scheduling/query_schedule`（静态求解）和 `query_sim_events/query_kpi`（动态模拟）

### 7.4 排产工具链（M4a / M4b）

`tools/scheduler_tools.py`，18 个工具中 11 个已实装：

| 工具 | 模块 | 说明 |
|------|------|------|
| `run_scheduling` | M4a | 触发排产求解并落库（写工具，需审批后生效） |
| `query_schedule` | M4a | 查最新/指定排产版本 + 批次表 |
| `query_sim_events` | M4a | 查模拟器事件（类型/状态过滤） |
| `approve_schedule` | M4a | 排产版本审批：待审核→已审核/已驳回 |
| `query_load_assessment` | M4b | 设备负载评估（分区颜色 + 利用率） |
| `query_ctp` | M4b | 可承诺交期（CTP）：给定订单预计完成时间 |
| `query_order_tracking` | M4b | 订单跟踪：当前环节 + 历史轨迹 |
| `query_preprocess_load` | M4b | 前道负载（待处理任务数 + 产能估算） |
| `query_kpi` | M4b | KPI 指标（准交率/在制数/利用率/延期数） |
| `query_forecast` | M5 | 需求预测（占位，M5a 实装） |
| `query_yield` | M5 | 良率预测（占位，M5 后续） |

### 7.5 统计预测（M5a）

`forecast/` 模块，纯函数 + 聚合入口。

**预测模型**：
- 移动平均（moving_average）：窗口 N 天均值
- 指数平滑（exponential_smoothing）：α 可调，默认 0.3

**聚合维度**：按 `order_date` 逐日分材料聚合（件数 + 机时），机时 = Σ(height ÷ rate × quantity)。

> 仅支持 MySQL 模式（CSV orders 无 order_date 列）。

### 7.6 KPI 看板（M5b）

`observability/dashboard.py`，三层职责：

1. **落库（写方唯一）**：
   - simulator tick → `record_kpi_snapshot`（KPI 快照）
   - api /ask → `record_cost` + `record_trace`（query 粒度成本 + trace）

2. **查询（只读）**：
   - `/dashboard/kpi-history`：KPI 时间序列
   - `/dashboard/costs`：按模型/按天成本统计
   - `/dashboard/traces`：最近 trace 列表

3. **兜底**：`render_static_html` 生成零 CDN 离线 HTML 看板。

## 8. API 端点一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查（provider/工具/缓存/checkpointer 配置） |
| POST | `/ask` | 单次/多轮提问（{query, thread_id?}） |
| GET | `/threads/{id}/history` | 多轮会话历史 |
| POST | `/sim/start` | 启动模拟器心跳 |
| POST | `/sim/stop` | 停止模拟器心跳 |
| GET | `/sim/status` | 模拟器状态（运行中/停止/模拟时间） |
| GET | `/schedule/latest` | 最新排产版本 + 批次表 |
| POST | `/schedule/load` | 触发求解 + 落库（需 admin token） |
| GET | `/order/{id}/tracking` | 订单跟踪详情 |
| GET | `/kpi` | 当前 KPI 指标 |
| GET | `/dashboard/kpi-history` | KPI 历史快照 |
| GET | `/dashboard/costs` | 成本统计 |
| GET | `/dashboard/traces` | Trace 列表 |
| GET | `/debug/cases` | 收集的 case（调试用） |

## 9. 环境变量全表

### v1 基础变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VOLC_API_KEY` | - | 火山豆包 API Key（主 provider） |
| `DEEPSEEK_API_KEY` | - | DeepSeek API Key（备 provider） |
| `CHECKPOINTER` | `sqlite` | 状态持久化：sqlite/memory/none |
| `SEMANTIC_CACHE` | `on` | 语义缓存开关 |
| `CACHE_THRESHOLD` | `0.20` | 语义缓存阈值（cosine distance 上限） |
| `LLM_CACHE` | `on` | L1 精确缓存开关 |
| `LLM_CACHE_TTL` | `3600` | L1 缓存 TTL（秒） |
| `OTEL_EXPORTER` | `console` | 观测导出：none/console/otel |
| `LLM_BUDGET_LIMIT` | `5.0` | LLM 预算上限（元） |
| `TOKEN_STORE` | `sqlite` | Token 存储：sqlite/memory |
| `AUDIT_LOG` | `on` | 审计落盘：on/none |
| `GUARDRAILS_MODE` | `warn` | 护栏模式：block/warn/off |
| `MCP_MODE` | `local` | 工具调用模式：local/mcp |
| `FORCE_TENANT` | `false` | 强制租户隔离 |

### R1-R8 缺陷修复新增

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TOOL_TIMEOUT` | `10` | 单次工具调用超时秒数（R1） |
| `TOOL_MAX_RETRIES` | `3` | 最大重试次数（R1） |
| `CONTEXT_MAX_CHARS` | `8000` | 触发上下文压缩的字符阈值（R4） |
| `CONTEXT_KEEP_RECENT` | `6` | 压缩后保留的最近消息数（R4） |

### v2 制造业主线新增 🆕

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATA_SOURCE` | `csv` | 数据源：csv / mysql（M1） |
| `DB_HOST` | `127.0.0.1` | MySQL 主机（M1） |
| `DB_PORT` | `3306` | MySQL 端口（M1） |
| `DB_USER` | `root` | MySQL 用户（M1） |
| `DB_PASSWORD` | - | MySQL 密码（M1） |
| `DB_NAME` | `demo_scheduling` | MySQL 库名（M1） |
| `DB_POOL_SIZE` | `5` | 连接池大小（M1） |
| `SIM_TICK_SECONDS` | `60` | 模拟器心跳间隔（秒），默认 60s = 1 sim 小时（M3） |
| `SOLVER_MAX_TIME` | `60` | CP-SAT 求解时间预算（秒）（M2） |

## 10. 运行评估与测试

```bash
# 全量单测 + 集成测试（mock LLM，零成本）
python run_all_tests.py

# 三层评估：工具 / 轨迹 / 语义（需真实 LLM）
python -m demo.eval.runner
python -m demo.eval.runner --case eval_001   # 单个 case
python -m demo.eval.runner --no-judge        # 跳过 LLM-as-Judge
python -m demo.eval.runner --report          # 生成 HTML 报告

# 回测：历史延期复盘
python -m demo.backtest.runner

# 排产求解器单测
python -m pytest demo/scheduler/test_solver.py -v

# 模拟器单测
python -m pytest demo/simulator/ -v
```

## 11. 验收清单

### v1 能力（已全部验收）
- [x] `python -m demo.main --check` 地基自检通过
- [x] 单 Agent 模式：订单问题多工具调用 + 综合回答
- [x] 单 Agent 模式：RAG 问题命中合同（rerank 分 >0.9）
- [x] 多 Agent 模式：Supervisor 分派 + RBAC 拒绝越权 + 审计报告
- [x] 观测层：trace 摘要含 LLM token 用量与工具延迟
- [x] 状态持久化：`--chat` 多轮对话，重启可恢复
- [x] 语义缓存：相似问题命中，无关问题不误命中
- [x] 成本监控 + 预算熔断
- [x] Token 持久化 + 审计持久化
- [x] R1 工具沙箱 / R2 输出护栏 / R3 步骤校验 / R4 上下文压缩
- [x] R5 MCP 隔离 / R6 三层评估 / R7 结构化筛选 / R8 多租户

### v2 制造业主线（M1-M5b）🆕
- [x] **M1 数据层**：MySQL 双模式 + 连接池 + 事务 + 租户过滤
- [x] **M2 求解器**：CP-SAT 约束规划 + 装箱 + C1-C9 校验 + 落库
- [x] **M3 模拟器**：事件驱动引擎 + 心跳线程 + 连续失败熔断
- [x] **M4a 调度闭环**：18 个排产工具（求解/查排产/模拟事件/审批）
- [x] **M4b 产能评估**：负载/CTP/订单跟踪/前道/KPI
- [x] **M5a 统计预测**：指数平滑 + 移动平均，分材料日级预测
- [x] **M5b KPI 看板**：KPI 快照落库 + Dashboard 查询端点 + 静态 HTML
- [x] **Schema**：15 张表建表脚本 + 迁移工具 + 写方唯一标注
- [x] **API 扩展**：/sim/* + /schedule/* + /kpi + /dashboard/*
- [x] **全量测试**：pytest 覆盖求解器/模拟器/数据层/工具/Dashboard

## 12. 演进历程

| 阶段 | 时间 | 核心内容 |
|------|------|---------|
| week1-4 | 2026-07 | 单文件脚本：call_llm → RAG → 单 Agent → 多 Agent |
| v1 整合 | 2026-08-04 | 工程化整合为分层项目（Harness 三层架构） |
| R1-R8 | 2026-08-07 | 8 大缺陷修复：沙箱/护栏/步骤校验/压缩/MCP/评估/筛选/租户 |
| 评估升级 | 2026-08-09 | 三层评估体系（工具/轨迹/语义）+ 回测 + 行业差距报告 |
| **M1 数据层** | 2026-08-22 | CSV → MySQL 抽象，连接池，事务，租户过滤 |
| **M2 求解器** | 2026-08-22 | OR-Tools CP-SAT + 装箱模型 + C1-C9 校验 |
| **M3 模拟器** | 2026-08-23 | 事件驱动引擎 + 心跳线程 + A/B 层状态流转 |
| **M4a 调度闭环** | 2026-08-23 | 18 个排产工具 + Agent 可触发求解/审批 + prompt 版本回滚 |
| **M4b 人机协同** | 2026-08-24 | 审批流 + 产能评估 + CTP + 订单跟踪 + 前道负载 |
| **M5a 预测** | 2026-08-24 | 指数平滑 + 移动平均，分材料日级需求预测 |
| **M5b 看板** | 2026-08-25 | KPI 快照 + Dashboard + 静态 HTML |
| **v2.0** | 2026-08-25 | 本版本：完整排产智能体闭环 |

## 13. 相关文档

### 需求 / 规格

| 文档 | 说明 |
|------|------|
| [需求规格 v1](../docs/demo/02-specs/需求规格-v1-2026-08-21.md) | 范围/功能/非功能/验收标准 |
| [部署指南 v1](../docs/demo/部署指南-v1-2026-08-25.md) | 生产部署完整指南 |
| [生产化蓝图](../docs/demo/生产化差距与部署蓝图-v1-2026-08-22.md) | 差距分析 + 部署方案 |

### 代码阅读

| 文档 | 说明 |
|------|------|
| [代码阅读指南 v2.0](./代码阅读指南-v2.0-2026-08-25.md) | 从底层到上层 22+ 层详细阅读路线 + 评估体系深度解析 |
| [8 大缺陷改造方案](../docs/week5/8大缺陷-可执行代码改造方案.md) | R1-R8 修复方案 |
| [v2 重构方案](../docs/demo/04-plans/) | M1-M6 分阶段重构计划 |

### 评估报告

| 文档 | 说明 |
|------|------|
| [制造业智能体缺失评估报告](../docs/week6/demo-制造业智能体缺失评估报告-2026-08-09.md) | 行业基线 + 11 位评审团 + M1-M13 差距 |
| [三层评估体系实现](../docs/superpowers/plans/2026-08-08-ragas升级-三层评估体系.md) | 评估改造前的完整实现计划 |
