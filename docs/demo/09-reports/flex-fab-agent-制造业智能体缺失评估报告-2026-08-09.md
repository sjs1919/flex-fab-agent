# 制造业智能体 demo 缺失评估报告 — 行业最佳实践对照

> **日期：2026-08-09**
> **评估对象：** `projects/agent-training/demo/`（多 Agent 排产助手，LangGraph + LLM API）
> **评估方式：** CodeGraph 全模块静态分析 + 真实运行验证（`--check` / pytest 128 passed）+ 行业实践调研
> **评审团：** CLAUDE.md 9 角色评估表（开发者/测试者/架构审查/安全审查/DBA 运维/前端架构师/前端开发工程师/代码走读/法律合规审查）+ AI 专家 + 技术专家

---

## 〇、评估结论速览（TL;DR）

**demo 当前成熟度：⭐⭐⭐⭐☆（4/5）** — 一个**教学级→生产级过渡**的排产 Agent 骨架，Harness 三层（编排/权限/观测）架构完整，但**制造业业务纵深**（APS 排产约束、IoT 实时数据、人机协同）和**生产级工程能力**（可观测性闭环、多环境、安全纵深）仍有明显缺口。

| 维度 | 现状评分 | 行业基线评分 | 主要差距 |
|------|---------|------------|---------|
| 编排层 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 缺 human-in-the-loop、动态约束、子任务并行 |
| 工具层 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 缺真实业务源、IoT/APS 集成、工具结果结构化 |
| 评估体系 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 三层评估已领先行业均值，但缺 CI 持续化 |
| 数据层 | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | CSV 快照 vs 实时 DB/MES/ERP |
| 安全 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 缺 API 限流、密钥管理、JWT 签名 |
| 可观测性 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 有 trace/成本/审计，缺自动告警、采样、看板 |
| 制造业业务 | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 缺 APS 排产算法、IoT 数据、排产变更闭环 |

---

## 一、行业最佳实践基线（制造业智能体，2026）

> 基于 2026 年制造业智能体行业调研：AI 自动排产重塑 MES 核心决策力、Agentic scheduling 自适应车间调度、风险感知生产决策。

### 1.1 制造业智能体的行业定位

制造业 AI 已从「报表问答」升级为**「风险感知决策」**。行业共识：

- **实时性**：从「天级排程」到「分钟级重排」（鼎華智能秒级重排）
- **决策深度**：不止查数据，要做「交期承诺 + 风险预警 + 自动调整」
- **多源数据**：APS（排产）/ MES（执行）/ ERP（订单）/ IoT（设备实时状态）四层打通
- **闭环**：排产 → 执行 → 异常 → 重排 的闭环（Agentic scheduling on UNS）

### 1.2 行业对 Agent 的评估范式（2026）

| 范式 | 说明 | demo 现状 |
|------|------|----------|
| **三层评估** | 轨迹（trajectory）+ 输出（output）+ 成本/延迟 | ✅ 已实现（工具/轨迹/语义） |
| **LLM-as-Judge** | 更强的 LLM 打分，替代子串匹配 | ✅ 已实现（faithfulness/relevancy） |
| **轨迹评估** | 工具顺序/参数/重试/效率 | ✅ 已实现（path_efficiency/retry/loop） |
| **持续评估（CI）** | 每次代码变更自动回归 | ⚠️ 有脚本，未接 CI |
| **回归基线** | 至少 N/M 通过 | ✅ 已实现（7/10 基线） |
| **生产监测** | 线上真实流量打点评估 | ❌ 未实现 |

### 1.3 制造业特有的评估维度（demo 缺失）

| 维度 | 说明 | 现状 |
|------|------|------|
| **排产正确性** | 排产结果是否满足交期/产能/物料约束 | ⚠️ 有排序逻辑，无数值验证 |
| **约束满足** | 硬约束（交期）vs 软约束（优先级）是否区分 | ❌ 未区分 |
| **实时数据敏感性** | 数据更新后决策是否同步 | ❌ CSV 静态快照 |
| **人机协同** | 关键决策是否有人确认 | ❌ 无 human-in-the-loop |
| **异常恢复** | 设备故障/物料延迟时能否自愈 | ⚠️ 有重试，无场景化降级 |

---

## 二、CodeGraph 阅读结论：demo 现状盘点（实证）

### 2.1 模块依赖与活跃度

CodeGraph 索引 **115 文件 / 1,438 节点 / 2,894 边**。demo 采用 Harness 三层（编排/权限/观测）+ 工具注册中心架构。

### 2.2 已实现（实证确认）

