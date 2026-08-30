# 设计：project-standards 模板包 v1.2 启用到 agent-training（demo 第二阶段重构）

| 项 | 值 |
|----|----|
| 日期 | 2026-08-22 |
| 状态 | 已批准（用户确认方案 2 + 6 节设计） |
| 背景 | demo 第二阶段重构（MySQL + 环境模拟器 + OR-Tools CP-SAT + LLM 在环）为多 Phase 大工程，需要 spec -> plan -> todo -> 四门禁全流程；`project-standards/` v1.2 模板包正是该流程的载体 |
| 关联 | [重构方案 v1](../../demo/04-plans/重构方案-v1-2026-08-21.md) · [需求规格 v1](../../demo/02-specs/需求规格-v1-2026-08-21.md) · [模板包 README](../../../project-standards/README.md) |

---

## 0. 决策汇总

| 决策点 | 定案 |
|--------|------|
| 规则落位 | **agent-training 仓库根目录**（方案 2），四门禁全仓生效 |
| 缓解措施 | CLAUDE.md 附加红线：豁免区声明 + 与 workspace 根 CLAUDE.md 冲突时以本仓 rules 为准 |
| 接受的代价 | ① 全仓 commit message 强制 conventional 格式（hook 拦截）；② 与 workspace 根 CLAUDE.md 的四门禁文本叠加，靠消歧声明解决 |
| 技术栈规则 | 新增 `stack-python/`（6 文件），删除 stack-go / stack-vue3 |
| docs 结构 | 单仓变体：`docs/demo/` 内设 5 个编号子目录，现有 5 份文档 git mv 迁入 |
| 模板包回填 | stack-python 复制回 project-standards，版本 v1.2 -> v1.3 |

---

## 1. 落位（agent-training 根目录）

新增文件/目录：

```
agent-training/
├── CLAUDE.md              # 薄入口（占位符已替换 + 附加红线）
├── AGENTS.md              # 薄入口（同步）
├── rules/
│   ├── rules-index.md     # 触发表（追加 stack-python 行）
│   ├── common/            # 10 文件照搬（workflow/testing/git/docs-flow/api-contract/deployment/server-approval/conversation/skill-integration/pitfalls）
│   └── stack-python/      # 新增 6 文件（见 §2）
├── .claude/
│   ├── settings.json      # 权限白名单（模板 .template 去后缀 + 替换）
│   └── hooks/
│       └── guard-hard-interrupt.sh
└── .githooks/
    └── commit-msg         # conventional 格式校验
```

删除：`rules/stack-go/`、`rules/stack-vue3/`（本仓用不到）。

启用动作：`chmod +x .claude/hooks/guard-hard-interrupt.sh .githooks/commit-msg` + `git config core.hooksPath .githooks`。

### 附加红线（写入 CLAUDE.md，模板占位符之外新增）

1. **豁免区**：`job-portfolio/`、`docs/`（demo 子目录除外）为轻量文档区，不走四门禁流程；仅守 commit 格式与敏感信息两条红线。
2. **冲突消歧**：与 workspace 根 CLAUDE.md 冲突时（如并行 Agent 上限 2 vs 3、命令速查），以本仓 `rules/rules-index.md` 及其加载文件为准。

---

## 2. stack-python 规则包（6 文件）

按模板 README「三步追加协议」新建；不硬凑 stack-go 九文件骨架，按 demo 实际裁剪。内容提炼自 demo README 红线、重构方案 v1 约束、token-hub 历史教训。

| 文件 | 核心红线 |
|------|---------|
| `arch.md` | 分层不变式：tools / rag / graph / agents / auth / observability / core 边界不可跨层反向依赖；新工具只经 `ToolRegistry` 注册（自动继承沙箱/RBAC/tracer），禁止散落调用；`tools/data.py` DataSource 抽象是数据层唯一入口（CSV->MySQL 切换只改此层）；`config.py` 是配置唯一来源，禁止散落 `os.getenv` |
| `error.md` | 异常必须向上传播（禁打日志后丢弃）；错误信息用中文、专有名词保留英文；工具返回值统一经 sandbox 三元组 `(result, success, retries)` |
| `logging.md` | 观测走 `observability/tracer.py` span，禁散落 print；鉴权决策必须落 `audit_logger`（JSONL）；新增子系统必须可被 trace_id 贯穿 |
| `database.md` | MySQL 连接经统一连接管理；**tenant_id 过滤强制**（R8，所有业务查询）；种子数据脚本化可重建；schema 变更必须有回滚路径；密钥只在 `.env` / credentials.local.md，代码留占位符 |
| `testing.md` | 测试先行（TDD）；单测 mock LLM 零成本运行；eval 回归基线 ≥7/10（case ≥0.6 为 pass）；`run_all_tests.py` 是 CI 入口，全绿才算过门禁 |
| `ops-build.md` | Python 3.11 锁定（依赖不随意升级）；Docker/前端构建在 **WSL 下执行**（Windows npm/EPERM 教训）；`.env`、`checkpoints.db`、`cache_db/` 不入库；compose 健康检查必须有 |

