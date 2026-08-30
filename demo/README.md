# demo -- 制造业排产智能体（v3.0 · 2026-08-30）

> [AI:Claude] 架构设计 + 实现。从 week1-week5 的对话式 Agent 助手，演进为完整的制造业排产智能体系统：**约束求解器 + 生产模拟器 + Agent 调度闭环 + 自动排产调度器 + 统计预测 + KPI 看板 + Web 控制台**。
>
> 需求规格 v1：[docs/demo/02-specs/需求规格-v1-2026-08-21.md](../docs/demo/02-specs/需求规格-v1-2026-08-21.md)
> 排程排产全链路自动化：[docs/demo/02-specs/2026-08-28-排程排产全链路自动化-定稿-v1.md](../docs/demo/02-specs/2026-08-28-排程排产全链路自动化-定稿-v1.md)
> 部署指南 v2：[docs/demo/10-deployment/部署指南-v2-2026-08-30.md](../docs/demo/10-deployment/部署指南-v2-2026-08-30.md)
> 部署指南 v1：[docs/demo/10-deployment/部署指南-v1-2026-08-25.md](../docs/demo/10-deployment/部署指南-v1-2026-08-25.md)
> 生产化蓝图：[docs/demo/10-deployment/生产化差距与部署蓝图-v1-2026-08-22.md](../docs/demo/10-deployment/生产化差距与部署蓝图-v1-2026-08-22.md)
> 功能介绍：[docs/demo/功能介绍-v1-2026-08-30.md](../docs/demo/11-manuals/功能介绍-v1-2026-08-30.md)
> 代码阅读指南 v3.0：[代码阅读指南-v3.0-2026-08-30.md](../docs/demo/11-manuals/代码阅读指南-v3.0-2026-08-30.md)

## 1. 这个 demo 能做什么

一个面向**制造业 3D 打印排程排产**的完整智能体系统。从对话式问答（v1）升级为**排产求解 → 模拟执行 → Agent 调度 → 自动排产 → 预测分析 → 看板观测**的闭环系统（v3）。

### v1 能力（对话式助手）
- **单 Agent 模式**：一个 Agent + 工具注册表，自主决定调用工具、循环调用直到拿到足够信息再回答（LangGraph 编排）
- **多 Agent 模式（Supervisor）**：主管 Agent 路由到专业子 Agent（订单评审 / 生产评估），子 Agent 持受限令牌调用工具，主管汇总，带 RBAC 鉴权 + 审计日志
- **合同知识库（RAG）**：向量 + BM25 + RRF + Cross-Encoder 混合检索，命中合同原文
- 能回答的问题：订单排期 / 订单详情 / 紧急情况 / 客户评估 / 库存影响

### v2 新增能力（制造业主线）
- **M1 数据层改造**：CSV → MySQL 抽象层，连接池，事务管理，读写分离，租户过滤
- **M2 排产约束求解器**：OR-Tools CP-SAT 约束规划 + 装箱模型，支持 C1-C9 九大约束校验，输出结构化排产表（批次表 + 指标）
- **M3 生产模拟器**：事件驱动模拟引擎，订单到达 → 前道 → 打印 → 完成全流程，心跳线程持续推进仿真时间
- **M4a Agent 调度闭环**：18 个排产工具（求解/查排产/查模拟事件/审批/产能/CTP/跟踪/KPI），Agent 可触发求解、查询排产、审批版本
- **M4b 人机协同 + 产能评估**：排产版本审批流（待审核→已审核/已驳回），产能负载评估，可承诺交期（CTP），订单跟踪，前道负载
- **M5a 统计预测**：指数平滑 + 移动平均，需求预测按日分材料聚合（件数 + 机时）
- **M5b KPI 看板 Dashboard**：KPI 快照落库 + 成本记录 + trace 记录，只读查询端点，零 CDN 静态 HTML 看板
- **Schema 建表脚本**：15 张业务表，写方唯一原则，幂等建表，外键拓扑

### v3 新增能力（自动化 + 前端）🆕
- **自动排产调度器（AutoScheduler）**：容器内后台线程，随模拟器 tick 周期自动排产 + 版本级 FIFO 自动审批，设备故障/插单事件触发即时重排兜底，实现「自动排版 → 自动关联设备 → 自动审核通过 → 模拟器推进」全链路无人值守
- **排程排产全链路自动化**：订单状态机（待排队 → 已审核 → 打印中 → 完成）贯穿流转，排产幂等防重复打印，审批门禁（模拟器只推进已通过版本），前道任务随批次生成（C9 前道完成 ≤ 打印开始）
- **Web 前端控制台**：Vue3 + Element Plus + ECharts 单页应用，6 个 tab 聚合（排产看板 / 排产调试台 / 排产审批 / 案例台 / 资源聚合 / 配置页）
- **排产调试台**：自然语言提问 → 触发工具 → 答案 + 两级链路树（入参/出参/耗时/成功）+ LLM-as-Judge 打分
- **Case 治理**：每次提问自动落盘 cases.jsonl，人工标注 good/bad，按 trace_id 回放/重跑，bad→good 转化率统计
- **资源聚合页 + 人员模块**：设备/客户/订单/库存/批次/前道/人员 7 类资源只读聚合，人员状态（上班/请假）切换与模拟器 leave 联动
- **循环守卫 + 缓存门禁**：同工具同参数连续 ≥3 次判定循环并产出用户友好兜底，守卫 dump 永不写入语义缓存；语义缓存阈值收紧至 0.10 消除跨实体误命中
- **审核意图识别**：区分「查询已审核数据」与「把 XX 审核通过」，查询场景不再误注入审批指令