| 能力 | 证据（代码位置） |
|------|----------------|
| **LangGraph 编排** | `graph/single_agent_graph.py`：analyze→select→evaluate→generate 循环 + should_continue 条件边 + 5 轮安全阀 |
| **数据质量校验（R3）** | `evaluate_results` 检查工具结果非空/非错误 + 订单/资源数据完整性 |
| **上下文压缩（R4）** | `select_and_execute` 前 `should_compress` + summarization buffer |
| **输出护栏（R2）** | `generate_answer` 集成 `run_guardrails`，block/warn/off + 重试 2 次 |
| **工具沙箱（R1）** | `registry.execute` → `sandbox.run_with_retry`（超时 + 指数退避） |
| **主备降级** | `config.py` PROVIDERS 列表，火山豆包→DeepSeek（实证 429 后自动切换） |
| **三层评估（R6+）** | `eval/` 工具层 + 轨迹层 + 语义层（judge），回归基线 7/10 |
| **回测模块** | `backtest/` 5 个历史延期复盘场景，覆盖度评分 |
| **观测/成本/审计** | `observability/` trace + cost（熔断）+ auth 审计 JSONL |
| **多租户（R8）** | `auth/token_exchange.py` tenant_id 全链路透传 + FORCE_TENANT |
| **测试** | **128 passed**（pytest 实证），单元 + 集成 + 回测 |
| **可部署** | `api.py` FastAPI + Dockerfile + compose |

### 2.3 发现的缺口（实证定位）

| # | 缺口 | 位置 | 严重度 |
|---|------|------|--------|
| G1 | **排产建议无数值验证** | `graph/generate_answer` 仅字符串输出，无结构化排产结果 | 🔴 高 |
| G2 | **硬约束/软约束未区分** | `order_tools` 排序仅按字段，无约束求解 | 🔴 高 |
| G3 | **无 human-in-the-loop** | `graph` 全程自动，无中断确认点 | 🟡 中 |
| G4 | **数据是 CSV 静态快照** | `tools/data.py` 读 CSV，无实时源 | 🔴 高 |
| G5 | **评估未接 CI** | `run_all_tests.py` 需手动跑，无定时/触发 | 🟡 中 |
| G6 | **无自动告警/采样** | `observability/` 无阈值告警、无采样 | 🟡 中 |
| G7 | **API 无限流** | `api.py` 无 rate limit | 🟡 中 |
| G8 | **安全纵深不足** | Token 无 JWT 签名、无 refresh；单 Agent 模式 RBAC 放行 | 🟡 中 |
| G9 | **缺 IoT/APS 集成** | 无设备实时数据源、无排产算法 | 🔴 高 |

---

## 三、评审团评估（9 角色 + AI 专家 + 技术专家）

### 3.1 评审团构成

按 CLAUDE.md 的任务工作流「9 角色评估表」，本次评估邀请全部 9 位角色 + 用户特别指定的 AI 专家 + 技术专家，共 **11 位评审**。

### 3.2 各角色评审意见

#### 开发者（代码正确性、编译通过、变更点覆盖）
- **PASS**：128 测试全绿，LangGraph 图逻辑完整，注册中心 O(1) 查找无死代码
- **关注**：`generate_answer` 的 `call_llm` 未传 `tools`，排产建议是纯 LLM 文本生成，无结构化校验

#### 测试者（单元测试、E2E、边界）
- **PASS**：17 个测试文件、128 用例覆盖 8 模块 + 回测
- **关注**：缺「排产结果数值正确性」断言（如 ORD003 是否真排在前面）；真实 LLM 回归受主 provider 配额影响

#### 架构审查（分层清晰、依赖方向）
- **PASS**：Harness 三层 + 注册中心依赖方向正确，无循环引用
- **关注**：多 Agent 的 supervisor 对 "query" 类路由无实际调度（`supervisor.py:104`），路由到单 Agent 只是注释

#### 安全审查（注入、越权、凭证）
- **PASS**：参数白名单 + RBAC + 租户隔离 + 护栏 + 沙箱
- **⚠️ 不合格项**：Token 无签名（篡改即伪造）；单 Agent 模式 RBAC 放行（`registry.py` token=None 跳过）；API 无限流；密钥在 `.env` 明文

#### DBA 运维（迁移、幂等、回滚）
- **PASS**：SQLite 无需迁移，Chroma 懒加载重建，RUNTIME_DIR 分离
- **关注**：生产演进需 PG + Redis + Milvus，无迁移脚本

#### 前端架构师（组件分层、路由守卫）
- **PASS**：无前端；API 网关层清晰
- **关注**：无 Web 管理界面，排产结果无可视化看板

#### 前端开发工程师（TS、响应式、表单）
- **N/A**：纯后端 demo，无前端界面

#### 代码走读（命名、注释、死代码、复杂度）
- **PASS**：命名一致，中文注释标设计意图，无 TODO 残留
- **关注**：`scripts/week1-4/` 旧脚本仍在（知识演进对照用，非死代码）

#### 法律合规审查（PIPL、开源、跨境）
- **PASS**：demo 无真实用户数据，无跨境传输；依赖均为 MIT/Apache 开源
- **关注**：生产接入真实 MES/ERP 需数据合规评估

#### AI 专家（行业 Agent 实践）
- **核心意见**：demo 的**三层评估 + 自研 judge + 回测**已经超过多数生产团队，但缺「**评估结果反哺 Agent 行为**」的闭环——目前评估只是「打分报告」，没有「低分场景→自动调参/改 prompt」的反馈回路
- **建议**：补 ① 评估失败场景自动归档复现；② 排产约束求解器（OR-Tools）；③ 人机协同确认点

