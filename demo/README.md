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
│   └── tracer.py          #   Span/Tracer：LLM+工具调用全链路计时与 token 用量（OTel 同构）
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
| 1 | **编排层** | LangGraph 状态图，内存态，5 轮安全阀 | 状态持久化（checkpoint）+ 中断恢复 + 人机协同（human-in-the-loop） | 无持久化，重启丢状态；无中断后续跑 | 接 LangGraph `MemorySaver`/`SqliteSaver` 做检查点；长任务加 `interrupt_before` 等人工确认 |
| 2 | **权限层** | STS 内存签发，RBAC 5 角色，令牌 5min TTL | OAuth2/OIDC + JWT + DB 存储 + 刷新令牌 + 权限细粒度（ABAC） | 内存令牌重启即失；角色权限粗粒度；无刷新机制 | 令牌落 Redis（TTL 自动过期）；JWT 签名 + refresh token；RBAC→ABAC（按资源属性判权限） |
| 3 | **观测层** | 进程内 Tracer，控制台文本摘要 | OpenTelemetry / Langfuse，异步导出 + 采样 + 分布式 trace | 无导出、无采样、单进程；无成本看板 | Tracer backend 换 OTel exporter 或 Langfuse；LangGraph `config.callbacks` 自动埋点；加 token 成本聚合 |
| 4 | **工具层** | 同进程函数 + MCP server 展示（非真隔离） | MCP 工具独立进程/容器运行 + 动态发现 + 沙箱 | 工具与 Agent 同进程，故障耦合；MCP 仅展示未真用 | 工具拆 MCP 子进程（stdio/SSE），Agent 通过协议调用；加工具执行超时与资源限制 |
| 5 | **RAG** | 本地 Chroma + 离线 reranker，4 文档 10 chunk | 向量库服务（Milvus/Pinecone）+ 增量索引 + 多租户 + 混合检索调参 | 数据量小、无增量更新、单租户；reranker 首载慢 | 换独立向量库服务；加文档增量入库 pipeline；reranker 常驻服务化；检索参数（top_k/RRF k）可调 |
| 6 | **LLM 调用** | 主备 fallback，固定顺序 | 智能路由（按任务选模型）+ 成本控制 + 语义缓存 | 无路由策略；无缓存，重复问题重算；无成本上限 | 加语义缓存（Redis + embedding 相似度）；按任务复杂度路由（简单→小模型，复杂→大模型）；设日 token 预算 |
| 7 | **状态管理** | TypedDict 内存态 | 持久化会话 + 断点续跑 + 多轮上下文压缩 | 多轮对话重启即失；长上下文无压缩 | 会话存 DB；超长上下文用摘要压缩（summarization buffer）；接 LangGraph 持久化 |
| 8 | **数据层** | 本地 CSV 只读 | 数据库/API + 实时同步 + 读写分离 | 数据静态、无写入；无并发控制 | 工具改查真实业务库（MySQL/API）；加连接池；写操作加乐观锁 |
| 9 | **审计** | 文件 audit_logger，trace_id 贯穿 | 结构化日志（JSON）+ SIEM 接入 + 不可篡改 | 文本日志、无防篡改、无集中查询 | 改 JSON 结构化日志；接 ELK/Loki；关键审计写 WORM 存储（只追加） |
| 10 | **部署** | 本地 `python -m` | 容器化 + API 网关 + 水平扩展 + 健康检查 | 单机脚本、无网关、无扩缩容 | Dockerfile + FastAPI 网关；K8s 部署 + HPA；加 `/health` + `/metrics` |

**优先级建议**（按性价比）：
1. **先补观测层导出**（#3）：Tracer 已就绪，换 backend 即可，改动小、收益大（能看到全链路）
2. **再补状态持久化**（#1/#7）：LangGraph MemorySaver 几行代码，多轮对话立即可用
3. **然后语义缓存**（#6）：重复问题省 token，立竿见影降本
4. **最后容器化**（#10）：演示对外可用，但需配合前几项才有意义

---

## 验收清单

- [x] `python -m demo.main --check` 地基自检通过
- [x] 单 Agent 模式：订单问题多工具调用 + 综合回答
- [x] 单 Agent 模式：RAG 问题命中合同（rerank 分 >0.9）
- [x] 多 Agent 模式：Supervisor 分派 + RBAC 拒绝越权 + 审计报告
- [x] 观测层：trace 摘要含 LLM token 用量与工具延迟
- [x] Windows GBK 兼容：无需手动设编码环境变量
- [x] README 含功能/调用建议/目录/架构图/差距表