## 2. 前置条件

### 基础依赖
```bash
# Python 3.11+
pip install openai httpx chromadb sentence-transformers rank-bm25 jieba langgraph
pip install mcp              # MCP 架构展示（非必需）
```

### v2 新增依赖
```bash
# 排产求解器（M2）
pip install ortools
# MySQL 数据层（M1）
pip install pymysql DBUtils
# FastAPI 网关 + 观察
pip install fastapi uvicorn redis opentelemetry-api opentelemetry-sdk
```

### 数据库（v2 必需）
MySQL 8.0+，库名 `demo_scheduling`，建表脚本见 `demo/schema/schema.sql`：
```bash
python -m demo.schema.migrate --up    # 幂等迁移（schema_version 管理）
```

### 环境变量（项目根目录 `.env`）
```ini
# LLM Provider（DeepSeek 主用，火山豆包备用，失败自动降级）
DEEPSEEK_API_KEY=...           # 主用 · ¥1/百万 Token
VOLC_API_KEY=...               # 备用1 · 火山豆包编程套餐
PRIMARY_PROVIDER=              # 可选：提权重排主备，如 "火山豆包(coding)"

# MySQL（v2，M1）
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=demo_sched
MYSQL_PASSWORD=...
MYSQL_DB=demo_scheduling
DEMO_DATA_SOURCE=mysql          # mysql | csv（默认 csv，兼容 v1）

# 自动排产调度器（v3）
AUTO_SCHEDULE_ENABLED=on        # off 关闭自动排产
AUTO_SCHEDULE_TICK_INTERVAL=3   # 每 N 个模拟 tick 排一轮
AUTO_APPROVE_TOP_N=5            # 保留最近 N 个待审核版本，更早自动通过
FIFO_AGE_TIMEOUT=24             # 最早待审版本超龄兜底（模拟小时）
STATUS_RESERVE_TOP_N=5          # 各订单状态保留最新 N 单不被推进（演示保底）
```

> 敏感信息双源：优先环境变量，回落到 `docs/demo/credentials.local.md`（gitignored，占位符 `{{MYSQL_PASSWORD}}` 替换为真实值）。未配置时给中文报错提示。

### 本地模型缓存（RAG 真连必需）
- 向量嵌入：Chroma 默认 ONNX MiniLM（`~/.cache/chroma/onnx_models/`）
- 重排器：`BAAI/bge-reranker-base`（`~/.cache/huggingface/hub/`）

## 3. 快速开始

```bash
cd projects/agent-training

# 0. 建表（首次，v2 必需）
python -m demo.schema.migrate --up

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

# ── v2 制造业主线 ──

# 6. 求解一轮排产并落库（M2 + M4a）
python -m demo.main --init-schedule

# 7. 启动生产模拟器心跳（M3 + M4a，Ctrl+C 停止）
python -m demo.main --sim

# 8. Prompt 版本回滚（R-4 安全回滚）
python -m demo.main --rollback v1

# 9. 启动 FastAPI 网关（含看板端点 + 自动排产调度 + 前端托管）
uvicorn demo.api:app --host 0.0.0.0 --port 8000

# ── v3 新增 ──

# 10. Docker 一键起（构建镜像 + 启动 + 自动排产调度）
docker compose up -d --build

# 11. 签发 admin token（调试台/写端点鉴权，1h 有效）
python -m demo.auth.mint admin

# 12. 构建前端控制台（web/dist，FastAPI 同源托管）
cd web && npm install && npm run build
```

> 本项目测试/构建/部署均在 WSL 下运行（默认 UTF-8），不涉及 Windows GBK 兼容；`npm run build` 含 `vue-tsc` 类型门禁。

## 4. 调用建议

| 场景 | 推荐命令 | 为什么 |
|------|---------|--------|
| 验证环境是否配好 | `--check` | 不调 LLM 也能确认工具/数据层 OK，最快排障 |
| 单一问题快速回答 | `python -m demo.main "问题"` | 单 Agent 足够，链路短、token 省 |
| 涉及多角色协同 | `--mode multi "..."` | Supervisor 分派子 Agent，各持权限令牌，演示 RBAC |
| 合同/条款类问题 | 任意模式问"合同""条款" | 自动触发 `search_knowledge_base`（RAG 工具） |
| **想看真实排产结果** | `--init-schedule` | 跑 CP-SAT 求解器，产出结构化批次表 + 准交率指标 |
| **想看动态模拟** | `--sim` + `--init-schedule` | 先求解 → 启模拟器，看订单在各环节流转、设备状态变化 |
| **看 KPI 看板** | 起 API → 浏览器访问 `/` | Web 控制台排产看板 tab（ECharts 曲线 + 成本 + trace） |
| **看自动排产运行** | 起 API → `GET /scheduler/status` | 自动调度器运行态（enabled/interval/topN/runs/上次触发） |
| **交互式调试** | 浏览器访问 `/portal/debug` | 自然语言提问 + 两级链路树 + judge 打分 |
| **正式演示** | 调试台提问 A1→...→L2（见功能介绍 §5） | 15 分钟脚本覆盖全部能力 |
| 看完整效果 | `--demo` | 5 个预设场景覆盖订单/资源/客户/RAG 各类工具 |

