# Git 规范

## 红线

- **禁止自动 git**：commit / push / pull 必须用户发起；提交前先列出变更清单待用户确认
- **远程分支查询必须先 fetch**：列出/搜索远程分支前必须先 `git fetch <remote>`，禁止直接用本地缓存 `git branch -r`

## 分支分层

三层分支 + 无 spec 兜底：

| 分支 | 用途 | 写入口 |
|------|------|--------|
| `main` | **稳定主线**：需求文档基线 + 已交付代码 | 代码**不直接改**，只经 dev 合入；**需求确认期文档可直接 commit main** |
| `dev` | **集成分支**（长期存在） | feature 完成合入点；联调稳定后一次性合 main |
| `feature/*` | 功能分支 | 从 **dev** 拉，代码在这里写 |
| `chore/*` / `fix/*` | 无 spec 的杂项 / 独立修复 | 可从 main 拉，完成直接合 main |

## 分支命名（spec 联动）

`feature/<规格日期>_spec_<主题英文标识>`

- **规格日期**：关联规格文档文件名中的日期（YYYYMMDD）
- **主题英文标识**：规格主题的简短英文 slug（中文主题翻译成短词）
- 示例：规格 `需求规格-操作日志-v1-20260901.md` → `feature/20260901_spec_operation-log`；规格 `需求规格-多模态运维手册知识库-v1-20260907.md` → `feature/20260907_spec_manual-kb`

## 合流流程

```
feature → 合入 dev → dev 联调稳定 → 合入 main
```

- feature 合 dev 前 rebase 到最新 dev；dev 合 main 前 rebase 到最新 main（旧基线 feature 必须补 rebase，不允许带着陈旧基线合流）。
- feature 合 dev 后删除；dev 长期保留。

## 文档落点（两段分工）

1. **需求确认期文档**（规格定稿 / 设计 / 实施计划 / 待办清单）→ **直接 commit main**。这是评审基线，让各协作者尽早看到最新需求，**不等代码合流**。
2. **代码提交必须关联文档**：
   - 功能引用的 spec/design/plan **已在 main** → commit body 写关联路径（git log 追溯需求来源），**不重复把已入 main 的文档再放 feature**。
   - 功能实现中**新产出**的文档（schema.sql 同步、设计修订、实现笔记）→ **与代码同包 1 个 commit** 进 feature。
   - 总原则：**每次 feature 提交都能从 commit 回溯到对应需求文档**。

## 提交规范

### 核心原则：feature 提交必须关联文档

见「文档落点（两段分工）」：功能新产出的文档与代码同包提交；引用的文档已在 main 则 commit body 写关联路径。**每次 feature 提交都能从 commit 回溯到需求文档**。

### 提交信息格式

```
<type>(<scope>): <subject>

关联规格：<文档仓>/02-specs/<spec>.md
关联设计：<文档仓>/02-specs/<design>.md（如有）
关联计划：<文档仓>/04-plans/<plan>.md（如有）
```

- **type** ∈ `feat|fix|docs|refactor|test|chore|style|perf`（与 `.githooks/commit-msg` 校验一致）
- **scope**：模块标识；**subject**：中文简述
- 纯杂项无 spec 的用 `chore`

### 提交分组

- 一个功能模块 1 个 commit：代码 + **随本功能新产出/修订**的文档（spec/plan 已在 main 的用 body 关联，不重复放）
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
