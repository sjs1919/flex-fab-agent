# demo -- 多 Agent 排产助手（week1-4 工程化整合版）

> [AI:Claude] 架构设计 + 实现。本 demo 把 week1-week4 的单文件脚本整合为一个按 Agent 行业推荐工程化思维组织的分层项目，对应 Harness（编排-权限-观测）三层架构。

## 1. 这个 demo 能做什么

一个面向**制造业排程排产**的对话式助手，用自然语言问生产相关问题，Agent 自动调用工具查数据、检索合同、综合分析后回答。支持两种运行模式：

- **单 Agent 模式**：一个 Agent 配合工具注册表，自主决定调用哪些工具、循环调用直到拿到足够信息再回答（LangGraph 编排）。
- **多 Agent 模式（Supervisor）**：一个主管 Agent 路由问题到专业子 Agent（订单评审 / 生产评估），子 Agent 各自持有限权限令牌调用工具，主管汇总。带 RBAC 鉴权 + 审计日志。

能回答的问题类型：
- 订单排期："今天先做哪些订单？"（综合交期、客户等级、库存、设备负载排序）
- 订单详情："ORD001 能按时交付吗？"（查状态、材料、设备）
- 紧急情况："有哪些紧急订单？哪些设备和材料是瓶颈？"
- 客户评估："东莞模具厂订单总体情况？信用如何？"
- 库存影响："PEEK 材料库存够吗？不够会影响哪些订单？"
- **合同知识库（RAG）**："广州航天合同有什么特殊条款？"（混合检索 + 重排命中合同原文）

## 2. 前置条件

```bash
# Python 3.11+，依赖（项目根目录已装则跳过）
pip install openai httpx chromadb sentence-transformers rank-bm25 jieba langgraph
# MCP 架构展示用（非运行必需）
pip install mcp
```

**环境变量**（项目根目录 `.env`，含 API Key 不提交 Git）：
```ini
VOLC_API_KEY=...        # 火山豆包（主 provider）
VOLC_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
DEEPSEEK_API_KEY=...    # DeepSeek（备 provider，主挂了自动降级）
DEEPSEEK_BASE_URL=https://api.deepseek.com
# KIMI_API_KEY=...      # Kimi（默认禁用，会员过期）
```

**本地模型缓存**（RAG 真连必需，已下载到本机）：
- 向量嵌入：Chroma 默认 ONNX MiniLM（`~/.cache/chroma/onnx_models/`）
- 重排器：`BAAI/bge-reranker-base`（`~/.cache/huggingface/hub/`）
- 首次调 RAG 工具会加载重排器（~1.1GB），约 20-30 秒；之后常驻秒级响应。

## 3. 快速开始

```bash
cd projects/agent-training

# 地基自检：验证 config / LLM / 工具 三层连通
python -m demo.main --check

# 单 Agent 模式问一个问题
python -m demo.main "今天先做哪些订单？"

# 多轮对话（状态持久化，重启可恢复）
python -m demo.main --chat

# 多 Agent 模式（带鉴权 + 审计）
python -m demo.main "广州航天合同有什么特殊条款？" --mode multi

# 跑预设场景（交互式选编号，回车=全部）
python -m demo.main --demo
```

> Windows 用户无需手动设 `PYTHONIOENCODING`：`demo/__init__.py` 已把标准输出重配为 UTF-8（控制台 GBK 无法显示状态 emoji）。

## 4. 调用建议

| 场景 | 推荐命令 | 为什么 |
|------|---------|--------|
| 验证环境是否配好 | `--check` | 不调 LLM 也能确认工具/数据层 OK，最快排障 |
| 单一问题快速回答 | `python -m demo.main "问题"` | 单 Agent 足够，链路短、token 省 |
| 涉及多角色协同（评审+生产） | `--mode multi "..."` | Supervisor 分派子 Agent，各持权限令牌，演示 RBAC |
| 合同/条款类问题 | 任意模式问"合同""条款""延期记录" | 自动触发 `search_knowledge_base`（RAG 工具） |
| 看完整效果 | `--demo` | 5 个预设场景覆盖订单/资源/客户/RAG 各类工具 |
| 第一次跑 RAG | 预期 20-30s 延迟 | 重排器首次加载，后续秒级，非故障 |

**调用顺序建议**：先 `--check` 确认地基 → 单 Agent 跑一个订单问题 → 单 Agent 跑一个 RAG 问题 → `--mode multi` 看鉴权审计 → `--demo` 看全貌。

## 5. 目录说明