**v3 推荐体验路径**：先 `--check` → 建表 → `docker compose up -d`（自动排产调度启动）→ 浏览器开 `/` 看板 → `/portal/debug` 提问 → 审批页审版本 → 资源页查数据。

## 5. 目录说明

```
demo/
├── __init__.py              # 包入口
├── main.py                  # 统一入口：--check/--demo/--sim/--init-schedule/--rollback
├── api.py                   # FastAPI 网关（28 端点 + 前端托管 + 自动调度启动）
├── config.py                # 统一 .env 加载 + PROVIDERS + credentials 双源 + 全部配置
│
├── core/                    # 基座层
│   ├── llm_client.py        #   call_llm + 主备降级 + L1 缓存 + B3 模型路由
│   ├── response.py          #   统一 API 响应格式（code/message/data/trace_id）
│   ├── logging_setup.py     #   统一日志配置
│   └── utils.py             #   通用工具（JSON 转换/格式化/参数校验）
│
├── cache/                   # 缓存层（两级缓存统一入口）
│   ├── manager.py           #   CacheManager：L1+L2 facade（P0-3）
│   ├── llm_cache.py         #   L1 精确缓存（SQLite，<1ms）
│   └── semantic_cache.py    #   L2 语义缓存（Chroma cosine，阈值 0.10，状态类短 TTL）
│
├── tools/                   # 工具层（MCP 架构，18 个工具）
│   ├── data.py              #   数据层抽象：CSV + MySQL 双模式 + 连接池 + 事务 + 租户过滤
│   ├── order_tools.py       #   订单工具：query_orders（8 字段 AND 筛选/排序/limit）
│   ├── resource_tools.py    #   资源工具：库存 / 设备 / 客户
│   ├── scheduler_tools.py   #   ★ 排产工具（11 个）：求解/查排产/模拟事件/审批/产能/CTP/跟踪/KPI/预测/良率
│   ├── registry.py          #   ToolRegistry：O(1) 查找 + 参数白名单 + RBAC + tracer + sandbox
│   ├── sandbox.py           #   工具沙箱（R1：超时 + 指数退避重试）
│   ├── mcp_client.py        #   MCP Client（R5：stdio 子进程通信）
│   └── mcp_servers.py       #   FastMCP server 构建（展示 MCP 协议）
│
├── scheduler/               # ★ 排产求解器 + 自动调度器（M2/v3）
│   ├── auto_scheduler.py    #   ★ AutoScheduler：后台线程 tick 周期排产 + FIFO 审批 + 事件重排 🆕
│   ├── snapshot.py          #   读一致性快照（仅待排队订单 + 空闲设备）
│   ├── verify.py            #   C1-C9 约束校验（9 条硬约束前置检查）
│   ├── model.py             #   装箱模型 + CP-SAT 约束规划（工艺组级部分成功）
│   ├── solver.py            #   求解入口 + persist 落库（版本/批次/前道任务/订单锁定/sim 锚点）
│   ├── assessment.py        #   产能评估（M4b）：负载/CTP/前道/跟踪/KPI
│   └── test_*.py            #   各模块单元测试
│
├── simulator/               # ★ 生产模拟器（M3）
│   ├── clock.py             #   模拟时钟（加速比可配）
│   ├── constants.py         #   业务常量（等级分/尺寸/优先级计算）🆕
│   ├── events.py            #   事件定义（订单到达/上板/下板/完成/restock 等）
│   ├── states.py            #   状态管理（设备/订单状态流转 + ORDER_TRANSITIONS）
│   ├── engine.py            #   模拟引擎：事件驱动，A/B 层单事务推进 + 审批门禁
│   ├── runner.py            #   心跳运行器 + 事件触发 request_rerun 重排
│   ├── seed.py              #   初始数据播种（20 单，写方唯一）
│   └── test_*.py            #   各模块单元测试 + e2e
│
├── forecast/                # ★ 统计预测（M5a）
│   ├── models.py            #   预测模型：指数平滑 + 移动平均（纯函数）
│   └── forecaster.py        #   聚合入口：读 MySQL → 逐日分材料预测
│
├── rag/                     # 合同知识库混合检索
│   ├── knowledge_base.py    #   文档加载/分块/Chroma 向量库
│   └── retriever.py         #   BM25 + 向量 + RRF 融合 + Cross-Encoder 重排 + 权限过滤
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
│   ├── judge.py             #   语义层：LLM-as-Judge（faithfulness/relevancy）
│   ├── judge_prompt.py      #   Judge 系统提示词（JSON 输出）
│   ├── report.py            #   单页 HTML 可视化报告
│   ├── ragas_regression.py  #   RAGAS 四指标回归（Q1-Q5）🆕
│   └── runner.py            #   评估运行器
│
├── backtest/                # 回测模块
│   ├── scenarios.py         #   5 个历史延期复盘场景
│   └── runner.py            #   回测运行器
│
├── graph/                   # LangGraph 编排层
│   ├── state.py             #   AgentState（TypedDict）
│   ├── single_agent_graph.py#   ★ 单 Agent 状态图：意图分析→工具→评估→汇总（5 轮安全阀）
│   ├── context_compressor.py#   上下文压缩器（R4）
│   └── checkpointer.py      #   状态持久化：sqlite/memory/none
│
├── agents/                  # Agent 层
│   ├── single_agent.py      #   单 Agent 入口（缓存守卫 + 状态敏感分类）
│   ├── router.py            #   AgentRouter：关键词路由
│   ├── review_agent.py      #   订单评审子 Agent（持 reviewer 令牌）
│   ├── production_agent.py  #   生产评估子 Agent（持 scheduler 令牌）
│   └── supervisor.py        #   SupervisorAgent：STS 签发+交换→分派→LLM 汇总→审计
│
├── auth/                    # 鉴权层（Harness 权限层）
│   ├── token_exchange.py    #   STS：签发用户令牌→交换受限子令牌（RFC 8693）
│   ├── guard.py             #   RBAC 守卫（洋葱第 3 层）+ 写工具配额
│   ├── quota.py             #   WriteQuota：写工具 5min 滑窗配额（R-D2）🆕
│   ├── mint.py              #   本地签发 Token CLI（调试台鉴权用）🆕
│   └── audit_logger.py      #   审计日志：trace_id 贯穿，JSONL 落盘
│
├── observability/           # 观测层（Harness 观测层）
│   ├── tracer.py            #   Span/Tracer：全链路计时与 token 用量
│   ├── exporter.py          #   导出 backend：none/console/otel(OTLP)
│   ├── cost.py              #   CostTracker：按 provider 计费 + 预算熔断
│   ├── dashboard.py         #   Dashboard 数据层：KPI/成本/trace 落库 + 只读查询 + 静态 HTML
│   ├── request_context.py   #   全链路 trace_id 上下文（contextvars）🆕
│   └── case_collector.py    #   用例收集器（低分 case 归档 + 调试台治理）
│
├── schema/                  # 数据库 Schema（M1）
│   ├── schema.sql           #   建表脚本（19 张表，写方唯一，幂等）
│   └── migrate.py           #   迁移工具：schema_version 管理（v1-v4）+ 增量迁移
│
├── prompts/
│   ├── system_prompts.py    #   各 Agent 系统提示词
│   └── versioning.py        #   Prompt 版本化（versions.json + 回滚）🆕
│
└── data/                    # 运行数据（CSV 模式用，MySQL 模式可忽略）
    ├── *.csv                #   订单/库存/设备/客户数据
    ├── contracts/*.txt      #   3 份合同特殊条款
    └── chroma_db/           #   Chroma 向量库（首次自动重建）

web/                        # 前端控制台（Vue3 + Vite + Element Plus + ECharts）🆕
├── src/views/               #   6 个视图：Portal/Dashboard/Debug/Cases/Schedule/Resources/Config
├── src/api/                 #   5 个 API 客户端：dashboard/debug/config/schedule/resources
└── dist/                    #   构建产物（FastAPI 同源托管）
```

