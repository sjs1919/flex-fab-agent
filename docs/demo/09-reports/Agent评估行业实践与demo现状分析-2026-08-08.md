# Agent 评估行业实践与 demo 现状分析

> 日期：2026-08-08
> 背景：推进 demo 评估体系改造前，先厘清行业当前评估 Agent 的最佳实践，以及 ragas 到底该用什么替代。
> 触发：会话中对「demo 用真 ragas 还是手写 eval」的讨论。
> 结论：**demo 继续用自研 eval，不引入 ragas**（ragas 已停滞 + 依赖问题）。若要升级，优先补 LLM-as-Judge 语义指标，而非换库。

---

## 一、当前 demo 评估体系（现状速览）

| 文件 | 作用 |
|------|------|
| `demo/eval/ground_truth.json` | 10 个排产场景（expected_tools / expected_order_ids / checks） |
| `demo/eval/metrics.py` | 手写 3 指标：工具 F1×0.3 + 完整性×0.5 + 订单召回×0.2 |
| `demo/eval/runner.py` | 遍历 10 case 跑真实 Agent，case ≥0.6 算 pass，回归基线 ≥7/10 |

**硬伤：**
- `ground_truth.json` 的 `min_tools_called` 字段，`metrics.py` 根本没读
- 完整性检查是**子串匹配**（`must_contain`），语义不对也判过
- 缺 **LLM-as-Judge 语义指标**（忠实度/相关性）
- **context 没被采集**：`search_knowledge_base` 把检索 hits 展平成字符串，RAGAS 的 context_precision/recall 想算也拿不到结构化上下文
- 缺 **trajectory 评估**（只看工具名，不看参数/顺序/重试）

---

## 二、行业最佳实践：评估 Agent 的分层体系

2025-2026 年行业共识是**分层评估**，单一指标已不够。业界主流是「**轨迹（trajectory）+ 输出（output）+ 成本/延迟**」三维一起评估。

### 1. 轨迹评估（Trajectory Evaluation）— 核心新趋势

不只看最终答案，看 **Agent 走过的路径对不对**：调了哪些工具、顺序、重试次数、是否绕远路。

- **工具选择正确性**（该调哪个调了没）
- **工具调用参数正确性**（参数对不对，不只是工具名）
- **路径效率**（是否过度调用工具、是否卡在死循环）
- **任务完成率**（task completion rate）

> 你的 demo 现有 eval 是「看最终答案 + 工具名集合」，属于轨迹评估的**很浅的一层**。

### 2. LLM-as-Judge（LLM 当裁判）

让一个更强的 LLM 给结果打分。RAGAS 的 faithfulness / answer_relevancy 就是这个路线。

- 2025 年 DeepMind 正式提出 **Agent-as-a-Judge** 方法论（ICML 2025）
- 趋势：**judge 也 agentic**，不只是打分，还要复现任务、验证轨迹

### 3. 工具调用级评估

针对 tool-calling Agent：
- tool name 是否正确、参数 schema 是否合法
- 返回值是否被正确消费
- 是否优雅处理工具报错

### 4. 成本/延迟约束

单次任务 token 消耗、延迟、失败重试成本 —— 生产场景越来越重要。

### 5. 回归 + 持续评估（CI）

把 ground-truth 场景纳入 CI，每次改代码自动跑，防止回归。

---

## 三、ragas 到底用什么替代了

**ragas 目前处于基本停滞状态**（0.4.3 就是 PyPI 最高版本，无更新可升）。它停在 langchain 拆分之前，导致它自己的代码（`from langchain_community.chat_models.vertexai import ChatVertexAI`）跟新版 langchain-community 不兼容 —— **这是「ragas 过时」，不是 langchain 不兼容 ragas**。

社区实际上已分裂成几个方向：

| 库/平台 | 定位 | 特点 |
|---------|------|------|
| **DeepEval** | OSS 库，最接近 ragas 的直接替代 | pytest 原生、metric 库最全、**trajectory eval 支持好**、LLM-as-judge |
| **LangSmith / Langfuse / Arize Phoenix** | 平台（本地自部署） | 观测 + 评估一体，自带 evals 面板，**trajectory 可视化** |
| **Braintrust / Promptfoo** | 平台 | 强在 prompt 对比、回归测试、CI 集成 |
| **自研轻量 eval 模块** | 你 demo 现在这样 | 最轻、可控，但语义深度有限 |

**关键点**：现在没有一个统一的「下一个 ragas」，而是**按需组合**。绝大多数生产团队不再只用 ragas 这种单库，而是用「观测平台（Langfuse/Phoenix）+ 评估库（DeepEval）+ 自研轨迹规则」的组合。

---

## 四、结论与建议

- **不引入 ragas**：已停滞 + 依赖问题，接入成本高、收益低。
- **demo 继续用自研 eval**，但**补齐缺失的层**：
  1. **LLM-as-Judge 语义指标**（忠实度/相关性）— 现在全是指纹/子串匹配
  2. **Trajectory 评估**（参数正确性 / 顺序 / 重试 / min_tools_called）— 现在只看工具名集合
- 若要上平台，优先考虑 **Langfuse**（观测 + 评估一体，week6 已有 Langfuse 待办 #12）。

---

## 附：参考来源

- [Ragas Alternatives in 2026: 7 Production RAG Eval Picks](https://futureagi.com/blog/ragas-alternatives-2026/)
- [AI Agent Evaluation (2026): Metrics, Frameworks, and Production Failures](https://www.morphllm.com/ai-agent-evaluation)
- [Agent-as-a-Judge: Evaluate Agents with Agents (ICML 2025)](https://icml.cc/virtual/2025/poster/45485)
- [AI agent evaluation: trajectory, tool calls, and task completion - Langfuse](https://langfuse.com/resources/engineering/ai-agent-evaluation)
- [LLM Evaluation Framework: Trajectories vs. Outputs - LangChain](https://www.langchain.com/resources/llm-evaluation-framework)
- [Ragas Release v0.4.3](https://github.com/vibrantlabsai/ragas/releases/tag/v0.4.3)
