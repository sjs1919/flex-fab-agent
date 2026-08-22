# Git 规范

## 红线

- **禁止自动 git**：commit / push / pull 必须用户发起；提交前先列出变更清单待用户确认
- **远程分支查询必须先 fetch**：列出/搜索远程分支前必须先 `git fetch <remote>`，禁止直接用本地缓存 `git branch -r`

## 分支管理

- **生产分支**：`main`
- **分支命名（spec 联动式为主）**：`feature/YYYYMMDD_spec_<规格标识>`，规格标识与文档仓 `02-specs/` 中的规格文档名一致（去日期、去 `-spec` 后缀、全小写）
- **无 spec 杂项兜底**：`chore/<简述>` 或 `fix/<简述>`

命名步骤：找到规格文档 → 去掉文件名末尾日期 → 去掉 `-spec` 后缀 → 全小写 → 拼装 `feature/当天日期_spec_<结果>`。

## 提交规范

### 核心原则：代码与文档同包提交

每一份功能代码必须和它的 spec 规格 + plan 计划放在同一个 commit 中，commit body 引用文档路径——git log 才能追溯需求来源。

### 提交信息格式

```
<type>(<scope>): <subject>

关联规格：<文档仓>/02-specs/<spec>.md
关联计划：<文档仓>/04-plans/<plan>.md（如有）
```

- **type** ∈ `feat|fix|docs|refactor|test|chore|style|perf`（与 `.githooks/commit-msg` 校验一致）
- **scope**：模块标识；**subject**：中文简述
- 纯杂项无 spec 的用 `chore`

### 提交分组

- 一个功能模块 1 个 commit（代码 + spec + plan 一起）
- 一个补丁规格 1 个 commit；独立 bug 修复 1 个 commit（测试 + 修复一起）

## 代码更新规则（强制）

**禁止凭本地状态判断「已是最新」。** 每次更新代码必须：

1. `git fetch origin` — 先拉取所有远程分支引用
2. 检查当前分支是否有远程跟踪分支
3. 如有 → `git log HEAD..origin/<当前分支> --oneline` 逐条比对
4. 同时检查 `origin/main` 是否有新提交
5. **全部确认无新提交后，才能说「已是最新」**

反例（禁止）：`git status -sb` 显示 `[ahead 2]` 就下结论「远程无新代码」。

## 平台

Git 平台：GitHub。hooks 启用：`git config core.hooksPath .githooks`。
