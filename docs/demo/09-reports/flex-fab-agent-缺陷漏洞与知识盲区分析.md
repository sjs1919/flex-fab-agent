# demo 项目缺陷、漏洞与知识盲区分析

> 基于课程《从能回答到能办事：构建可控的企业级 AI 助手》三梯队框架，对照 demo 代码逐项排查。
> 分析时间：2026-08-06

---

## 一、核心增量盲区（课程第一梯队 → demo 差距）

### ① Harness 工程（主题 6/7）—— 有零件，缺装配

| 课程要求 | demo 现状 | 差距 | 严重程度 |
|---------|----------|------|---------|
| **编排/状态机** | LangGraph 4 节点循环 + 5 轮上限 | 有基础，但缺状态机自检（如"当前在哪一步"的显式状态机查询接口） | 🟡 |
| **工具执行沙箱与重试** | `registry.execute` 直接调 handler，无重试逻辑 | 工具调用失败（如 API 超时、DB 锁）直接抛异常，无指数退避/重试 | 🔴 |
| **上下文管理（压缩/分段）** | 无 | messages 列表无限增长，长轮对话无上下文压缩/截断 | 🔴 |
| **检查点与恢复** | SqliteSaver 持久化 AgentState | 有，但缺少"从检查点恢复后显式校验中间状态完整性"的 hook | 🟡 |
| **可观测（trace/metric/log）** | tracer + exporter + cost | 有，但缺**自动告警**（如成本超阈值自动通知）和**采样**（高 QPS 全量导出性能差） | 🟡 |
| **权限网关** | STS + RBAC + 洋葱三层 | 有，但单 Agent 模式 `token=None` 时完全绕过鉴权，无"强制鉴权模式"开关 | 🟡 |
| **成本预算与熔断** | CostTracker + BudgetExceededError | 有，但**按会话计费**而非按用户/租户计费；无成本看板 | 🟡 |
| **评估与护栏（guardrails）** | 无 | **最大盲区**：没有输出校验（如 LLM 生成的 JSON 格式错误、越权指令、有害内容过滤） | 🔴 |

**关键发现：**
- Harness 的"编排层"有（LangGraph），但"沙箱层""护栏层"完全缺失。
- `supervisor.py` 的 `orchestrate()` 是硬编码流程（if review → dispatch_review → if production → dispatch_production → LLM 综合），不是**声明式编排**（如 YAML/DSL 定义工作流）。课程强调的 Harness 是"可配置、可插拔的装配框架"，demo 还是手写 if/else。

### ② 业务数据包设计（主题 3）—— 有数据，缺"包"

| 课程要求 | demo 现状 | 差距 |
|---------|----------|------|
| **按场景组织数据包** | CSV 分散在 `data/` 目录，工具函数直接读 | 未按"问答/筛选比较/推荐/流程"四类场景组织；无"数据包"概念 |
| **结构化筛选** | `query_orders(status="紧急")` 等工具 | 能回答"紧急订单有哪些"（问答），但**无法回答**"交期 7/30 前、A 级客户、3D打印工艺、按设备空闲排序的前 3 单"（多条件结构化筛选） |
| **推荐型** | RAG 检索合同条款 | 无"和历史延期案例相似"的推荐能力 |
| **流程型** | LangGraph 状态机 | 有，但状态机未和数据包绑定（如"排产流程"=数据包+状态机+工具链的完整封装） |

**关键发现：**
- 课程强调的"数据包决定 Agent 能办什么事"，demo 还停留在"工具函数查表"阶段。没有"排产业务数据包"的显式定义（如一个 `SchedulingDataPackage` 类，封装 orders + inventory + machines + customers + contracts 的联合查询能力）。

### ③ 长任务步骤合并/跳过（主题 5）—— 有上限，缺校验