## 6. 架构图

```
                        ┌────────────┐
                        │  FastAPI   │  api.py：28 端点 + 前端托管 + 自动调度启动
                        │   网关      │
                        └─────┬──────┘
                              │
         ┌────────────────────┼────────────────────┬──────────────┐
         ▼                    ▼                    ▼              ▼
  ┌──────────────┐    ┌──────────────┐    ┌───────────────┐  ┌─────────────┐
  │  对话 Agent   │    │  排产工具链   │    │   Dashboard   │  │  Web 控制台  │ 🆕
  │ LangGraph     │    │  18 个工具   │    │ KPI/成本/trace│  │ Vue3 6-tab  │
  │ 单/多 Agent   │    │  scheduler_  │    │ observability│  │ 看板/调试台  │
  └──────┬───────┘    │  tools.py    │    └───────┬───────┘  │ /审批/案例   │
         │            └──────┬──────┘            │          │ /资源/配置   │
         │                   │                   │          └──────┬──────┘
         └──────────┬────────┘                   │                 │ 只读 API
                    ▼                            │                 │
         ┌─────────────────────┐                 │                 │
         │    ToolRegistry     │  O(1) 查找 + RBAC + quota + sandbox
         └──────────┬──────────┘                 │
                    │                            │
    ┌───────────────┼───────────────┐            │
    ▼               ▼               ▼            │
┌─────────┐  ┌───────────┐  ┌──────────┐         │
│ 订单/资源│  │  排产求解  │  │ RAG 检索  │         │
│ 工具     │  │  solver   │  │ retriever│         │
└────┬────┘  └─────┬─────┘  └────┬─────┘         │
     │             │              │                │
     ▼             ▼              ▼                ▼
  ┌──────────────────────────────────────────────────┐
  │              数据层  data.py  (M1)               │
  │     CSV / MySQL 双模式 + 连接池 + 事务 + 租户      │
  └──────────────────────────────────────────────────┘
                    ▲
                    │ 事件写入（B 层）+ 自动排产（v3）
         ┌──────────┴──────────┐
         │   生产模拟器 (M3)    │◄── AutoScheduler 🆕
         │  engine + runner    │    tick 周期排产 + FIFO 审批
         │  事件驱动 · 心跳线程  │    事件 request_rerun 重排
         └─────────────────────┘

  ════════════════════ Harness 三层 ════════════════════
       权限层              编排层              观测层
    auth/（STS+RBAC+配额） graph/+agents/    observability/（trace+cost+dashboard）
```

## 7. 核心模块详解

