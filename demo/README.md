# demo -- 多 Agent 排产助手（week1-5 工程化整合版）

> [AI:Claude] 架构设计 + 实现。本 demo 把 week1-week5 的单文件脚本整合为一个按 Agent 行业推荐工程化思维组织的分层项目，对应 Harness（编排-权限-观测）三层架构。
> R1-R8 缺陷修复已完成（2026-08-07），详见 `docs/week5/8大缺陷-可执行代码改造方案.md`。
> 正式需求规格 v1：[docs/demo/需求规格-v1-2026-08-21.md](../docs/demo/需求规格-v1-2026-08-21.md)（范围/功能/非功能/验收标准/演进候选）。

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
│   └── llm_client.py      #   call_llm(messages, tools) + 主备降级 + 连接池 + L1 精确缓存
│
├── cache/                 # 缓存层（两级缓存减少 LLM API 调用）
│   ├── llm_cache.py       #   L1 精确缓存（SQLite，相同 prompt 命中 <1ms，0 token）
│   └── semantic_cache.py  #   L2 语义缓存（Chroma cosine，近义改写命中 ~50ms）
│
├── tools/                 # 工具层（MCP 架构）
│   ├── data.py            #   CSV 数据加载 + R8 租户过滤
│   ├── order_tools.py     #   订单工具：query_orders（R7 多字段筛选/排序/limit）
│   ├── resource_tools.py  #   资源工具：query_inventory（R7 筛选/排序）+ query_customer（R7）
│   ├── registry.py        #   ToolRegistry：O(1) 查找 + 参数白名单 + RBAC 强制 + tracer 接入
│   │                      #     + R1 sandbox 集成 + R5 MCP 路由 + R8 tenant_id 自动注入
│   ├── sandbox.py         #   工具沙箱（R1：超时控制 + 指数退避重试）
│   ├── mcp_client.py      #   MCP Client（R5：stdio 子进程通信）
│   └── mcp_servers.py     #   FastMCP server 构建（展示 MCP 协议，非运行必需）
│
├── rag/                   # 合同知识库混合检索
│   ├── knowledge_base.py  #   文档加载/分块/Chroma 向量库（复用持久化）
│   └── retriever.py       #   BM25 + 向量 + RRF 融合 + Cross-Encoder 重排 + 离线防坑
│
├── prompts/
│   └── system_prompts.py  # 各 Agent 系统提示词（单 Agent / 评审 / 生产 / 主管）
│
├── guardrails/            # 输出护栏（R2 缺陷修复）
│   ├── __init__.py        #   run_guardrails() 统一入口
│   ├── rules.py           #   护栏规则定义（越权/敏感/缺失段落）
│   └── content_filter.py  #   内容过滤器（regex + 降级策略）
│
├── eval/                  # Agent 评估（R6 + 三层升级 2026-08-09）
│   ├── __init__.py
│   ├── ground_truth.json  #   10 组排产场景 ground truth Q&A
│   ├── metrics.py         #   工具层指标（工具F1/完整性/订单召回/min_tools_called）
│   ├── trajectory.py      #   轨迹层指标（路径效率/重试质量/循环检测）
│   ├── trajectory_capture.py # 从 tracer + tool_results 重建工具调用序列
│   ├── judge.py           #   语义层：自研 LLM-as-Judge（faithfulness/relevancy）
│   ├── judge_prompt.py    #   Judge 系统提示词（JSON 输出）
│   ├── report.py          #   单页 HTML 可视化报告
│   ├── runner.py          #   评估运行器（python -m demo.eval.runner）
│   └── test_*.py          #   各层单元测试
│
├── backtest/              # 回测模块（2026-08-09 新增）
│   ├── __init__.py
│   ├── scenarios.py       #   5 个历史延期复盘场景（bt_001~005）+ 覆盖度评分
│   ├── runner.py          #   回测运行器（Agent 复盘历史事件 vs 人工结论）
│   └── test_backtest.py   #   回测单元测试
│
├── graph/                 # LangGraph 编排层
│   ├── state.py           #   AgentState（TypedDict：messages/tool_results/iteration/final_answer
│   │                      #     + R3 新增 evaluation_notes/needs_retry/needs_more/ready_for_answer
│   │                      #     + R4 新增 compression_count/compressed_summary）
│   ├── single_agent_graph.py  # 单 Agent 状态图：分析→选工具执行→评估→生成答案（5 轮安全阀）
│   │                      #     + R2 集成 guardrails + R3 evaluate_results 不再 noop + R4 上下文压缩
│   └── context_compressor.py  # 上下文压缩器（R4 缺陷修复：summarization buffer）
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