| 课程要求 | demo 现状 | 差距 |
|---------|----------|------|
| **强制结构化 todo** | 无 | `select_and_execute` 节点无 todo 列表，模型可能跳步（如跳过查设备直接给排产结论） |
| **检查点（持久化中间状态）** | SqliteSaver 存 AgentState | 有，但检查点只存 LangGraph 状态，不存"当前 todo 完成到哪一步" |
| **子任务分解** | Supervisor 拆 review/production | 有，但子任务分解是硬编码（review/production），不是动态分解（如"复杂排产"自动拆成"查订单→查设备→查材料→综合"） |
| **步骤校验** | `evaluate_results` 是 noop | **最大盲区**：没有"每步工具结果是否真的拿到了"的校验。模型可能 hallucinate 工具结果 |
| **上下文压缩** | 无 | messages 无限增长，长轮对话无截断/压缩 |

---

## 二、新视角补强盲区（课程第二梯队）

### ④ Vibe Coding 回炉（主题 4）—— 有代码，缺迭代方法论

| 课程要求 | demo 现状 | 差距 |
|---------|----------|------|
| **快速搭建→迭代式对话开发** | 代码已工程化，但开发过程未记录 | 缺"Vibe Coding"的开发日志（如 prompt 迭代版本、bad case 驱动的优化记录） |
| **Prompt 版本管理** | `system_prompts.py` 硬编码 | 无版本管理（如 `prompts/v1/`、`prompts/v2/`），A/B 测试无基础 |
| **Bad case 驱动优化** | 无 | 没有系统化的 bad case 收集→分析→修复→回归验证流程 |

### ⑤ MVP→PMF + 制造业岗位结合（主题 7/9）

| 课程要求 | demo 现状 | 差距 |
|---------|----------|------|
| **MVP→PMF 演进路线** | 纯技术 demo | 缺产品化视角：从"能跑"到"有人用"到"规模化"的演进路线图 |
| **岗位拆解** | review/production 两个子 Agent | 未和真实制造业岗位（排产计划员、车间调度、质检员）对齐。如"排产计划员"的工作 = 查订单 + 查设备 + 查材料 + 排优先级 + 下发工单，demo 只覆盖了前半段 |
| **SLA 定义** | 无 | 没有定义"排产建议生成时间 < 3s""准确率 > 95%"等 SLA |

---

## 三、复习印证盲区（课程第三梯队）

### ⑥ 回答≠业务结果（主题 1）+ 检索痛点（主题 2）

| 课程要求 | demo 现状 | 差距 |
|---------|----------|------|
| **回答≠业务结果** | 单 Agent 返回文本建议 | 有"调度建议"文本，但**没有"建议被采纳后实际效果如何"的闭环**。课程强调的"能办事"=输出要驱动业务动作（如自动下发工单到 MES），demo 只到"给建议"为止 |
| **RAG 召回痛点** | 混合检索（向量+BM25+RRF+重排） | 有，但**未解决"多条件结构化筛选"**（如"交期 7/30 前 AND 客户等级=A AND 工艺=3D打印"）。RAG 擅长语义匹配，不擅长结构化过滤——这是课程主题 2 的核心痛点，demo 用工具函数绕过了，未正面解决 |

---

## 四、工程实现层面的具体缺陷与漏洞

### 🔴 高严重度

| # | 缺陷/漏洞 | 位置 | 影响 | 修复建议 |
|---|----------|------|------|---------|
| 1 | **工具调用无重试机制** | `tools/registry.py:execute()` | API 超时/网络抖动直接导致任务失败 | 加 `@retry` 装饰器（指数退避，最多 3 次） |
| 2 | **上下文无限增长** | `graph/single_agent_graph.py` | 长轮对话 messages 膨胀，token 成本失控 | 加上下文压缩/截断（保留最近 N 轮，或按 token 数截断） |
| 3 | **无输出护栏（guardrails）** | 全局 | LLM 可能生成有害内容、格式错误 JSON、越权指令 | 加输出校验层（JSON schema 校验、敏感词过滤、权限二次确认） |
| 4 | **步骤校验缺失** | `graph/single_agent_graph.py:evaluate_results` | 模型可能 hallucinate 工具结果，跳过关键步骤 | 实现 todo 列表 + 每步校验（工具结果非空、格式正确） |
| 5 | **单 Agent 模式绕过鉴权** | `tools/registry.py:execute()` | `token=None` 时完全无 RBAC，生产环境危险 | 加 `FORCE_AUTH` 环境变量，强制所有模式走鉴权 |