`rules-index.md` 追加触发行：

| 触发场景 | 加载文件 |
|---------|---------|
| demo 分层 / 工具注册 / 数据源抽象 | -> `stack-python/arch.md` |
| 异常处理 / 工具返回值 | -> `stack-python/error.md` |
| 观测 / 审计 / span | -> `stack-python/logging.md` |
| MySQL / 迁移 / 种子数据 / tenant_id | -> `stack-python/database.md` |
| Python 测试执行 / pytest / mock LLM / eval | -> `stack-python/testing.md` |
| Python 版本 / Docker / WSL 构建 | -> `stack-python/ops-build.md` |

---

## 3. docs 映射（单仓变体）

模板 docs-repo-template 的 13 目录裁剪为实际用到的 5 个，落在 `docs/demo/` 下。现有 5 份文档 **git mv 迁入**（保留历史）：

| 新位置 | 迁入文档（原 `docs/demo/` 下） |
|--------|------------------------------|
| `docs/demo/01-requirements/` | rq-排程排产需求.md |
| `docs/demo/02-specs/` | 需求规格-v1-2026-08-21.md · 排程排产需求规格-v1-2026-08-21.md |
| `docs/demo/04-plans/` | 重构方案-v1-2026-08-21.md |
| `docs/demo/09-reports/` | 盲区报告-JD对标与demo追赶路线-v1-2026-08-21.md · 评测报告-RAG质量-ragas-v1-2026-08-21.md |
| `docs/demo/05-tasklist/` | 新建：todo.md（总索引）+ 活跃任务文件 |

另：`credentials.local.md.example` 复制到 `docs/demo/` 下（真实值文件 gitignore）。

**common 文件路径适配**：`common/` 10 文件内容照搬、条款不改，但其中引用文档仓目录名（如 00-taskregister、05-tasklist）处，落地时统一映射为 `docs/demo/` 下的对应编号目录（待办登记 -> `docs/demo/05-tasklist/`）。映射关系在 `common/docs-flow.md` 头部加一行路径说明，不改条款本身。

迁移后更新引用链接：agent-training `README.md`、`docs/00_文档地图.md`、demo `README.md` 中指向旧路径的链接。

---

## 4. 占位符取值表

| 占位符 | 取值 | 备注 |
|--------|------|------|
| `{{PROJECT_NAME}}` | agent-training-demo | |
| `{{PROJECT_DESC}}` | 制造业排程排产多 Agent 助手（第二阶段重构） | |
| `{{DOCS_REPO}}` | `docs/demo/` | 单仓相对路径 |
| `{{MAIN_BRANCH}}` | main | |
| `{{GIT_PLATFORM}}` | GitHub | remote 为 git@github.com:sjs1919/agent-training.git |
| `{{TEST_CMD}}` | `python run_all_tests.py` | demo 现有 CI 入口 |
| `{{BUILD_CMD}}` | `docker compose build` | 在 WSL 下执行 |
| `{{LINT_CMD}}` | `python -m compileall demo` | 暂无 ruff，语法级兜底 |
| `{{MAX_PARALLEL_AGENTS}}` | 2 | 与 workspace 红线一致 |
| `{{SERVER_ALIAS_1/2/3}}` | token_hub_120 / token_hub_47 / token_hub_172 | 照 workspace 现状 |
| `{{GO_VERSION}}` 等栈类占位符 | 替换为 Python 3.11 语义（ops-build.md） | stack-go 相关占位符随目录删除 |

凭据类占位符（`{{DB_PASSWORD}}` 等）不做全局替换，按项目增删行，仅存在于 credentials.local.md(.example)。

---

## 5. 回填模板包（v1.2 -> v1.3）

`stack-python/` 6 文件同步复制到 `project-standards/code-repo-template/rules/stack-python/`，`rules-index.md` 同步追加触发行，`project-standards/README.md` 变更记录新增：

```
### [1.3] - 2026-08-22
#### Added
- stack-python 技术栈规则包（6 文件）：arch/error/logging/database/testing/ops-build，首个非 Go/Vue3 栈，验证「三步追加协议」可裁剪落地
```

遵守「模板改进只回填模板包」约定；已复制项目（token-hub 等）不受影响，按需对照升级。

---

## 6. 启用自检（四项全过才算启用完成）

1. 让 AI 执行 `git push --force` 样例 -> 确认被 guard hook 拦截（阻断 + 审批提示）
2. 让 AI 跑 `python run_all_tests.py` -> 确认放行、不弹确认窗
3. 提交一条非法格式 message（如 `update stuff`）-> 确认被 commit-msg 拒绝
4. 问 AI「当前项目规则是什么」-> 确认能列出 `rules/rules-index.md` 触发表

---

## 7. 范围外（明确不做）

- 不拆独立仓库（git 历史与训练文档引用保持完整）
- 不给 job-portfolio / 训练文档套四门禁
- 不引入 ruff 等新 lint 工具（`{{LINT_CMD}}` 用 compileall 兜底，后续需要再议）
- demo 代码重构本身（MySQL/模拟器/OR-Tools）不在本设计范围，另走 04-plans 流程
