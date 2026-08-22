# 文档流转规范

> **本项目路径映射**（单仓变体）：模板文档仓目录映射到 `docs/demo/` 下——01-requirements -> `docs/demo/01-requirements/`、02-specs -> `docs/demo/02-specs/`、04-plans -> `docs/demo/04-plans/`、05-tasklist -> `docs/demo/05-tasklist/`、09-reports -> `docs/demo/09-reports/`；待办登记见 `05-tasklist/todo.md`。

## 双仓分层

- **文档仓（`docs/demo/`）**：所有 spec（`02-specs/`）、实现计划（`04-plans/`）、任务索引（`05-tasklist/`）**必须**写入文档仓
- **代码仓**：仅保留编码规范（`rules/`）、API 文档、部署指南等与代码同包提交的文档

## 流转规则

- **即时落盘**：确认需求/决策 → 立即写入 `02-specs/`，不等对话结束
- **规格 → 计划**：spec 确认后（门禁②），计划写入 `04-plans/`，命名 `YYYY-MM-DD-<标识>-plan.md`
- **计划 → 任务**：plan 确认后（门禁③），状态索引写入 `05-tasklist/`
- **实现后回核源头（强制）**：编码完成后必须回到 spec 和 plan 逐条核对验收标准，确认无遗漏

## 归档

- 禁止物理删除，加 `_archived-` 前缀
- 覆盖前须用户同意；新建/改名后同步更新索引

## 待办事项登记

对话中出现待办事项（用户提及/讨论中产生/完成后剩余未完成项）→ **必须**询问用户是否需要登记到文档仓 `00-taskregister/`：

- 索引文件：`taskregister-index.md`（活跃总表 + 按日期归档）
- 单日文件：`YYYYMMDD-<topic>.md`（格式参考 `_TEMPLATE.md`）
- 每项必须含：日期、事项描述、优先级（P0-P3）、状态（📋/🟢/⏸️/✅/❌）
- 完成后不删除，标记 ✅；发现阻塞立刻更新状态