```
demo/
├── __init__.py            # 包入口；UTF-8 输出修复（Windows GBK 兼容）
├── main.py                # 统一入口：--check/--demo/--mode single|multi
├── config.py              # 统一 .env 加载 + 单一 PROVIDERS 列表（主备 fallback）
│
├── core/                  # 基座层
│   └── llm_client.py      #   call_llm(messages, tools) + 主备降级 + trust_env=False 绕死代理
│
├── cache/                 # 语义缓存层（#6）
│   └── semantic_cache.py  #   Chroma cosine collection，相似问题命中跳过 LLM，仅无上下文时启用
│
├── tools/                 # 工具层（MCP 架构）
│   ├── data.py            #   CSV 数据加载（orders/inventory/machines/customers）
│   ├── order_tools.py     #   订单工具：query_orders/get_order_detail/get_production_status
│   ├── resource_tools.py  #   资源工具：query_inventory/query_machine_load/query_customer
│   ├── registry.py        #   ToolRegistry：O(1) 查找 + 参数白名单 + RBAC 强制 + tracer 接入
│   └── mcp_servers.py     #   FastMCP server 构建（展示 MCP 协议，非运行必需）
│
├── rag/                   # 合同知识库混合检索
│   ├── knowledge_base.py  #   文档加载/分块/Chroma 向量库（复用持久化）
│   └── retriever.py       #   BM25 + 向量 + RRF 融合 + Cross-Encoder 重排 + 离线防坑
│
├── prompts/
│   └── system_prompts.py  # 各 Agent 系统提示词（单 Agent / 评审 / 生产 / 主管）
│
├── graph/                 # LangGraph 编排层
│   ├── state.py           #   AgentState（TypedDict：messages/tool_results/iteration/final_answer）
│   └── single_agent_graph.py  # 单 Agent 状态图：分析→选工具执行→评估→生成答案（5 轮安全阀）
│   └── checkpointer.py    #   状态持久化：sqlite/memory/none，多轮对话 + 重启恢复（#1/#7）
│
├── agents/                # Agent 层
│   ├── single_agent.py    #   run_single_agent()：构建图 + 调用
│   ├── router.py          #   AgentRouter：关键词路由（review/production/full/query）
│   ├── review_agent.py    #   订单评审子 Agent（持 reviewer 令牌）
│   ├── production_agent.py#   生产评估子 Agent（持 scheduler 令牌）
│   └── supervisor.py      #   SupervisorAgent：STS 签发+交换令牌→分派→LLM 汇总→审计报告
│
├── auth/                  # 鉴权层（Harness 权限层）
│   ├── token_exchange.py  #   STS：签发用户令牌→交换受限子令牌（RFC 8693，5min TTL）
│   ├── guard.py           #   RBAC 守卫：工具层权限校验（洋葱第 3 层）
│   └── audit_logger.py    #   审计日志：trace_id 贯穿，记录每次鉴权决策
│
├── observability/         # 观测层（Harness 观测层）
│   ├── tracer.py          #   Span/Tracer：LLM+工具调用全链路计时与 token 用量（OTel 同构）
│   └── exporter.py        #   导出 backend：none/console/otel(OTLP)，延迟批量导出（#3）
│
└── data/                  # 运行数据（已随 demo 打包）
    ├── *.csv              #   订单/库存/设备/客户数据
    ├── contracts/*.txt    #   3 份合同特殊条款
    ├── 历史延期记录.txt    #   延期复盘
    └── chroma_db/         #   Chroma 向量库（首次自动重建）
```

## 6. 如何阅读这个 demo 的代码

> 第一次读这个 demo，建议按下面顺序从入口一步步深入。每一层只在前一层基础上多加一个概念，不会一次吞下全部。每步标了「读哪个文件 → 关注什么」。

**第一层 · 入口和配置（先跑通，再看怎么连）**
1. `main.py` — 三种模式（`--check`/`--demo`/`--mode single|multi`）怎么分发，`_run_with_trace` 怎么在每轮查询前后重置和打印 trace。关注：入口尽量薄，只做参数解析和分发。
2. `config.py` — `PROVIDERS` 列表怎么从 `.env` 读出。关注：一份列表同时是「主备顺序」，第一个成功就返回，失败自动降级。

**第二层 · LLM 基座（Agent 怎么「说话」）**
3. `core/llm_client.py` — `call_llm(messages, tools)` 怎么遍历 PROVIDERS、`trust_env=False` 为什么必要（绕过 Windows 死代理）。关注：统一一份签名，调用方不用关心切 provider。