**第八层 · 工具安全（工具挂了怎么兜底）** 🆕 R1
19. `tools/sandbox.py` — `run_with_retry` 怎么用 threading.Timer 做超时控制 + 指数退避重试。关注：返回三元组 (result, success, retries)，上层 registry 不感知重试细节。

**第九层 · 输出安全（LLM 输出了不该输出的内容怎么办）** 🆕 R2
20. `guardrails/` — `run_guardrails` 怎么在 `generate_answer` 前做输出校验。关注：三种 severity（block/warn/sanitize），护栏拦截后怎么让 LLM 修正重试。

**第十层 · 上下文压缩（长对话 token 成本怎么控制）** 🆕 R4
21. `graph/context_compressor.py` — `compress_messages` 怎么把早期消息转成摘要。关注：保留 system + 最近 N 条，中间用 LLM 摘要替代——summarization buffer 是 LangGraph 推荐模式。

**第十一层 · 评估（怎么量化 Agent 好不好）** 🆕 R6 + 三层升级
22. `eval/` — `ground_truth.json` 定义 10 组排产场景。**三层指标**：
    - **工具层**（`metrics.py`）：工具 F1 + 完整性 + 订单召回 + min_tools_called（该调几个工具没调够直接判 0）
    - **轨迹层**（`trajectory.py` + `trajectory_capture.py`）：路径效率（冗余调用扣分）+ 重试质量（重试/失败扣分）+ 循环检测
    - **语义层**（`judge.py` + `judge_prompt.py`）：自研 LLM-as-Judge 打分 faithfulness / answer_relevancy，不依赖 ragas（已停滞）
    - 聚合：`overall = 工具×0.5 + 轨迹×0.3 + 语义×0.2`，case ≥0.6 算 pass，回归基线 ≥7/10
    - `report.py` 单页 HTML 可视化三层指标 + 循环标记
    - 回测（`backtest/`）：让 Agent 复盘 5 个历史延期案例，按人工复盘结论覆盖度评分
    - 关注：三层聚合权重为什么这么定；judge 无上下文时如何降级。