### 🟡 中严重度

| # | 缺陷 | 位置 | 影响 | 修复建议 |
|---|------|------|------|---------|
| 6 | **Supervisor 硬编码编排** | `agents/supervisor.py` | 新增子 Agent 需改代码，不可配置 | 改为声明式工作流定义（如 YAML/JSON） |
| 7 | **成本按会话计费** | `observability/cost.py` | 多用户场景无法区分谁用了多少 | 按 user_id/tenant_id 分组计费 |
| 8 | **Prompt 无版本管理** | `prompts/system_prompts.py` | A/B 测试、回滚无基础 | 加版本号 + 配置化加载 |
| 9 | **RAG 未解决结构化筛选** | `rag/retriever.py` | 多条件过滤场景无法覆盖 | 引入 NL2SQL 或结构化查询工具 |
| 10 | **无自动告警** | `observability/` | 成本超阈值、错误率飙升无法及时发现 | 加 webhook/邮件告警 |

### 🟢 低严重度（优化项）

| # | 优化项 | 位置 | 建议 |
|---|-------|------|------|
| 11 | **开发日志/Vibe Coding 记录** | 全局 | 建立 `docs/vibe-coding-log.md`，记录 prompt 迭代、bad case、修复过程 |
| 12 | **SLA 定义** | 全局 | 定义响应时间、准确率、可用性等 SLA，并加监控 |
| 13 | **业务闭环** | 全局 | 从"给建议"延伸到"驱动业务动作"（如生成工单、推送到 MES） |

---

## 五、知识盲区总结（按课程主题映射）

| 课程主题 | demo 盲区 | 优先级 |
|---------|----------|--------|
| **主题 1：能回答≠能办事** | 输出只到"给建议"，未驱动业务动作 | 高 |
| **主题 2：检索痛点** | RAG 无法处理多条件结构化筛选（用工具函数绕过了） | 高 |
| **主题 3：业务数据包** | 无"数据包"概念，数据分散在 CSV + 工具函数 | 高 |
| **主题 4：Vibe Coding** | 无 prompt 版本管理、无 bad case 驱动优化流程 | 中 |
| **主题 5：长任务步骤控制** | 无 todo 列表、无步骤校验、无上下文压缩 | 高 |
| **主题 6/7：Harness** | 有零件（编排/权限/观测）缺装配（沙箱/护栏/评估） | 最高 |
| **主题 8：技术体系总览** | 缺 NL2SQL、缺 guardrails、缺业务闭环 | 中 |
| **主题 9：岗位结合** | 子 Agent 未和真实岗位对齐，缺 SLA | 中 |

---

## 六、修复路线图建议

### 第一阶段（Harness 补齐，1-2 周）
1. **工具沙箱**：`registry.execute()` 加重试 + 超时 + 隔离执行
2. **输出护栏**：新建 `guardrails/` 模块，JSON schema 校验 + 敏感词过滤
3. **上下文压缩**：`graph/` 加 messages 截断/压缩逻辑
4. **步骤校验**：`evaluate_results` 节点实现 todo 列表 + 每步校验

### 第二阶段（业务数据包 + 长任务，1-2 周）
5. **业务数据包**：新建 `data_package.py`，封装四类场景查询
6. **NL2SQL/结构化筛选**：针对"多条件筛选"场景，补工具或 NL2SQL 能力
7. **Prompt 版本管理**：`prompts/` 按版本组织，配置化加载