### 7.1 数据层（M1）：从 CSV 到 MySQL

`tools/data.py` 提供统一数据访问接口，支持 CSV 和 MySQL 双模式，由 `DEMO_DATA_SOURCE` 环境变量切换。

**关键能力**：
- `get_connection()`：从连接池取连接（MySQL 模式，PooledDB）
- `transaction()`：上下文管理器，单事务自动提交/回滚
- `load_orders() / load_parts() / load_machines() / ...`：统一加载函数，CSV/MySQL 透明切换
- 租户过滤：`FORCE_TENANT=true` 时所有查询强制加 `tenant_id` 条件
- `format_table()`：Dict 列表 → Markdown 表格（LLM 友好）

**写方唯一原则**（schema.sql 中每张表标注写方）：
| 表组 | 写方 | 读方 |
|------|------|------|
| 业务表（customer/orders/parts/machines/...） | seed + 模拟器 B 层 | solver / tools / forecast |
| 求解输出（schedule_versions/batches/preprocess_tasks） | solver + auto_scheduler | tools / dashboard |
| 模拟/审计（sim_clock/state_change_log/sim_events） | simulator | tools / dashboard |
| 配置（system_config） | 运维 / 配置 API | 全部模块 |

### 7.2 排产求解器（M2）

`scheduler/` 模块，基于 OR-Tools CP-SAT 的约束规划求解器。

**求解流程**：
```
snapshot（读一致性快照，仅待排队订单 + 空闲设备）
  → verify（C1-C9 前置校验，不满足直接返回冲突）
  → 装箱（按设备分组，版子装箱，单版单材料）
  → CP-SAT 建模（决策变量 + 约束 + 目标函数，工艺组级部分成功）
  → 求解（solver_max_time_seconds 预算，默认 20s，model 层回落 60s）
  → 指标计算（准交率/延期数/目标值/批次统计）
  → persist 落库（schedule_versions + batches + preprocess_tasks + 订单锁定 + sim 锚点）
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
- **审批门禁**（v3）：模拟器只推进 `approval_status='通过'` 的批次（待上机→打印中、前道→待上机均加门禁）
- **连续失败熔断**：同一事件连续失败 10 次停止心跳，防脏数据卡死
- **缓存失效**：每 tick bump `llm_cache` 的 `scene_version`，状态相关精确缓存自动失效

### 7.4 排产工具链（M4a / M4b）

`tools/scheduler_tools.py`，18 个工具中 11 个排产工具全部实装：

| 工具 | 模块 | 说明 |
|------|------|------|
| `run_scheduling` | M4a | 触发排产求解并落库（写工具，幂等锁定待排队订单） |
| `query_schedule` | M4a | 查最新/指定排产版本 + 批次表 |
| `query_sim_events` | M4a | 查模拟器事件（类型/状态过滤） |
| `approve_schedule` | M4a | 排产版本审批：待审核→已审核/已驳回（驳回回退订单） |
| `query_load_assessment` | M4b | 设备负载评估（分区颜色 + 利用率 + 三区制） |
| `query_ctp` | M4b | 可承诺交期（CTP）：给定订单预计完成时间 + 预测校准 |
| `query_order_tracking` | M4b | 订单跟踪：当前环节 + 历史轨迹 + 前面单据队列 |
| `query_preprocess_load` | M4b | 前道负载（落库 SUM 口径 + 未完成且已通过过滤） |
| `query_kpi` | M4b | KPI 指标（准交率/延期金额/舱利用率/良率/前道瓶颈） |
| `query_forecast` | M5 | 需求预测（指数平滑 + 移动平均，分材料日级） |
| `query_yield` | M5 | 良率分析（总览→设备→批次→材料 + LLM 改善建议） |

### 7.5 统计预测（M5a）

`forecast/` 模块，纯函数 + 聚合入口。

**预测模型**：
- 移动平均（moving_average）：窗口 N 天均值
- 指数平滑（exponential_smoothing）：α 可调，默认 0.3

**聚合维度**：按 `order_date` 逐日分材料聚合（件数 + 机时），机时 = Σ(height ÷ rate × quantity)。

> 仅支持 MySQL 模式（CSV orders 无 order_date 列）。

### 7.6 KPI 看板（M5b）

`observability/dashboard.py`，三层职责：

1. **落库（写方唯一）**：simulator tick → `record_kpi_snapshot`；api /ask → `record_cost` + `record_trace`
2. **查询（只读）**：`/dashboard/kpi-history`、`/dashboard/costs`、`/dashboard/traces`
3. **兜底**：`render_static_html` 生成零 CDN 离线 HTML 看板

### 7.7 自动排产调度器（v3）🆕 ★

`scheduler/auto_scheduler.py`，容器内后台线程，实现排产 + 审批全自动。

**三层触发**：
1. **cron 周期**：主循环按模拟器 tick 节流（`current_sim_time` 变化计 tick），累计满 `AUTO_SCHEDULE_TICK_INTERVAL` 跑一轮排产 + FIFO 审批
2. **模拟器事件**：`runner` tick 尾检测设备故障/插单/延期告警 → `request_rerun()` 即时重排兜底
3. **Agent 语义**：`run_scheduling` 工具触发（已有，保持不动）

**FIFO 自动审批**：保留最近 `AUTO_APPROVE_TOP_N`（默认 5）个待审核版本给人审，更早的自动通过；最早待审版本龄期 ≥ `FIFO_AGE_TIMEOUT`（默认 24 模拟小时）自动通过兜底（防长期无新单导致停滞）。

**状态留底守卫**：排产前查待排队订单数，≤ `STATUS_RESERVE_TOP_N` 跳过本轮排产（保留演示样本）；> topN 时排除最新 N 单不锁定，保证任意状态随时可查。

**并发控制**：`threading.Lock` 保证同一时刻仅一个 `run_scheduling` 在跑（CP-SAT 不可并发）。

### 7.8 Web 前端控制台（v3）🆕

`web/`，Vue3 + Vite + TypeScript + Element Plus + ECharts 单页应用，由 FastAPI 同源托管。

| Tab | 视图 | 功能 |
|-----|------|------|
| 排产看板 | DashboardView | KPI 走势折线 + LLM 成本分模型柱状图 + Trace 摘要表 |
| 排产调试台 | DebugView | 自然语言提问 → 两级链路树（入参/出参/耗时）+ judge 打分 |
| 排产审批 | ScheduleView | 排产版本列表 + 通过/驳回（admin token 自动签发） |
| 案例台 | CasesView | case 统计 + 标注 good/bad + 回放/重跑 + bad→good 转化率 |
| 资源聚合 | ResourcesView | 设备/客户/订单/库存/批次/前道/人员 7 类资源，人员状态切换 |
| 配置页 | ConfigView | 数据源 / 模拟时钟 / 求解器预算 / 调试台三开关 |

### 7.9 排程排产全链路自动化（v3）🆕 ★

定稿：[2026-08-28-排程排产全链路自动化-定稿-v1.md](../docs/demo/02-specs/2026-08-28-排程排产全链路自动化-定稿-v1.md)

**订单状态机**：
```
待排队 ──persist 生成批次──▶ 已审核（锁定，防重复排）──批次上机──▶ 打印中 ──完成──▶ 完成
   ▲                              │
   └──版本驳回（回退）──────────┘