#### 技术专家（架构与生产化）
- **核心意见**：demo 是「**单点快照推理**」，行业是「**实时数据闭环**」。差距不在代码质量，在**数据时态**——CSV 快照无法验证「数据更新后决策是否自适应」
- **建议**：① 数据层抽象出 DataSource 接口，CSV→DB/IoT 可插拔；② 补 SSE/WebSocket 实时事件流；③ 补人工确认中断（LangGraph interrupt）

---

## 四、缺失清单（按优先级）

### P0（制造业主线，必须补）

| # | 缺失 | 说明 | 对应角色 |
|---|------|------|---------|
| M1 | **排产约束求解** | 用 OR-Tools / 启发式做交期-产能-物料约束排产，而非纯 LLM 文本建议 | 技术专家/AI 专家 |
| M2 | **实时数据源抽象** | DataSource 接口，CSV→MySQL/MES/IoT 可插拔；支持增量更新 | 技术专家 |
| M3 | **human-in-the-loop** | LangGraph `interrupt_before` 关键排产决策人工确认 | AI 专家/架构 |
| M4 | **结构化排产结果** | `final_answer` 之外输出 JSON 排产表（订单/优先级/时间/原因），供数值验证 | 开发者/测试者 |

### P1（生产化加固）

| # | 缺失 | 说明 | 对应角色 |
|---|------|------|---------|
| M5 | **API 限流** | 网关层 rate limit，防打爆预算 | 安全审查 |
| M6 | **Token 签名 + refresh** | JWT 签名防伪造；refresh token 续期 | 安全审查 |
| M7 | **评估接 CI** | 每次 commit 自动跑 eval，回归基线门槛 | 测试者 |
| M8 | **自动告警 + 采样** | provider 失败率阈值告警；高 QPS 采样导出 | 运维/DBA |
| M9 | **排产可视化看板** | Web 界面展示排产表/设备负载/风险标记 | 前端架构师 |

### P2（纵深完善）

| # | 缺失 | 说明 |
|---|------|------|
| M10 | **Prompt 版本管理 / A/B** | `prompts/` 版本化 + 分流 |
| M11 | **Langfuse 看板** | 观测 + 评估一体，替代 console 导出 |
| M12 | **评估闭环** | 低分场景自动归档 → 反哺 prompt/参数 |
| M13 | **多环境隔离** | dev/staging/prod 配置分离 |

---

## 五、与 demo 已有 README 差距表的对照

demo/README.md §9 已有「与行业推荐方案的差距表」（12 项）。本报告是其**行业基准化升级**：

| README 已有差距 | 本报告补充 |
|----------------|-----------|
| #12 评估缺 CI 集成 | ✅ 已补 M7（CI 持续化） |
| #1 编排缺 human-in-the-loop | ✅ 已补 M3（interrupt 确认） |
| #8 数据缺实时源 | ✅ 已补 M2（DataSource 抽象） |
| #3 观测缺告警/采样 | ✅ 已补 M8 |
| #2 权限缺 JWT/refresh | ✅ 已补 M6 |
| #11 护栏缺有害分类器 | 保持待办 |
| — | **新增**：M1 排产约束求解（制造业特有） |
| — | **新增**：M4 结构化排产结果（可数值验证） |
| — | **新增**：M12 评估闭环（AI 专家核心建议） |

---

## 六、结论

**demo 当前是一个架构优秀、工程扎实的教学级→生产级过渡排产 Agent**：
- ✅ **评估体系已超行业均值**（三层 + 自研 judge + 回测 + 128 测试）
- ✅ **Harness 三层完整**（编排/权限/观测 + 工具注册中心）
- ⚠️ **制造业主线缺「排产约束求解」和「实时数据闭环」**——这是从「能跑」到「能用」的最后一公里
- ⚠️ **生产化工程缺限流/告警/CI 持续评估**——上线前必备

**下一步建议（按性价比）**：M4（结构化排产结果）→ M1（约束求解）→ M7（CI 持续评估）→ M2（DataSource 抽象）→ M3（human-in-the-loop）。

---

## 参考来源

- [AI自动排产重塑MES核心决策力](http://c.gongkong.com/PhoneVersion/PaperDetail?paperId=113511)
- [Agentic scheduling: Adaptive shop floor planning on the UNS](https://www.hivemq.com/blog/agentic-scheduling-adaptive-planning-uns/)
- [鼎華 Multi-Agent 智慧工廠運行平台](https://digihua.com.tw/2026automationtaipei/)
- [AI Agent Trajectory Evaluation: 2026 Patterns](https://iotdigitaltwinplm.com/ai-agent-trajectory-evaluation-patterns-2026/)
- [LLM Evaluation Framework: Trajectories vs. Outputs — LangChain](https://www.langchain.com/resources/llm-evaluation-framework)
- [How to build LLM-as-a-Judge evaluators that hold up in production — Arize](https://arize.com/blog/how-to-build-llm-as-a-judge-evaluators-that-hold-up-in-production/)
- [Your Agent Passes Evals and Fails in Production — FutureAGI](https://futureagi.com/blog/agent-passes-evals-fails-production-2026/)