**第三层 · 工具层（Agent 怎么「动手」查数据）**
4. `tools/data.py` — CSV 怎么加载成内存数据，最底层数据先认脸。
5. `tools/order_tools.py` + `tools/resource_tools.py` — 纯函数，输入参数返回字符串，没有 Agent 逻辑。关注：工具 =「函数 + 一段描述」，描述决定 LLM 何时调它。
6. `tools/registry.py` — **重点**。看 `ToolRegistry` 怎么用字典 O(1) 查找、`execute` 怎么做参数白名单过滤和 RBAC 校验。对比 week1 的 if/elif 链，理解为什么用注册中心。
7. `tools/mcp_servers.py` — 可选。看 FastMCP 怎么把工具包成 MCP server，理解「工具协议化」形态（本 demo 只展示，运行时不强制走 MCP）。

**第四层 · 单 Agent（Agent 怎么自己决定调哪个工具）**
8. `graph/state.py` — `AgentState` 这个 TypedDict 有哪些字段（messages/tool_results/iteration/final_answer）。关注：状态在节点间传递，显式类型比字典安全。
9. `graph/single_agent_graph.py` — **重点**。4 个节点（分析意图→选工具执行→评估结果→生成答案）和 `should_continue` 条件边怎么连成循环，以及 5 轮安全阀防死循环。
10. `agents/single_agent.py` — 怎么把图构建出来并调用，就几行。

**第五层 · RAG（Agent 怎么查合同知识库）**
11. `rag/knowledge_base.py` — 文档加载、分块、Chroma 向量库怎么复用持久化。
12. `rag/retriever.py` — **重点**。四步混合检索（向量召回→BM25 召回→RRF 融合→Cross-Encoder 重排），以及 `load_reranker` 里 patch HF constants 的离线防坑。关注：为什么纯向量不够（中文关键词召回弱），要 BM25 + 重排补。

**第六层 · 多 Agent + 鉴权（多个 Agent 怎么分工、怎么限权）**
13. `auth/token_exchange.py` — STS 怎么签发用户令牌、交换成受限子令牌（5min TTL）。关注：子令牌权限 ≤ 父令牌，防权限升级。
14. `auth/guard.py` — `check_tool_permission` 怎么在工具执行入口做 RBAC。关注：这是「洋葱第 3 层」，前两层是网关和运行时。
15. `agents/router.py` — 关键词怎么路由到不同子 Agent。
16. `agents/review_agent.py` + `agents/production_agent.py` — 子 Agent 怎么持各自令牌、通过 registry 调工具。
17. `agents/supervisor.py` — **重点**。主管怎么签发+交换令牌、分派子 Agent、LLM 汇总、出审计报告。

**第七层 · 观测（怎么知道 Agent 干了什么）**
18. `observability/tracer.py` — `Span` 和 `Tracer` 怎么用 contextmanager 记录每个 LLM/工具调用的耗时和 token。关注：OTel 的同构最小实现，week5 换 backend 不动业务代码。

**读代码时带这三个问题：**
- 这一层解决什么问题？（避免「为设计而设计」）
- 它和上一层什么关系？（理解数据怎么流）
- 注释里的「为什么」比「是什么」重要。（中文注释标了设计意图）

## 7. 架构图

```
                        用户提问
                           │
                ┌──────────▼──────────┐
                │       main.py        │  入口 + tracer.reset
                └──────────┬──────────┘
                           │
            ┌──────────────┴──────────────┐
            ▼ single 模式                  ▼ multi 模式
   ┌─────────────────┐          ┌─────────────────────┐
   │  single_agent   │          │    Supervisor       │
   │  (LangGraph)    │          │  ┌────路由────┐     │
   │  分析→执行→评估  │          │  ▼           ▼     │
   └────────┬────────┘          │ 评审Agent  生产Agent │
            │                   │ (reviewer (scheduler│
            │ 共用                │  令牌)     令牌)   │
            ▼                   └─────┬───────┬──────┘
   ┌──────────────────────────────────┼───────┼──────┐
   │           ToolRegistry (O(1) 查找 + 参数白名单)    │
   │   order_tools   resource_tools   search_knowledge │
   │        │             │              │            │
   │        ▼             ▼              ▼            │
   │     CSV数据       CSV数据        RAG混合检索      │
   │                                  向量+BM25+RRF   │
   │                                  +CrossEncoder   │
   └──────────┬───────────────────────────────────────┘
              │ 每次工具调用经 guard.py RBAC 校验
              ▼
   ┌────────────────────┐    ┌────────────────────┐
   │   auth/STS+RBAC    │    │  observability/     │
   │  令牌签发→交换→守卫  │    │  tracer 全链路 span │
   │  + audit_logger     │    │  (LLM计时/token用量) │
   └────────────────────┘    └────────────────────┘
              │                        │
              ▼                        ▼
   ════════════════════ Harness 三层 ════════════════════
        权限层              编排层            观测层
```