```

**五大缺口合并解决**：
- **A 前道任务生成**：solver.persist 同事务为每个批次生成前道任务（man_hours 含方案审核分摊），C9 硬约束前道完成 ≤ 打印开始
- **B 人员锁定释放**：前道任务落库防重复排，前道→待上机释放占用
- **C 订单状态贯穿**：persist 原子锁定待排队→已审核，驳回回退（带状态守卫），打印完成判定基于最新版本已通过批次
- **D 排产幂等**：事务开头条件 UPDATE 原子锁定 + 受影响行数不足 ROLLBACK，同一订单只被打印一次
- **E 审批门禁**：模拟器只推进 `approval_status='通过'` 的批次，驳回版本批次永不被推进

**读路径聚合**：多活动版本并存时聚合所有含未完成批次且版本状态非「已驳回」的版本，防插单后旧版本在途订单漏报。

## 8. API 端点一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查（provider/工具/缓存/checkpointer/sim 配置） |
| POST | `/ask` | 单次/多轮提问（{query, thread_id?}） |
| GET | `/threads/{id}/history` | 多轮会话历史 |
| POST | `/sim/start` | 启动模拟器心跳 |
| POST | `/sim/stop` | 停止模拟器心跳 |
| GET | `/sim/status` | 模拟器状态（运行中/停止/模拟时间） |
| GET | `/schedule/latest` | 最新排产版本 + 批次表 |
| GET | `/schedule/versions` | 排产版本列表（id/时间/触发/状态/批次数） |
| POST | `/schedule/load` | 触发求解 + 落库（需 admin token） |
| POST | `/schedule/approve` | 审批排产版本：通过/驳回（需 admin token） |
| GET | `/scheduler/status` | 自动排产调度器运行态 |
| GET | `/order/{id}/tracking` | 订单跟踪详情 |
| GET | `/kpi` | 当前 KPI 指标 |
| GET | `/resources/{category}` | 资源列表（machines/customers/orders/inventory/batches/preprocess/personnel） |
| PUT | `/resources/personnel/{id}/status` | 人员状态切换：上班/请假（需 admin token） |
| GET | `/dashboard/kpi-history` | KPI 历史快照 |
| GET | `/dashboard/costs` | 成本统计 |
| GET | `/dashboard/traces` | Trace 列表 |
| GET | `/debug/cases` | 收集的 case（type/good 过滤） |
| GET | `/debug/trace/{id}` | 按 trace_id 回放（trace + case 合并） |
| POST | `/debug/rerun/{id}` | 重跑 case（需 admin token，真实 LLM） |
| POST | `/debug/judge/{id}` | 手动打分（需 admin token，真实 LLM） |
| GET | `/debug/stats` | case 统计 + bad→good 转化率 |
| PUT | `/debug/cases/{id}/label` | 人工标注 good/bad（需 admin token） |
| GET | `/debug/admin-token` | 签发 admin token（本地演示便利） |
| GET | `/config` | 读关键配置 |
| PUT | `/config` | 写 system_config（需 admin token，白名单键） |
| GET | `/{full_path:path}` | SPA 静态托管（web/dist） |

## 9. 环境变量全表

### LLM / Provider

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DEEPSEEK_API_KEY` | - | DeepSeek API Key（主用） |
| `VOLC_API_KEY` | - | 火山豆包 API Key（备用1） |
| `KIMI_API_KEY` + `KIMI_ENABLED` | `false` | Kimi 编程套餐（备用2，默认禁用） |
| `PRIMARY_PROVIDER` | - | 可选：提权重排主备顺序（如 `火山豆包(coding)`） |
| `CHECKPOINTER` | `sqlite` | 状态持久化：sqlite/memory/none |
| `LLM_BUDGET_LIMIT` | `5.0` | LLM 预算上限（元） |
| `LLM_BUDGET_WARN` | `0.8` | 预算告警比例 |

