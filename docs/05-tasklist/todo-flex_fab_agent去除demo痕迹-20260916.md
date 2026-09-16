# todo · flex_fab_agent 去除 demo 痕迹

> 日期：2026-09-16 · 状态：✅ 执行完成（M0-M10 全部收口，待用户 push）
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
| 8 M8 前端 | `OverviewView.vue` / `DemoCasesView.vue` / `DebugView.vue` 路径 + 产品语义清零 | ✅ 已完成 | `24f4e02` |
| 9 M9 图谱 | 调查脚本 → 不可用 → 路径引用同步（非重生成） | ✅ 已完成 | `8329a36` `c4247a2` |
| 10 M10 终验 | grep + 三件门禁 + 链接抽检 + 收尾登记 | ✅ 已完成 | （无）+ 补漏两笔 |

## 基线记录

**Stage 0（2026-09-16 WSL · oplog-venv · MySQL 8.4.10）**：**540 passed, 1 skipped, 3 warnings in 1001.96s (16:41)**
- 环境要点：WSL 用 `/root/oplog-venv/bin/python`（Python 3.11，含全部依赖）；MySQL 需每 session 重建 `/var/run/mysqld` 后 `mysqld_safe` 起。
- 3 warning 全是 deprecation（`on_event`/`pkg_resources`），非 ERROR。

**M1 后复测**：540 passed / 1 skipped / 3 warnings ✅ 与基线一致。

## M10 终验记录

**三件门禁**（2026-09-16）
| 门禁 | 结果 |
|------|------|
| `run_all_tests.py` 全量单测 | ✅ 540 passed / 1 skipped / 3 warnings in 974.49s——与 Stage 0 基线（1001.96s）、M1 后复测三方一致 |
| `cd web && npm run build` | ✅ vue-tsc 类型检查 + vite build 通过（2239 模块，1m7s） |
| `compileall` 静态检查 | ✅ 各阶段改动文件均 0 error |

**链接抽检**（脚本 `tmp/linkcheck.py`，覆盖 docs/ 全部 .md）：相对链接 **183 通 / 0 断**（修掉 2 处迁移前既有失效链接后）。

**终验 grep 结果**（排除生成物目录）
- `git ls-files` 口径：全仓仅剩 **9 处**，全部为已记录类别——`DemoCasesView` 组件标识 7 处（3 文件）+ Q4 保护的训练仓文件名引用 1 处 + 指向旧仓的绝对 URL 1 处。
- 含生成物口径：159 处 = 旧仓绝对 URL 26 + 豁免归档文档 125 + `.env`（gitignored）1 + 本计划/todo 自身主题表述。

**终验暴露的扫描盲区（已补）**
早前各阶段扫描只覆盖 `*.py` 且大小写敏感，漏掉 `.sh` / `.sql` / `.ini` / `.example` 及大写 `Demo`。终验补漏并单独 commit：
- 脚本改名 `flex_fab_agent/test_demo.sh` → `test_flex_fab_agent.sh`（M3 计划项，此前遗漏）
- `smoke_test.sh` / `pytest.ini` / `schema.sql` 顶部注释
- `tools/order_tools.py`、`tools/mcp_servers.py` 的 `Demo` 措辞
- `docs/credentials.local.md.example` 失效冒烟路径

## 已知遗留

| 项 | 说明 | 处置 |
|----|------|------|
| `flex_fab_agent/data/graph/{call_graph.json,module_graph.dot}` | **本次唯一未清理的 `demo` 集中地**：1473 + 66 处。二者是 2026-08-05 生成的旧图谱，节点名用的还是包名 `demo`；`codegraph analyze`（文档记载的生成命令）在当前 codegraph CLI v1.5.0 已不存在，**无法重生成**；计划 Q5 已预批 `--exclude-dir=data/graph` | 保留（Q5 回退）；如需清除建议整文件删除而非改字符串（内容描述的是旧结构，改名会误导） |
| `graphs/viewers/*.html` 中 19 处裸 `demo` | 图谱生成时对源码/文档名的引用快照（如 `FastAPI(title="demo 排产助手 API")` 原文、历史文档名） | 保留（改写=伪造快照时点）；结构性路径引用已同步 |
| `tools/test_data.py::test_load_orders_all` | 断言 15，实际 MySQL 返回 20（seed 后行数变化）；与 demo 改名无关的既有 fixture 漂移 | 待专项修复 |
| `test_config.py::test_get_data_source_default_csv` | 断言 csv，但 `.env` 实为 mysql；单跑必失败，全量跑因 `scheduler/test_model_pack.py` 直接改 `os.environ`（非 monkeypatch）泄漏成 csv 才「通过」。**测试隔离漏洞**，基线 540 passed 属顺序依赖 | 待专项修复 |
| 指向旧仓的绝对 URL（26 处） | `github.com/sjs1919/agent-training/blob/main/...` 形式，仓库拆分后已失效 | 独立开源计划「失效链接清理」另案 |
| `graphs/README.md` 的重生成指引 | 指向 `tmp/flex-fab-agent-graphs/{codegraph_export,build_viewers}.py`，两脚本已随 tmp 清理丢失 | 待补脚本或更新文档 |
| 生成物目录 | `.understand-anything/`、`graphs/understand-anything/knowledge-graph.json`、`web/dist/`、`.codegraph/` 均 untracked 或 gitignored | 不处理 |
| skip-worktree 文件 | `OverviewView.vue` 已解除（本地差异仅为本次改动）；`PortalView.vue` **保持 skip-worktree**（本地隐藏首页的刻意设置，不入库） | PortalView 按 260831 决策维持原状 |
| `DemoCasesView` 组件标识（7 处 / 3 文件） | 按 M8 拍板**不重命名组件文件**——PortalView.vue 本地隐藏首页且不入库，改名会使远端 PortalView 引用断链 | 保留（已拍板） |

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