**第十一层·续 · 一键自动化测试** 🆕 2026-08-09
23. `run_all_tests.py` + `test_demo.sh` — pytest 全量（mock LLM 零成本）→ 可选 `--eval` 三层评估（真实 LLM）→ 可选 `--report` HTML 报告。关注：测试脚本作为 CI 入口的基础。

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
| 1 | **编排层** | LangGraph 状态图 + SqliteSaver 检查点，5 轮安全阀，多轮/重启可恢复 + evaluate_results 步骤校验 + summarization buffer 上下文压缩 ✅R3,R4 | 状态持久化（checkpoint）+ 中断恢复 + 人机协同（human-in-the-loop） | 已支持多轮与重启恢复 + 步骤校验 + 上下文压缩；缺中断恢复演示、human-in-the-loop | 长任务加 `interrupt_before` 等人工确认；演示崩溃续跑 |
| 2 | **权限层** | STS + RBAC 5 角色 + Token SQLite 持久化 + tenant_id 多租户 + FORCE_TENANT 强制模式 ✅R8 | OAuth2/OIDC + JWT + DB 存储 + 刷新令牌 + 权限细粒度（ABAC） | 有租户隔离基础；缺 JWT 签名、refresh token、ABAC | 令牌落 Redis（TTL 自动过期）；JWT 签名 + refresh token；RBAC→ABAC |
| 3 | **观测层** | Tracer + 可插拔导出 + OTel 同构 + CostTracker 预算熔断 | OpenTelemetry / Langfuse，异步导出 + 采样 + 分布式 trace | 已支持导出与 OTel trace + 成本；缺采样、异步导出、成本看板 | LangGraph `config.callbacks` 自动埋点；加采样 + OTLP 接常驻 collector |
| 4 | **工具层** | 同进程函数 + sandbox 超时/重试 ✅R1 + MCP client 子进程通信能力 ✅R5 | MCP 工具独立进程/容器运行 + 动态发现 + 沙箱 | 有沙箱（超时+重试）+ MCP client；默认仍走 local fast path | 默认切 MCP_MODE=mcp；加工具执行资源限制（cgroup） |
| 5 | **RAG** | 本地 Chroma + 离线 reranker + query_orders 多字段 AND 筛选/排序/limit ✅R7 | 向量库服务 + 增量索引 + 多租户 + NL2SQL | 有结构化筛选；缺增量索引、多租户 RAG | 独立向量库服务；文档增量入库；reranker 常驻服务化 |
| 6 | **LLM 调用** | 主备 fallback + 两级缓存（L1 SQLite + L2 Chroma cosine）+ 成本熔断 | 智能路由（按任务选模型）+ 成本控制 + 语义缓存 | 有完整缓存+成本；缺智能路由、强中文 embedding | 缓存换 bge-large-zh + Redis；按任务复杂度路由 |
| 7 | **状态管理** | SqliteSaver 持久化 + 多轮 + 重启恢复 + 上下文压缩 ✅R4 | 持久化会话 + 断点续跑 + 多轮上下文压缩 | 已支持全链路；缺长上下文自动压缩的触发日志 | 会话过期清理；压缩次数统计面板 |
| 8 | **数据层** | 本地 CSV 只读 + tenant_id 租户过滤 ✅R8 | 数据库/API + 实时同步 + 读写分离 | 有租户过滤基础；数据静态、无写入 | 工具改查真实业务库（MySQL/API）；加连接池 |
| 9 | **审计** | JSONL 持久化 + trace_id 贯穿 + AUDIT_LOG 可切换 | 结构化日志（JSON）+ SIEM 接入 + 不可篡改 | JSONL 已结构化；缺集中查询、防篡改 | 接 ELK/Loki；关键审计写 WORM 存储 |
| 10 | **部署** | Dockerfile + FastAPI 网关 + compose + 健康检查 | 容器化 + API 网关 + 水平扩展 + 健康检查 | 代码完成，Docker 环境待验收 | 启动 Docker Desktop → build → up → 验收 |
| 11 | **护栏** 🆕 | guardrails 模块：越权指令/敏感信息检测 + 缺失段落检查 + block/warn/off 模式 ✅R2 | Guardrails AI / NeMo Guardrails + JSON Schema 校验 + 有害内容分类 | 有规则引擎；缺小模型有害内容分类器、RAIL 规范 | 调研 Guardrails AI 的 RAIL 规范 |
| 12 | **评估** 🆕 | eval 模块：10 组 ground truth + 3 维指标 + runner + 回归基线 ✅R6 | RAGAS + Langfuse + 持续评估 pipeline + 轨迹评估 | 有基础评估；缺 CI 集成、轨迹评估（trajectory eval） | 接入 CI pipeline；加 trajectory evaluation |

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
- [x] **成本监控（#1）**：LLM 调用自动计费，预算熔断，费用摘要含进度条
- [x] **Token 持久化（#2）**：SQLite 默认存储 + `TOKEN_STORE=memory` 切回内存
- [x] **审计持久化（#3）**：JSONL 即时落盘 + `AUDIT_LOG=none` 禁用
- [x] **L1 精确缓存**：SQLite 存储，相同 prompt 命中 <1ms，0 token 消耗
- [x] **LLM 连接池**：provider 级 httpx 连接池，keep-alive 60s，复用 TCP 连接
- [x] **R1 工具沙箱**：`tools/sandbox.py`，超时控制 + 指数退避重试（TOOL_TIMEOUT/TOOL_MAX_RETRIES）
- [x] **R2 输出护栏**：`guardrails/` 模块，越权指令/敏感信息检测 + 缺失段落检查 + block/warn/off 模式
- [x] **R3 步骤校验**：`evaluate_results` 不再 noop，检查工具结果质量 + 数据完整性
- [x] **R4 上下文压缩**：`graph/context_compressor.py`，summarization buffer 自动摘要
- [x] **R5 MCP 进程隔离**：`tools/mcp_client.py`，MCP_MODE=mcp 走子进程通信
- [x] **R6 Agent 评估**：`eval/` 模块，10 组 ground truth + 3 指标 + runner
- [x] **R7 结构化筛选**：`query_orders` 支持 8 字段 AND 组合筛选 + 排序 + limit
- [x] **R8 多租户隔离**：Token + tenant_id，数据层租户过滤，FORCE_TENANT 强制模式