### 缓存

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_CACHE` | `on` | L1 精确缓存开关 |
| `LLM_CACHE_TTL` | `3600` | L1 缓存 TTL（秒） |
| `SEMANTIC_CACHE` | `on` | L2 语义缓存开关 |
| `CACHE_THRESHOLD` | `0.10` | 语义缓存阈值（cosine distance 上限，v3 从 0.25 收紧） |
| `SEMANTIC_CACHE_STATE_TTL` | `60` | 状态类语义缓存 TTL（秒，对齐模拟器 tick） |

### 数据源（v2）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DEMO_DATA_SOURCE` | `csv` | 数据源：csv / mysql |
| `MYSQL_HOST` | `127.0.0.1` | MySQL 主机 |
| `MYSQL_PORT` | `3306` | MySQL 端口 |
| `MYSQL_USER` | `demo_sched` | MySQL 用户 |
| `MYSQL_PASSWORD` | - | MySQL 密码（env 或 credentials.local.md） |
| `MYSQL_DB` | `demo_scheduling` | MySQL 库名 |
| `FORCE_TENANT` | `false` | 强制租户隔离 |

### 模拟器 + 求解器

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SIM_TICK_SECONDS` | `60` | 模拟器心跳间隔（秒），默认 60s = 1 sim 小时 |
| `solver_max_time_seconds` | `20` | CP-SAT 求解时间预算（秒，snapshot 参数；性能优化 60→20，model 层回落 60） |

### 自动排产调度器（v3）🆕

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AUTO_SCHEDULE_ENABLED` | `on` | 自动排产开关（off 关闭） |
| `AUTO_SCHEDULE_TICK_INTERVAL` | `3` | 每 N 个模拟 tick 排一轮 |
| `AUTO_APPROVE_TOP_N` | `5` | 保留最近 N 个待审核版本，更早自动通过 |
| `FIFO_AGE_TIMEOUT` | `24` | 最早待审版本超龄兜底（模拟小时） |
| `STATUS_RESERVE_TOP_N` | `5` | 各订单状态保留最新 N 单不被推进 |

### 工具 / 安全 / 观测

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TOOL_TIMEOUT` | `10` | 单次工具调用超时秒数（R1） |
| `TOOL_MAX_RETRIES` | `3` | 最大重试次数（R1） |
| `WRITE_QUOTA_LIMIT` | `3` | 写工具配额：同角色 5min 内最多 N 次（R-D2） |
| `WRITE_QUOTA_WINDOW` | `300` | 配额滑窗（秒） |
| `GUARDRAILS_MODE` | `warn` | 护栏模式：block/warn/off |
| `MCP_MODE` | `local` | 工具调用模式：local/mcp |
| `OTEL_EXPORTER` | `console` | 观测导出：none/console/otel |
| `CONTEXT_MAX_CHARS` | `8000` | 触发上下文压缩的字符阈值（R4） |
| `CONTEXT_KEEP_RECENT` | `6` | 压缩后保留的最近消息数（R4） |

## 10. 运行评估与测试

```bash
# 全量单测 + 集成测试（mock LLM，零成本，必须全过）
python run_all_tests.py

# 全量单测 + 三层评估（真实 LLM）
python run_all_tests.py --eval

# 生成 HTML 报告
python run_all_tests.py --report

# 部署冒烟测试（S0-S10，S10 调真实 LLM 可跳过）
python demo/smoke_test.py --skip-llm

# 三层评估：工具 / 轨迹 / 语义（需真实 LLM）
python -m demo.eval.runner
python -m demo.eval.runner --case eval_001   # 单个 case
python -m demo.eval.runner --no-judge        # 跳过 LLM-as-Judge

# RAGAS 四指标回归（需真实 LLM，Q1-Q5）
python -m demo.eval.ragas_regression

# 回测：历史延期复盘
python -m demo.backtest.runner

# 排产求解器单测
python -m pytest demo/scheduler/test_solver.py -v

