# app_intent 关键词「审核」误伤读操作：查询审核通过的批次被当审批执行

## 日期 / 场景

2026-08-30 · 问题「帮我查询审核通过的批次」产出答非所问（一大篇「综合调度分析与建议」），trace `e3956b5fe47a4a71`（复现 `8174438df368437f`）。

> 注：用户报障后我复现，第一次 trace `b50f21afebd34b76` 仅 79.6ms / 1 span / cache:lookup **hit**——垃圾答案已写入语义缓存，二次查询直接命中。清缓存后复现才拿到真实执行链路。

## 根因链

1. **`app_intent` 关键词误伤**（`demo/graph/single_agent_graph.py:277`）：`app_intent = any(k in user_text for k in ("审批", "驳回", "审核"))`——用户文本「帮我**查询**审核通过的批次」含「审核」→ `app_intent = True`
2. **读操作被当写操作强制推进**（`:285`）：`if app_intent and "approve_schedule" not in tool_names:` → 用户没让审批，LLM 自然不调 `approve_schedule` → evaluate 每轮都 `needs_more` 强制继续工具轮
3. **pending_write 注入矛盾指令**（`:164`）：select_and_execute 注入「用户明确要求执行 approve_schedule（审批排产版本）…请立即调用该工具完成操作，不要只做查询或输出建议」——**与真实用户意图（查询）冲突**
4. **LLM 被矛盾指令带偏**：既不能调 approve_schedule（用户没让审批），又被系统催着「执行审批」→ 反复 `query_schedule`（含 3 次无意义的 `version_id:0`）找「已审核」数据 → 最后查到订单（`status=已审核`）→ 基于混乱数据生成「综合调度分析与建议」
5. **iteration ≥ 5 强制收尾**（`should_continue`）→ 垃圾成为 `final_answer`
6. **垃圾答案格式正常 → 写入语义缓存**：缓存门禁只拦拒绝话术/标记文本/兜底前缀，拦不住「格式完整的答非所问」→ 后续查询一直命中垃圾（投毒变体）

## 教训

**关键词意图识别必须区分读/写**。给「审核/审批」补关键词修复审批漏识别时，只加了写操作关键词，没排除读操作语义——「查询审核通过的批次」（定语，读）被误判为「把 XX 审核通过」（谓语，写）。

上一轮修复标注的副作用「含「审核」的非审批查询多走一轮工具轮，无实际危害」**预测错误**：pending_write 注入的不是无害提示，而是与真实意图冲突的**执行指令**，会把 LLM 逼进答非所问的循环。副作用评估不能只看「多走一轮」，要看注入内容是否可能违背真实意图。

**格式正常的答非所问能投毒语义缓存**。缓存门禁按格式特征（标记文本/拒绝话术/兜底前缀）拦截，对语义质量无能为力——垃圾答案一旦写入，重问永远命中。缓存层拦不住 → 必须**源头修复 + 清缓存**。

## 规避动作（修复方向）

- `app_intent` 判定排除查询动词：文本含「查/查询/查看/找/有哪些/哪些/列出」等读操作信号时，不得判为审批写操作
- 新增单测锁定两种语义：
  - 「帮我查询审核通过的批次」→ `app_intent=False`（正常查询，不强制工具轮、不注入审批指令）
  - 「帮我把待审核的排产版本审核通过」→ `app_intent=True`（审批路径保留）
- 修复后清语义缓存（`docker exec demo-api rm -rf /data/runtime/cache_db` + **重启容器**——只删磁盘文件不够，Chroma 进程内存 collection 仍在，必须重启才真正清空）

## 顺带发现（同修复链，trace 83e162c3 / 22af96b9 / d25b1e42）

**坑 1：`pending_write` 机制此前从未真正生效——LangGraph 丢弃 schema 外 key。**
`AgentState`（TypedDict）未声明 `pending_write` 字段，evaluate 设置的值被 StateGraph 丢弃，select_and_execute 永远读到 None → 注入从未发生。之前 bug 3「验证通过」是 LLM 恰好自己执行了审批（ac6c8048），非 pending_write 之功。**修复**：`state.py` 补声明 `pending_write: str`。

**坑 2：DeepSeek 对写操作指令遵循度不足，即使注入也倾向查询数据。**
补 schema 后注入生效，但 LLM 仍连续 4 次 `query_schedule` 不调审批（被延期数据带偏）。**修复**：pending_write 强制时 `tools_schema` 过滤为只含写工具 + 指令附版本号（`version_id` 从已收集的 query_schedule 结果提取）——LLM 无查询工具可选，只能调写工具，确定性兜底。

**坑 3：注入的 system 指令在写操作执行后残留，可能干扰汇总轮。**
写工具执行后 evaluate 清 `pending_write` 时，同步移除 messages 里「用户明确要求执行」开头的 system 消息。

**坑 4：清语义缓存必须重启容器。**
`rm -rf cache_db` 只删磁盘，Chroma 进程内存 collection 仍在，后续查询仍命中旧答案。必须 `docker restart demo-api` 才真正清空（复现验证时多次因只删文件而 cache hit）。

## 是否已升级为规则

是 → `rules/common/llm-agent.md` 红线 4（关键词意图识别必须区分读/写）。