**三层对应关系**：
- **编排层**：`graph/` + `agents/`（LangGraph 状态机驱动 Agent 循环）
- **权限层**：`auth/`（STS 令牌交换 + RBAC 守卫 + 审计，洋葱型三道防线）
- **观测层**：`observability/`（Span 全链路追踪，OTel 同构接口）

## 8. 与原 week1-4 脚本的关系

| 原 week 脚本 | 整合到 | 工程化改进 |
|-------------|--------|-----------|
| week1 `call_llm(system,user)` | `core/llm_client.py` | 两份签名合一为 `call_llm(messages,tools)` + 主备 fallback 内置 |
| week1 硬编码 TOOLS + if/elif 执行 | `tools/registry.py` | O(1) 字典查找 + 参数白名单 + RBAC 强制 + tracer 接入 |
| week2 `day1_rag_basics.py` | `rag/knowledge_base.py` | 复用持久化向量库，路径用 config 统一管理 |
| week2 `day2_hybrid_rerank.py` | `rag/retriever.py` | 离线防坑（patch HF constants）+ 懒加载单例 + 工具函数化 |
| week3 `single_agent` 内联图 | `graph/` + `agents/single_agent.py` | 图定义与调用分离，state 用 TypedDict 显式类型 |
| week3 多 Agent 串行调用 | `agents/supervisor.py` + 子 Agent | 子 Agent 持独立令牌，经 registry 走 RBAC（原版无鉴权） |
| 各处散落 print | `observability/tracer.py` | 统一 Span 追踪，生产可换 OTel backend |
| 无鉴权 | `auth/` 三件套 | 补齐 STS 令牌交换 + RBAC + 审计（缺口 #7 修复） |

原脚本保留在 `scripts/week1-4/`，可对照查看演进。

## 9. 与行业推荐方案的差距 + 优化策略

> 以下是当前 demo（教学版）与生产级 Agent 系统的差距。每项给出现状、行业推荐、优化策略，作为 week5+ 的演进路线。

| # | 维度 | 现状（demo） | 行业推荐 | 差距 | 优化策略 |
|---|------|------------|---------|------|---------|
| 1 | **编排层** | LangGraph 状态图 + SqliteSaver 检查点，5 轮安全阀，多轮/重启可恢复 | 状态持久化（checkpoint）+ 中断恢复 + 人机协同（human-in-the-loop） | 已支持多轮与重启恢复；缺中断恢复演示、human-in-the-loop | 长任务加 `interrupt_before` 等人工确认；演示崩溃续跑 |
| 2 | **权限层** | STS 内存签发，RBAC 5 角色，令牌 5min TTL | OAuth2/OIDC + JWT + DB 存储 + 刷新令牌 + 权限细粒度（ABAC） | 内存令牌重启即失；角色权限粗粒度；无刷新机制 | 令牌落 Redis（TTL 自动过期）；JWT 签名 + refresh token；RBAC→ABAC（按资源属性判权限） |
| 3 | **观测层** | Tracer + 可插拔导出（console/otel/OTLP），延迟批量导出，OTel 同构 | OpenTelemetry / Langfuse，异步导出 + 采样 + 分布式 trace | 已支持导出与 OTel trace；缺采样、异步导出、成本看板 | LangGraph `config.callbacks` 自动埋点；加采样 + token 成本聚合；OTLP 接常驻 collector |
| 4 | **工具层** | 同进程函数 + MCP server 展示（非真隔离） | MCP 工具独立进程/容器运行 + 动态发现 + 沙箱 | 工具与 Agent 同进程，故障耦合；MCP 仅展示未真用 | 工具拆 MCP 子进程（stdio/SSE），Agent 通过协议调用；加工具执行超时与资源限制 |
| 5 | **RAG** | 本地 Chroma + 离线 reranker，4 文档 10 chunk | 向量库服务（Milvus/Pinecone）+ 增量索引 + 多租户 + 混合检索调参 | 数据量小、无增量更新、单租户；reranker 首载慢 | 换独立向量库服务；加文档增量入库 pipeline；reranker 常驻服务化；检索参数（top_k/RRF k）可调 |
| 6 | **LLM 调用** | 主备 fallback + 语义缓存（Chroma cosine，相似问题跳过 LLM） | 智能路由（按任务选模型）+ 成本控制 + 语义缓存 | 无路由策略；缺智能路由、成本上限、强中文 embedding | 缓存换 bge-large-zh + Redis；按任务复杂度路由（简单→小模型，复杂→大模型）；设日 token 预算 |
| 7 | **状态管理** | SqliteSaver 持久化会话 + 多轮上下文（thread_id 续接） | 持久化会话 + 断点续跑 + 多轮上下文压缩 | 已支持多轮与重启恢复；缺长上下文摘要压缩 | 超长上下文用摘要压缩（summarization buffer）；会话过期清理 |
| 8 | **数据层** | 本地 CSV 只读 | 数据库/API + 实时同步 + 读写分离 | 数据静态、无写入；无并发控制 | 工具改查真实业务库（MySQL/API）；加连接池；写操作加乐观锁 |
| 9 | **审计** | 文件 audit_logger，trace_id 贯穿 | 结构化日志（JSON）+ SIEM 接入 + 不可篡改 | 文本日志、无防篡改、无集中查询 | 改 JSON 结构化日志；接 ELK/Loki；关键审计写 WORM 存储（只追加） |
| 10 | **部署** | 本地 `python -m` | 容器化 + API 网关 + 水平扩展 + 健康检查 | 单机脚本、无网关、无扩缩容 | Dockerfile + FastAPI 网关；K8s 部署 + HPA；加 `/health` + `/metrics` |