## 13. 新增环境变量

R1-R8 改造新增的环境变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TOOL_TIMEOUT` | `10` | 单次工具调用超时秒数（R1） |
| `TOOL_MAX_RETRIES` | `3` | 最大重试次数（R1） |
| `GUARDRAILS_MODE` | `warn` | 护栏模式：block/warn/off（R2） |
| `CONTEXT_MAX_CHARS` | `8000` | 触发上下文压缩的字符阈值（R4） |
| `CONTEXT_KEEP_RECENT` | `6` | 压缩后保留的最近消息数（R4） |
| `MCP_MODE` | `local` | 工具调用模式：local/mcp（R5） |
| `FORCE_TENANT` | `false` | 强制租户隔离（R8） |

## 14. 运行评估（三层：工具 / 轨迹 / 语义）

```bash
# 跑全部 10 个 case（单 Agent 模式，含 LLM-as-Judge）
python -m demo.eval.runner

# 跑单个 case
python -m demo.eval.runner --case eval_001

# 多 Agent 模式
python -m demo.eval.runner --mode multi

# 跳过 LLM-as-Judge（评估提速/省钱，语义层降级为关键词启发式）
python -m demo.eval.runner --no-judge

# 生成单页 HTML 可视化报告（demo/eval/reports/）
python -m demo.eval.runner --report
```

## 15. 运行回测（历史延期复盘）

```bash
# 跑全部 5 个历史延期复盘场景（需真实 LLM）
python -m demo.backtest.runner
```

## 16. 一键自动化测试（CI 入口）

```bash
# 全量单测 + 集成测试（mock LLM，零成本）——128 passed
python run_all_tests.py

# 全量单测 + 三层评估（真实 LLM，需 .env key）
python run_all_tests.py --eval

# 全量单测 + 三层评估 + 生成 HTML 报告
python run_all_tests.py --report

