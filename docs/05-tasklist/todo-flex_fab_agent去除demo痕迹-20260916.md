# todo · flex_fab_agent 去除 demo 痕迹

> 日期：2026-09-16 · 状态：🔄 执行中（M1-M7 完成，M8-M10 进行中）
>
> 关联计划：[2026-09-16-flex_fab_agent去除demo痕迹计划.md](../04-plans/2026-09-16-flex_fab_agent去除demo痕迹计划.md)

## 任务清单

| 阶段 | 模块 | 状态 | commit |
|------|------|------|--------|
| 0 前置 | 建分支 + 基线回归 | ✅ 已完成 | （无） |
| 1 M1 基础设施 | `__init__/main/config/conftest/core/llm_client` | ✅ 已完成 | `a556bfb` |
| 2 M2 业务层 | graph(2a) / tools(2b) / scheduler+simulator+backtest(2c) / api+auth+observability(2d) | ✅ 已完成 | `c6ef57c` `712e45a` `692f57a` `fee1aa0` |
| 3 M3 测试评估 | eval / smoke_test / run_eval_report / test_registry_gov / test_e2e_m3 | ✅ 已完成 | `8980be0` |
| 4 M4 包内 README | `flex_fab_agent/README.md` | ✅ 已完成 | `5d50a4a` |
| 5 M5 根仓库配置 | `.dockerignore`（失效路径修正）/ `requirements-*.txt` | ✅ 已完成 | `a954ff3` |
| 6 M6 规则层 | `rules/rules-index.md` / `rules/stack-python/arch.md` | ✅ 已完成 | `9488fb3` |
| 7 M7 文档仓 | 文档仓子目录上移一层 + 全仓路径同步 + 内文清理 | ✅ 已完成 | `0d74fdd` `1be6017` + 内文清理笔 |
| 8 M8 前端 | `OverviewView.vue` / `DemoCasesView.vue` 路径 + 产品语义清零 | ⏳ 待启动 | `refactor(web): ...` |
| 9 M9 图谱 | 调查脚本 → 能跑就跑 → 跑不动回退跳过 | ⏳ 待启动 | `chore(graphs): ...`（或无） |
| 10 M10 终验 | grep + 三件门禁 + 链接抽检 + 收尾登记 | ⏳ 待启动 | （无） |

## 基线记录

**Stage 0（2026-09-16 WSL · oplog-venv · MySQL 8.4.10）**：**540 passed, 1 skipped, 3 warnings in 1001.96s (16:41)**
- 环境要点：WSL 用 `/root/oplog-venv/bin/python`（Python 3.11，含全部依赖）；MySQL 需每 session 重建 `/var/run/mysqld` 后 `mysqld_safe` 起。
- 3 warning 全是 deprecation（`on_event`/`pkg_resources`），非 ERROR。

**M1 后复测**：540 passed / 1 skipped / 3 warnings ✅ 与基线一致。

## 已知遗留（待 M10 或专项处理）

| 项 | 说明 | 归属 |
|----|------|------|
| `tools/test_data.py::test_load_orders_all` | 断言 15，实际 MySQL 返回 20（seed 后行数变化）；与 demo 改名无关的既有 fixture 漂移 | M10 终验复核 |
| `test_config.py::test_get_data_source_default_csv` | 断言 csv，但 `.env` 实为 mysql；单跑必失败，全量跑因 `scheduler/test_model_pack.py` 直接改 `os.environ`（非 monkeypatch）泄漏成 csv 才「通过」。**测试隔离漏洞**，基线 540 passed 属顺序依赖 | 专项修复（非本次范围） |
| `graphs/viewers/*.html` 等图谱产物 | 583+ 处旧前缀引用，属生成物 | M9 重生成 |
| 指向旧仓的绝对 URL | `github.com/sjs1919/agent-training/blob/main/...` 形式，仓库拆分后已失效 | 独立开源计划「失效链接清理」另案 |
| 生成物目录 | `.understand-anything/`、`graphs/understand-anything/`、`web/dist/`、`.codegraph/` 均 untracked 或 gitignored | 不处理 |
| skip-worktree 文件 | `OverviewView.vue`、`PortalView.vue`（本地隐藏首页的刻意设置），改动 git 不可见 | M8 定夺是否解除 |

## 拍板记录（5 疑问）

- ✅ Q1 文档仓子目录上移一层（去除中间层）+ 内文清理
- ✅ Q2 项目名形参（下划线版 `flex_fab_agent`）
- ✅ Q3 产品语义全部清零
- ✅ Q4 保留 `demo-*` 文件名前缀（git blame 可读性优先）
- ✅ Q5 尝试重生成图谱（找不到脚本回退跳过）

## 追加拍板

- ✅ CLI `--demo` → `--scenario`（M1 执行时确认）
- ✅ 后续阶段自动 commit 授权，push 由用户手动发起（2026-09-16）
- ✅ 迁移自指文档改写为「已完成记述」（M7 执行时确认）

## 启动决策

- 分支：`feature/20260916_clean_demo-traces`
- 顺序：1 → 6 默认顺序（M1 → M6 已按序完成）
- 起点：阶段 0（建分支 + 基线回归）

## 变更记录

| 日期 | 变更 |
|------|------|
| 2026-09-16 | 初稿：阶段 0 启动中 |
| 2026-09-16 | 阶段 0 完成：基线 540 passed（起 MySQL 后）；M1-M6 完成，各阶段独立 commit |
| 2026-09-16 | 追加拍板：CLI `--demo` → `--scenario`；自动 commit 授权；自指文档改写为已完成记述 |
| 2026-09-16 | M7 完成：91 文件迁移 + 36 文件 115 处引用同步 + 36 处内文功能性修正；新建已知遗留登记（含测试隔离漏洞） |