### 第三阶段（产品化 + 闭环，2-3 周）
8. **声明式编排**：Supervisor 改为 YAML 配置
9. **成本按租户**：CostTracker 支持 user_id/tenant_id 分组
10. **业务闭环**：从"给建议"延伸到"生成工单→推送 MES"
11. **SLA + 告警**：定义 SLA，加监控和告警

---

## 七、课程与知识缺失盲区点（附权威教程链接）

> 以下列出每个盲区对应的**已学课程/已读资料**，以及**仍需补充的权威教程**。链接指向 `projects/agent-training/docs/` 下的现有文档或外部权威源。

### 7.1 已学课程对照（现有知识资产）

| 盲区 | 对应已学课程/资料 | 链接 | 掌握度 |
|------|------------------|------|--------|
| Harness 概念框架 | 《从能回答到能办事》主题 6/7 提炼 | [`courses/从能回答到能办事-重点提炼.md`](从能回答到能办事-重点提炼.md) | 理论已学，代码未落地 |
| 业务数据包设计 | 课程主题 3 提炼 + week2 RAG | [`courses/从能回答到能办事-重点提炼.md`](从能回答到能办事-重点提炼.md) · [`week2/day4_guide.md`](../week2/day4_guide.md) | 理论已学，未封装成类 |
| 长任务步骤控制 | 课程主题 5 + week3 LangGraph | [`courses/从能回答到能办事-重点提炼.md`](从能回答到能办事-重点提炼.md) · [`week3/day3_5_guide.md`](../week3/day3_5_guide.md) | 有 iteration 上限，缺 todo/校验 |
| 多 Agent 协作 | week4 多 Agent + 鉴权 | [`week4/day1_2_guide.md`](../week4/day1_2_guide.md) · [`week4/day3_5_guide.md`](../week4/day3_5_guide.md) | 有基础，缺动态分解 |
| RAG 混合检索 | week2 RAG + BM25 + 重排 | [`week2/week2_代码深度解读.md`](../week2/week2_代码深度解读.md) | 有实现，缺结构化筛选 |
| 可观测体系 | week5 tracer + exporter + cost | [`代码阅读指南`](../11-manuals/代码阅读指南.md) 第 12 层 | 有零件，缺告警/采样 |
| Agent 评测 | 美团图灵 Agent 评测文章 | [`courses/Agent评测漫谈-由浅入深讲解Agent评测.md`](Agent评测漫谈-由浅入深讲解Agent评测.md) | 刚整理，未接入 demo |
| 企业级 Agent 入门 | 培训分享稿 | [`train/企业Agent开发入门-20260722.md`](../train/企业Agent开发入门-20260722.md) | 已学，需回炉到 demo |
| 行业对标 | 12 家 Agent 公司深度分析 | [`hangye/README.md`](../hangye/README.md) | 已读，需提取 Harness 实践 |
| Claude Code Harness 解剖 | learn-claude-code s01-s20 | [`learn-claude-code/README-zh.md`](../../learn-claude-code/README-zh.md) | 待深入（s05/s08/s11/s12 最相关） |

### 7.2 仍需补充的权威教程（知识盲区 → 权威源）