**优先级建议**（按性价比）：
1. ~~**先补观测层导出**（#3）~~ ✅ 已完成（2026-08-04）：Tracer 接可插拔导出 backend（console/otel/otlp），见 §10
2. ~~**再补状态持久化**（#1/#7）~~ ✅ 已完成（2026-08-04）：SqliteSaver 检查点 + `--chat` 多轮 + 跨进程恢复，见 §11
3. ~~**然后语义缓存**（#6）~~ ✅ 已完成（2026-08-04）：Chroma cosine 语义缓存，相似问题跳过 LLM，见 §12
4. **最后容器化**（#10）：演示对外可用，但需配合前几项才有意义

## 10. 查看 trace（观测层导出）

观测层支持把每轮 query 的完整 trace 导出到外部 sink，由 `OTEL_EXPORTER` 环境变量选择 backend：

| `OTEL_EXPORTER` | 输出 | 基建 | 用途 |
|---|---|---|---|
| `console`（默认） | 控制台结构化 JSON 行（每 span 一行，含 token 用量） | 无 | 开箱演示「导出」概念 |
| `otel` | 真 OpenTelemetry span（JSON，含 trace_id/span_id/resource） | 无（ConsoleSpanExporter） | 看真 OTel 格式 |
| `otel` + `OTEL_EXPORTER_OTLP_ENDPOINT` | 发 OTLP gRPC 到 collector | 本地 Jaeger（4317） | Jaeger UI 看分布式 trace |
| `none` | 无导出，仅友好摘要 | 无 | 等价 week4 行为 |

```bash
# 默认：控制台结构化导出
python -m demo.main "ORD001 能按时交付吗？"

# 真 OTel JSON（ConsoleSpanExporter）
OTEL_EXPORTER=otel python -m demo.main "ORD001 能按时交付吗？"

# 发到本地 Jaeger（先起 Jaeger，见下方说明）
OTEL_EXPORTER=otel OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 \
  python -m demo.main "ORD001 能按时交付吗？"
```

**本地起 Jaeger**（可选，看 OTLP 导出效果）：
```bash
docker run -d --name jaeger -p 4317:4317 -p 16686:16686 jaegertracing/all-in-one:1.62
# 跑完后访问 http://localhost:16686，service 选 demo-scheduling-agent
```

> 导出是「延迟批量」：整轮 query 结束才 flush，保证业务代码在 span 结束后写入的 token 用量不丢。一轮 query 的所有 span 共享同一 trace_id，OTel 档下挂到同一个 OTel trace。

## 11. 多轮对话与状态持久化（编排层 #1/#7）

单 Agent 图编译时接入 LangGraph checkpointer，运行状态（messages/工具结果/迭代次数）落盘，支持多轮对话与重启恢复。backend 由 `CHECKPOINTER` 环境变量选：