# 模拟器单测
python -m pytest demo/simulator/ -v
```

> 测试基线：v2 里程碑 449 passed 只增不减；v3 新增自动调度器/审批/资源/调试台/循环守卫回归测试。全量测试在 WSL 下运行。

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
- [x] R1 工具沙箱 / R2 输出护栏 / R3 步骤校验 / R4 上下文压缩
- [x] R5 MCP 隔离 / R6 三层评估 / R7 结构化筛选 / R8 多租户

### v2 制造业主线（M1-M5b）
- [x] **M1 数据层**：MySQL 双模式 + 连接池 + 事务 + 租户过滤
- [x] **M2 求解器**：CP-SAT 约束规划 + 装箱 + C1-C9 校验 + 落库
- [x] **M3 模拟器**：事件驱动引擎 + 心跳线程 + 连续失败熔断
- [x] **M4a 调度闭环**：18 个排产工具（求解/查排产/模拟事件/审批）
- [x] **M4b 产能评估**：负载/CTP/订单跟踪/前道/KPI
- [x] **M5a 统计预测**：指数平滑 + 移动平均，分材料日级预测
- [x] **M5b KPI 看板**：KPI 快照落库 + Dashboard 查询端点 + 静态 HTML
- [x] **Schema**：15 张表建表脚本 + 迁移工具 + 写方唯一标注
- [x] **API 扩展**：/sim/* + /schedule/* + /kpi + /dashboard/*

### v3 自动化 + 前端（2026-08-25 之后）🆕
- [x] **自动排产调度器**：tick 周期排产 + FIFO 自动审批 + 事件即时重排（`/scheduler/status`）
- [x] **全链路自动化**：订单状态机 + 排产幂等 + 审批门禁 + 前道任务生成
- [x] **前道任务生成**：solver 同事务生成 preprocess_tasks，C9 前道完成 ≤ 打印开始
- [x] **排产审批页面**：/schedule/versions + /schedule/approve（R-7 admin 鉴权）
- [x] **Web 控制台**：6-tab 单页聚合（看板/调试/审批/案例/资源/配置）
- [x] **资源聚合页 + 人员模块**：7 类资源 + personnel 状态切换 + 模拟器 leave 联动
- [x] **调试台**：case 落盘/标注/回放/重跑/judge/bad→good 转化率
- [x] **循环守卫 + 缓存门禁**：同参循环判定 + 兜底不投缓存 + 语义缓存阈值 0.10
- [x] **审核意图识别**：查询动词排除审批判断，查询已审核数据不误判写操作
- [x] **写配额（R-D2）**：写工具 5min 滑窗配额 + 审计 quota_exceeded
- [x] **RAGAS 回归**：四指标不劣化基线（0.82 / 1.00 / 0.90 / 1.00 实测）

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
| **v2.0** | 2026-08-25 | 完整排产智能体闭环（M1-M5b） |
| **审批页 + 控制台** | 2026-08-26 | /schedule/versions + approve + Web 6-tab 聚合 + 资源聚合页 |
| **自动排产调度器** | 2026-08-27 | AutoScheduler：tick 周期排产 + FIFO 审批 + 事件重排 + 循环守卫 |
| **全链路自动化** | 2026-08-28 | 订单状态机 + 幂等 + 审批门禁 + 前道任务生成（A-E 五缺口） |
| **状态留底** | 2026-08-29 | 各状态保留 topN 样本防演示清空 + 自动推进器留底 |
| **v3.0** | 2026-08-30 | 自动化闭环 + Web 控制台 + 调试台 + 意图识别加固 |

## 13. 相关文档

### 需求 / 规格

| 文档 | 说明 |
|------|------|
| [需求规格 v1](../docs/demo/02-specs/需求规格-v1-2026-08-21.md) | 范围/功能/非功能/验收标准 |
| [排程排产需求规格 v1](../docs/demo/02-specs/排程排产需求规格-v1-2026-08-21.md) | 排产业务需求 + C1-C9 约束 |
| [排程排产全链路自动化 定稿 v1](../docs/demo/02-specs/2026-08-28-排程排产全链路自动化-定稿-v1.md) | A-E 五缺口 + 订单状态机 + 幂等 + FIFO |
| [自动推进器状态留底 design](../docs/demo/02-specs/2026-08-29-自动推进器状态留底-design.md) | 各状态 topN 保底 |
| [资源聚合页 design](../docs/demo/02-specs/2026-08-26-资源聚合页-design.md) | 7 类资源 + 人员模块 |
| [部署指南 v2](../docs/demo/10-deployment/部署指南-v2-2026-08-30.md) | 生产部署完整指南（最新） |
| [部署指南 v1](../docs/demo/10-deployment/部署指南-v1-2026-08-25.md) | 生产部署指南 v1 |
| [生产化蓝图](../docs/demo/10-deployment/生产化差距与部署蓝图-v1-2026-08-22.md) | 差距分析 + 部署方案 |

### 功能介绍 / 代码阅读

| 文档 | 说明 |
|------|------|
| [功能介绍 v1](../docs/demo/11-manuals/功能介绍-v1-2026-08-30.md) | 可用功能 / 工具集合 / 技术架构 / 测试用例 / 可用例子 |
| [代码阅读指南 v3.0](../docs/demo/11-manuals/代码阅读指南-v3.0-2026-08-30.md) | 从底层到上层 28+ 层详细阅读路线（v3 全面升级） |
| [代码阅读指南 v2.0](../docs/demo/11-manuals/代码阅读指南-v2.0-2026-08-25.md) | 22 层阅读路线 + 评估体系深度解析 |
| [调试台测试用例提示词 v1](../docs/demo/08-test/调试台测试用例提示词-v1-2026-08-29.md) | A-L 12 组自然语言测试用例 + 正式执行清单 |
| [验收清单](../docs/demo/08-test/验收清单.md) | 门禁2 验收核对源头 |

### 评估报告

| 文档 | 说明 |
|------|------|
| [制造业智能体缺失评估报告](../docs/week6/demo-制造业智能体缺失评估报告-2026-08-09.md) | 行业基线 + 11 位评审团 + M1-M13 差距 |
| [三层评估体系实现](../docs/superpowers/plans/2026-08-08-ragas升级-三层评估体系.md) | 评估改造前的完整实现计划 |