# 评估时跳过 LLM-as-Judge（省钱/提速）
python run_all_tests.py --no-judge
```

> 等价的 shell 脚本：`./test_demo.sh`

---

## 17. 行业差距与评估结论（2026-08-09）

> 完整报告：`docs/week6/demo-制造业智能体缺失评估报告-2026-08-09.md`
> 评估方式：CodeGraph 全模块静态分析 + 真实运行验证（`--check` + pytest 128 passed）+ 2026 制造业智能体行业实践调研。
> 评审团：CLAUDE.md 9 角色（开发者/测试者/架构/安全/DBA/前端架构/前端开发/代码走读/法律合规）+ AI 专家 + 技术专家。

### 17.1 成熟度评分（对照行业基线）

| 维度 | 现状 | 行业基线 | 主要差距 |
|------|------|---------|---------|
| 编排层 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 缺 human-in-the-loop、动态约束、子任务并行 |
| 工具层 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 缺真实业务源、IoT/APS 集成 |
| **评估体系** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 三层评估已超行业均值，缺 CI 持续化 |
| 数据层 | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | CSV 快照 vs 实时 DB/MES/ERP |
| 安全 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 缺 API 限流、密钥管理、JWT 签名 |
| 可观测性 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 有 trace/成本/审计，缺自动告警、采样、看板 |
| 制造业业务 | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 缺 APS 排产算法、IoT 数据、排产变更闭环 |

### 17.2 差距清单（按优先级）

**P0（制造业主线，必须补）**

| # | 缺失 | 说明 |
|---|------|------|
| M1 | **排产约束求解** | 用 OR-Tools / 启发式做交期-产能-物料约束排产，而非纯 LLM 文本建议 |
| M2 | **实时数据源抽象** | DataSource 接口，CSV→MySQL/MES/IoT 可插拔，支持增量更新 |
| M3 | **human-in-the-loop** | LangGraph `interrupt_before` 关键排产决策人工确认 |
| M4 | **结构化排产结果** | `final_answer` 之外输出 JSON 排产表（订单/优先级/时间/原因），供数值验证 |

**P1（生产化加固）**

| # | 缺失 | 说明 |
|---|------|------|
| M5 | **API 限流** | 网关层 rate limit，防打爆预算 |
| M6 | **Token 签名 + refresh** | JWT 签名防伪造；refresh token 续期 |
| M7 | **评估接 CI** | 每次 commit 自动跑 eval，回归基线门槛 |
| M8 | **自动告警 + 采样** | provider 失败率阈值告警；高 QPS 采样导出 |
| M9 | **排产可视化看板** | Web 界面展示排产表/设备负载/风险标记 |

**P2（纵深完善）**

| # | 缺失 | 说明 |
|---|------|------|
| M10 | **Prompt 版本管理 / A/B** | `prompts/` 版本化 + 分流 |
| M11 | **Langfuse 看板** | 观测 + 评估一体，替代 console 导出 |
| M12 | **评估闭环** | 低分场景自动归档 → 反哺 prompt/参数 |
| M13 | **多环境隔离** | dev/staging/prod 配置分离 |

### 17.3 下一步建议（按性价比）

`M4 结构化排产结果 → M1 约束求解 → M7 CI 持续评估 → M2 数据源抽象 → M3 human-in-the-loop`

---

## 18. 相关文档链接（2026-08-08 ~ 08-09 评估改造）

> 本 demo 的评估体系改造（三层评估 + 回测）与制造业智能体缺失评估的完整过程记录，见以下文档。

### 评估报告 / 现状分析

| 文档 | 说明 |
|------|------|
| [制造业智能体缺失评估报告](../docs/week6/demo-制造业智能体缺失评估报告-2026-08-09.md) | 完整缺失评估：行业基线 + 11 位评审团 + M1-M13 差距 |
| [Agent 评估行业实践与 demo 现状分析](../docs/courses/Agent评估行业实践与demo现状分析-2026-08-08.md) | 2026 行业评估范式 + ragas 停滞分析，为何弃 ragas 自研 |

### 改造计划 / 实现过程

| 文档 | 说明 |
|------|------|
| [评估改造方案](../docs/week6/demo-评估改造方案-2026-08-09.md) | 全量执行分阶段路线图：Phase A 重问题修补 → B 制造业主线 → C 生产化 → D 评估深化（CI 载体=本地） |
| [三层评估体系实现计划](../docs/superpowers/plans/2026-08-08-ragas升级-三层评估体系.md) | 改造前的完整实现计划（TDD + writing-plans） |
| [评估改造实现过程定位](../docs/week6/demo-评估改造实现过程定位-2026-08-09.md) | 实现实录：16 个坑复盘 + 根因归属 + 修测试/修代码分类 |
| [8 大缺陷可执行改造方案](../docs/week5/8大缺陷-可执行代码改造方案.md) | R1-R8 缺陷修复方案（评估体系改造的源头） |

### Session 记录

| 文档 | 说明 |
|------|------|
| [session 08-08 行业现状分析](../job-portfolio/sessions/session-2026-08-08-Agent评估体系现状与行业实践分析.md) | 评估体系现状梳理 + 行业实践调研 |
| [session 08-09 三层评估实现](../job-portfolio/sessions/session-2026-08-09-demo三层评估体系实现+全量测试+回测.md) | 三层评估 + 全量测试 + 回测实现 |
| [session 08-09 缺失评估报告](../job-portfolio/sessions/session-2026-08-09-demo制造业智能体缺失评估报告.md) | 制造业智能体缺失评估 + 11 位评审团 |