| 盲区 | 需补充的知识 | 权威教程来源 | 优先级 |
|------|------------|------------|--------|
| **Guardrails 输出护栏** | 如何校验 LLM 输出（JSON schema、敏感词、越权指令） | [Guardrails AI 官方文档](https://www.guardrailsai.com/docs) · [NVIDIA NeMo Guardrails](https://github.com/NVIDIA/NeMo-Guardrails) | 最高 |
| **上下文压缩工程** | 长上下文截断/压缩策略（snip/micro/budget/auto） | [learn-claude-code s08 Context Compact](../../learn-claude-code/s08_context_compact) · [Anthropic Context Window 最佳实践](https://docs.anthropic.com/en/docs/build-with-claude/context-window) | 高 |
| **NL2SQL / 结构化查询** | 让 Agent 用自然语言查结构化数据库 | [Vanna AI NL2SQL](https://vanna.ai/) · [LangChain SQL Agent](https://python.langchain.com/docs/use_cases/sql/) | 高 |
| **声明式工作流编排** | YAML/DSL 定义多 Agent 工作流（非硬编码） | [LangGraph Studio 工作流](https://langchain-ai.github.io/langgraph/) · [Temporal.io 工作流](https://docs.temporal.io/) | 中 |
| **Agent 评估与回归** | 如何建立 Task-based 评测体系（prompt-expected-trace 三元组） | [Anthropic AI Agent 评估博客](https://www.anthropic.com/research/evaluating-ai-agents) · [课程附录：长程Agent评测开源调研](Agent评测漫谈-由浅入深讲解Agent评测.md) | 高 |
| **成本治理与多租户** | 按 user/tenant 计费、配额、限流 | [OpenAI Usage Tiers](https://platform.openai.com/docs/guides/rate-limits) · [API 网关限流模式](https://konghq.com/blog/how-to-design-rate-limiting) | 中 |
| **Prompt 版本管理与 A/B 测试** | Prompt 迭代版本控制、效果对比 | [LangSmith Prompt Hub](https://docs.smith.langchain.com/prompt_hub) · [Weights & Biases Prompts](https://docs.wandb.ai/guides/prompts) | 中 |
| **业务闭环（MES 集成）** | 从"给建议"到"驱动业务系统" | [OPC UA / MES 集成指南](https://opcfoundation.org/about/opc-technologies/opc-ua/) · [工业 4.0 AAS 架构](https://www.plattform-i40.de/IP/Navigation/EN/Home/home.html) | 低（后期） |
| **SLA 定义与监控** | Agent 系统 SLA 设计（延迟/准确率/可用性） | [Google SRE Book - SLI/SLO/SLA](https://sre.google/sre-book/table-of-contents/) · [Datadog APM SLA 监控](https://docs.datadoghq.com/monitors/types/apm/) | 中 |
| **Vibe Coding 方法论** | 迭代式对话开发、bad case 驱动优化 | [课程主题 4 提炼](从能回答到能办事-重点提炼.md) · [Cursor Composer 工作流](https://docs.cursor.com/composer) | 中 |

### 7.3 推荐阅读路径（按优先级排序）

**立即读（本周）**：
1. [learn-claude-code s05 TodoWrite](../../learn-claude-code/s05_todo_write) → 补"长任务步骤控制"代码实现
2. [learn-claude-code s08 Context Compact](../../learn-claude-code/s08_context_compact) → 补"上下文压缩"代码实现
3. [Guardrails AI Quickstart](https://www.guardrailsai.com/docs) → 补"输出护栏"概念

**下周读**：
4. [Anthropic AI Agent 评估博客](https://www.anthropic.com/research/evaluating-ai-agents) → 补"Agent 评测"体系
5. [课程主题 3 提炼](从能回答到能办事-重点提炼.md) → 回炉"业务数据包"设计
6. [Vanna AI NL2SQL](https://vanna.ai/) → 补"结构化筛选"能力

**后续读**：
7. [learn-claude-code s11 Error Recovery](../../learn-claude-code/s11_error_recovery) → 补"重试/熔断"机制
8. [learn-claude-code s12 Task System](../../learn-claude-code/s12_task_system) → 补"任务持久化/恢复"
9. [行业报告：中科闻歌 Harness 架构](../hangye/Wenge_中科闻歌_深度分析报告.html) → 补"企业级 Harness 实践"
10. [行业报告：语核科技 长任务控制](../hangye/LangCore_语核科技_深度分析报告.html) → 补"反幻觉/步骤校验"实践

---

> **文档维护**：本报告随 demo 代码迭代更新。每次修复一个缺陷后，在此标注 ✅ 并记录 commit。
> 
> 最后更新：2026-08-06
