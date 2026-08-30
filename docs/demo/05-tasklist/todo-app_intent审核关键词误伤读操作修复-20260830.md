# app_intent 审核关键词误伤读操作修复 待办

> 日期：2026-08-30 · 优先级：P1 · 状态：✅ 已完成（app_intent 排除查询动词 + pending_write schema 修复 + 编排层代执行审批，121 测试 + 真实回归全过）
> 背景：问题「帮我查询审核通过的批次」产出答非所问（综合调度分析），trace `e3956b5fe47a4a71` / 复现 `8174438df368437f`；且垃圾答案投毒语义缓存（复现首次直接 cache hit `b50f21afebd34b76`）。踩坑已记录：`docs/pitfalls/20260830-app_intent审核关键词误伤读操作.md`。

## 事项（app_intent 关键词误伤读操作）

**根因链**：
1. `app_intent = any(k in user_text for k in ("审批", "驳回", "审核"))`（`single_agent_graph.py:277`）——「帮我**查询**审核通过的批次」含「审核」→ `app_intent=True`
2. `if app_intent and "approve_schedule" not in tool_names:`（`:285`）→ 用户没让审批，LLM 不调 `approve_schedule` → 每轮强制 `needs_more`
3. select_and_execute 注入 `pending_write`：「用户明确要求执行 approve_schedule（审批排产版本）…不要只做查询」——**与真实查询意图冲突**
4. LLM 被矛盾指令带偏：反复 `query_schedule`（含 3 次无意义 `version_id:0`）→ 转查订单（`status=已审核`）→ 编出「综合调度分析」
5. iteration≥5 强制收尾 → 垃圾成为 final_answer → 格式正常的垃圾**写入语义缓存** → 重问永远命中（投毒变体）

**核心缺陷**：关键词意图识别未区分读/写。「查询审核通过的批次」（定语，读）被误判为「把 XX 审核通过」（谓语，写）。上一轮副作用评估「无实际危害」错误——pending_write 注入的是执行指令，不是无害提示。

## 修复方案

**方案 1（读操作误判，核心·已完成）**：`app_intent` 判定排除**查询动词**：用户文本含读操作信号（查/查询/查看/找/有哪些/哪些/列出/看看）时，「审核」为定语而非审批谓语，不得判为审批写操作。保留「帮我把待审核的排产版本审核通过」审批路径（该文本无查询动词）。

**方案 2（pending_write 机制修复·已完成）**：`pending_write` 此前因 `AgentState` schema 未声明**从未真正传递**（LangGraph 丢弃 schema 外 key，注入从未生效）。补声明 + 指令每轮重注入 + 工具过滤（tools 只留写工具）。

**方案 3（审批执行兜底·编排层代执行，2026-08-30 用户确认）**：真实 LLM 验证发现 DeepSeek **幻觉调用历史工具**——tools 过滤只留 `approve_schedule` 仍返回 `query_schedule`（trace `9fb9384a`），pending_write 注入/工具过滤均不可靠。改为：evaluate 检测 app_intent 且 `approve_schedule` 未执行、`iteration>=2`（LLM 已有多轮机会）→ **编排层直接执行 `approve_schedule`**（版本号从已收集 query_schedule 结果提取，token 用 STS 签发），确定性完成审批，不依赖 LLM 自觉。

## 任务拆分

- [x] **T1 TDD 红测试**（`demo/graph/test_single_agent_graph.py`）：
  - `test_query_approved_batches_is_read_not_approve`：「帮我查询审核通过的批次」→ 不强制 `approve_schedule`、不注入审批指令、正常汇总收尾
  - `test_approve_intent_forced_by_orchestrator`：审批意图 + LLM 连续 2 轮不执行 → 编排层代执行 `approve_schedule`（tool_results 含该工具）
- [x] **T2 实现**：
  - `single_agent_graph.py` 定义 `_QUERY_VERBS` + `app_intent` 排除查询信号
  - `state.py` 补 `pending_write` schema
  - select_and_execute pending_write 每轮重注入 + 工具过滤 + 指令 insert 最前
  - evaluate app_intent 分支：`iteration>=2` 时代执行 `approve_schedule`（`_extract_schedule_version` 提取版本号 + STS 签 token + 清理注入消息）
- [x] **T3 验证**：graph/agents/cache/scheduler 121 测试全绿（回归子集 exit 0）
- [x] **T4 真实回归**：查询「审核通过的批次」正确（trace a6b4c37e）；审批「审核通过」编排层代执行 approve_schedule（trace c6030f5e，版本66已审核被正确拒绝——业务正确）
- [x] **T5 规则升级**：`rules/common/llm-agent.md` 红线 4「关键词意图识别必须区分读/写」+ 红线 5「LangGraph 状态 key 必须声明 schema」
- [x] **T6 报告**：门禁核对 + CR 走读（无重大缺陷，1 个已知边界记录）+ 报告用户验收

## 验收 checklist（🔴 门禁）

1. 「帮我查询审核通过的批次」→ 正常查询收尾（非审批强制、非综合分析垃圾）
2. 「帮我把待审核的排产版本审核通过」→ 审批路径保留（`approve_schedule` 仍被调用）
3. 新增单测先红后绿；graph/agents 全量 + 相关子集全绿
4. 真实回归通过；缓存已清无残留
5. CR 走读通过

## 关联

- 根因证据：trace `e3956b5f` / `8174438df368437f` / 缓存命中 `b50f21af`；审批残留 trace `83e162c3`
- 踩坑：`docs/pitfalls/20260830-app_intent审核关键词误伤读操作.md`
- 交叉：`todo-审核意图识别与汇总兜底优化-20260830.md`（本轮修复的回归源——上轮补「审核」关键词未排除读语义；pending_write 单次注入残留）