| `CHECKPOINTER` | 行为 | 用途 |
|---|---|---|
| `sqlite`（默认） | 落盘 `demo/data/checkpoints.db`，重启可恢复 | 默认，演示真持久化 |
| `memory` | 进程内存，重启即失 | 仅演示 checkpoint 概念 |
| `none` | 不持久化 | 等价 week4 无 checkpointer |

```bash
# 多轮对话（同一会话跨轮共享上下文）
python -m demo.main --chat
# 会话 id 会打印；/exit 退出 · /new 新会话 · /switch <id> 切换

# 续接指定会话（含跨进程重启恢复）
python -m demo.main --chat --thread <会话id>

# 单次提问但恢复某会话上下文
python -m demo.main "接着上面说" --thread <会话id>
```

**多轮原理**：每轮 invoke 前，从 checkpoint 取历史 messages 追加新问题，并重置 `tool_results`/`iteration`/`final_answer`（每轮独立工具循环）。同一 `thread_id` 即同一会话；sqlite 落盘后新进程读同一 db + 同一 thread_id 即恢复上下文。

**为什么不用 `add_messages` reducer**：它会把消息转成 LangChain `HumanMessage`/`AIMessage` 对象，而本 demo 全链路按 dict 处理消息并直接喂 OpenAI SDK。改对象类型风险大、收益小，故保持 dict + 覆盖语义，多轮时显式从 checkpoint 取历史。

> `demo/data/checkpoints.db` 是运行时会话数据，已 gitignore，勿提交。

## 12. 语义缓存（LLM 调用层 #6）

相似问题直接返回缓存答案，跳过整图执行（省 LLM token、降延迟）。教学版用 Chroma 独立 collection（cosine 空间，复用其默认 ONNX MiniLM embedding），生产换 Redis + 更强中文 embedding。

```bash
# 默认开启。首次问 -> 未命中 -> 执行 -> 缓存；再问相似问题 -> 命中 -> 跳过 LLM
python -m demo.main "今天有哪些紧急订单？"
python -m demo.main "查一下今天的紧急订单"   # 近义改写，命中缓存

# 关闭语义缓存
SEMANTIC_CACHE=off python -m demo.main "今天有哪些紧急订单？"

# 调阈值（cosine distance 上限，越小越严，默认 0.20）
CACHE_THRESHOLD=0.10 python -m demo.main "今天有哪些紧急订单？"
```

**只对无多轮上下文的独立问题生效**：多轮对话（`--chat`/`--thread`）里同一句话的答案依赖前文，不能复用首轮缓存，故 `thread_id` 非空时跳过缓存。

**阈值校准**（MiniLM cosine distance）：完全相同 0.00 · 多标点 0.04 · 近义改写 0.17 · 较远改写 0.37 · 不相关 0.46+。默认 0.20 catches 同义/标点/近义改写，排除较远与不相关。

**局限**：MiniLM 中文判别力一般（RAG 那块也靠 BM25+reranker 补），生产建议换 `bge-large-zh` + Redis + 可选 reranker 校验。命中/未命中记为 `cache:lookup` span（result=hit/miss + distance），随观测层导出（见 §10）。

> `demo/data/cache_db/` 是运行时缓存向量库，已 gitignore，勿提交。

---

## 验收清单

- [x] `python -m demo.main --check` 地基自检通过
- [x] 单 Agent 模式：订单问题多工具调用 + 综合回答
- [x] 单 Agent 模式：RAG 问题命中合同（rerank 分 >0.9）
- [x] 多 Agent 模式：Supervisor 分派 + RBAC 拒绝越权 + 审计报告
- [x] 观测层：trace 摘要含 LLM token 用量与工具延迟
- [x] 观测层导出（#3）：`OTEL_EXPORTER=console` 跑一轮见结构化导出（含 token 用量）
- [x] OTel 档：`OTEL_EXPORTER=otel` 产出真 OTel span（共享 trace_id，可发 Jaeger）
- [x] 状态持久化（#1/#7）：`--chat` 多轮对话，第二轮记住第一轮上下文
- [x] 重启恢复：新进程 `--chat --thread <id>` 恢复原会话历史
- [x] 语义缓存（#6）：首次问未命中（执行并缓存），近义改写再问命中跳过 LLM
- [x] 语义缓存：无关问题不误命中（distance>阈值判 miss），trace 记 `cache:lookup(result=hit/miss + distance)`
- [x] Windows GBK 兼容：无需手动设编码环境变量
- [x] README 含功能/调用建议/目录/架构图/差距表
