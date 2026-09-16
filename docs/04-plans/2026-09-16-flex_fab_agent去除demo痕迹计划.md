# flex_fab_agent 去除 demo 痕迹计划 v1.0

> 日期：2026-09-16 · 状态：✅ **执行完成（M0-M10 全部收口）**
>
> 用户原话（2026-09-16）：「把文件夹上的demo 去除，子文件夹向上迁移一层；文件内、代码内以及代码的注释，都需要把demo更名为项目名flex_fab_agent。」
>
> v1.0 关键：5 范围边界疑问 Q1-Q5 已逐项 ✅ 拍板；阶段切分定稿；待用户拍板启动阶段 0（建分支 + 基线回归）。
>
> 关联：[todo-flex-fab-agent独立开源评估与计划-20260830.md](../05-tasklist/todo-flex-fab-agent独立开源评估与计划-20260830.md) §4.4 命名统一

---

## 一、目标

把 `flex_fab_agent` 仓库内所有 `demo` 字样清理干净——**目录路径、文件名、代码、注释、文档**全部统一为 `flex_fab_agent`（代码/Python 语境）/ `flex-fab-agent`（仓库/前端/正文语境）。

**完成定义**：`grep -rE "\bdemo\b" projects/flex-fab-agent/ --exclude-dir=graphs --exclude-dir=data/graph --exclude-dir=.git` 结果中**仅剩产品语义词**（按 Q3 拍板结果**全部清零**——但 git 历史归档文件名按 Q4 保留 demo-* 前缀）。

---

## 二、范围边界（5 疑问逐项拍板完毕）

### ✅ Q1 范围边界 — **已拍板**
- **2026-09-16 用户拍板**：文档仓子目录整体上移一层（去除中间层）+ 内文清理（与「子文件夹向上迁移一层」原话完全吻合）
- 含义：阶段 7 全量进入（路径迁移 + 全仓引用同步 + 文档内文 demo 清理）；前端 OverviewView.vue、DemoCasesView.vue 中指向文档仓的旧前缀引用同步改

### ✅ Q2 项目名形参（已隐含确认，无需追问）
**"项目名flex_fab_agent"指下划线版**——用于 Python import、模块字符串、注释、docstring、CLI 内部、文档正文标题；仓库根目录名 `flex-fab-agent/`（连字符）保持不动；前端 URL `/flex-fab-agent/`（连字符）保持不动。

### ✅ Q3 产品语义词豁免 — **已拍板**
- **2026-09-16 用户拍板**：**全部清零（按字面）**——按"代码内 demo 都改"原话严格解释
- 影响清单（阶段 1 + 阶段 8）：
  - `flex_fab_agent/main.py` `--demo` 参数 → 改名（候选 `--preset` / `--scenarios`，**执行阶段 1 时再定**）
  - `mode = "demo"` → 同步改名
  - `web/src/views/DemoCasesView.vue` 组件名 → 改名（候选 `PresetCasesView.vue`）
  - `.demo-entry`、`.demo-entry-text`、`.demo-steps`、`.demo-step` CSS class → 全部改
  - "现场 15 分钟演示脚本"、"演示前建议" 文案 → 改写
  - 同步影响：CLI 帮助文本、README 用法表、router 配置、前端 CSS class 引用点、flex_fab_agent/README.md:118/162 等位置
- 风险提示：CLI 参数改名破坏用户现有调用脚本；如有外部脚本调用需同步迁移

### ✅ Q4 归档文件名 demo-* 前缀 — **已拍板**
- **2026-09-16 用户拍板**：**保留 demo-* 前缀**（历史归历史，git blame 可读性优先）
- 影响：阶段 7.4 跳过文件改名（仍做内文 demo 清理）；新建文档统一用 `flex-fab-agent-` 前缀
- 当前文档文件名含 demo 的（如 `2026-08-22-模板包启用demo重构-design.md`）按归档对待，不改文件名

### ✅ Q5 图谱 JSON 产物 — **已拍板**
- **2026-09-16 用户拍板**：**尝试重生成**——先找项目内是否有图谱生成脚本（如 `build_graph.py` / `make_callgraph.sh`），能跑就跑一遍重生；找不到则回退到跳过（grep 时 `--exclude-dir=graphs --exclude-dir=data/graph` 排除）
- 含义：阶段 9 改为"先调查脚本 → 能跑就跑 → 不能跑就跳过"

---

## 三、模块清单一览（10 阶段对应 10 个模块组）

| 模块组 | 涉及路径 | demo 字样密度 | 关键文件举例 |
|--------|----------|--------------|--------------|
| **M0 前置** | （分支 + 基线） | — | `run_all_tests.py`、web build |
| **M1 基础设施** | `flex_fab_agent/{config.py,main.py,__init__.py,conftest.py,pytest.ini}` + `flex_fab_agent/core/llm_client.py` | 16 处 | `main.py`（CLI `--demo` **按 Q3 改名**）、`__init__.py:1` |
| **M2 业务模块** | `flex_fab_agent/{agents,graph,prompts,tools,rag,data,scheduler,simulator,forecast,backtest,api.py,schema,cache,auth,guardrails,observability}` | ~25 处 | `scheduler/verify.py`、`api.py`、`tools/mcp_client.py`、`tools/sandbox.py` |
| **M3 测试与评估** | `flex_fab_agent/{test_*.py,test_*.sh,smoke_test.py,smoke_test.sh,test_demo.sh,run_all_tests.py,run_eval_report.py,eval}` | ~12 处 | `smoke_test.py:5`、`test_demo.sh`（脚本改名） |
| **M4 包内文档** | `flex_fab_agent/README.md` | **27 处（最高密度）** | 标题 `# demo -- 制造业排产智能体（v3.0 · 2026-08-30）` |
| **M5 根仓库配置** | 根 `{README.md,CLAUDE.md,.env.example,.dockerignore,docker-compose.yml,requirements-flex-fab-agent.txt}` | 11 处 | `.dockerignore:4`、CLAUDE.md |
| **M6 规则层** | `rules/{common,stack-python,*/}` + `rules/rules-index.md` | ~13 处 | `rules/common/pitfalls.md:5` |
| **M7 文档仓** | 文档仓子目录上移一层（去除中间层） | 跨 36 文件旧前缀引用 | 八个子目录、credentials.local.md.example |
| **M8 前端** | `web/src/` | OverviewView.vue:5、DemoCasesView.vue:6 | 路径引用 + **产品语义全部清零（Q3）** |
| **M9 图谱产物** | `flex_fab_agent/data/graph/` + `graphs/` | call_graph.json:1472、graphs/*.json 数百处 | **先调查脚本 → 能跑就跑 → 不能跑回退跳过（Q5）** |
| **M10 终验** | 全仓 | — | grep + 三件门禁 |

---

## 四、执行阶段（按模块切分 10 阶段 + 前置 1 阶段）

### 阶段 0：前置准备（基础设施）
- **动作**：
  1. 用户拍板后建分支 `feature/20260916_clean_demo-traces`（基于当前 `master` 干净树）
  2. 基线三件门禁：`python run_all_tests.py` + `cd web && npm run build` + `python -m compileall flex_fab_agent` 全部绿灯，记基线耗时
- **commit**：（无，纯准备）
- **验证**：三件门禁绿灯 + 基线耗时记录

---

### 阶段 1：M1 基础设施层清理
- **模块**：`flex_fab_agent/config.py`、`flex_fab_agent/main.py`、`flex_fab_agent/__init__.py`、`flex_fab_agent/conftest.py`、`flex_fab_agent/pytest.ini`、`flex_fab_agent/core/llm_client.py`
- **demo 字样定位**（已知）：
  - `__init__.py:1` — `"""demo -- week1-4 整合..."""` → 改 docstring
  - `main.py:7` — `--demo` 参数、`mode = "demo"`、`"""demo 统一入口"""`（**按 Q3 全部清零**——CLI 参数改名需先定新名字）
  - `main.py:8` — `python -m flex_fab_agent.main --demo`（注释示例，按 Q3）
  - `main.py:127` — `用法：python -m flex_fab_agent.main "你的问题"  或  --chat  或  --demo  或  --check`（用法说明，按 Q3）
  - `config.py:3` — 注释含 demo（读上下文定）
  - `conftest.py:3` — 含 demo（读上下文定）
  - `core/llm_client.py:1` — 含 demo（读上下文定）
- **commit**：`refactor(flex_fab_agent): 清理基础设施层 demo 字样（CLI --demo 改名 + 入口字符串）`
- **验证**：`python -m compileall flex_fab_agent` + `python run_all_tests.py`
- **子决策（执行阶段时拍板）**：CLI 参数 `--demo` 新名字（候选 `--preset` / `--scenarios` / 其他）

---

### 阶段 2：M2 业务模块层清理（四个子阶段）
- **2a 子智能体编排**：`agents/`、`graph/`、`prompts/`
  - `agents/router.py`、`agents/{single_agent,supervisor,production_agent,review_agent}.py`
  - `graph/{state,single_agent_graph,context_compressor,checkpointer}.py`
  - `prompts/system_prompts.py`
- **2b 工具与检索**：`tools/`、`rag/`、`data/`
  - `tools/{registry,order_tools,resource_tools,data,mcp_client,mcp_servers,sandbox}.py`
  - `rag/{retriever,knowledge_base}.py`
  - `data/`（除 graph/ 子目录）
- **2c 排产与模拟**：`scheduler/`、`simulator/`、`forecast/`、`backtest/`
  - `scheduler/{solver,auto_scheduler,verify,snapshot}.py`
  - `simulator/{simulator,seed}.py`
  - `forecast/`、`backtest/scenarios.py`
- **2d 服务与基础设施**：`api.py`、`schema/`、`cache/`、`auth/`、`guardrails/`、`observability/`
  - `api.py:3`、`schema/migrate.py`、`cache/*`、`auth/{guard,mint,quota,audit_logger}.py`、`guardrails/`、`observability/{exporter,case_collector}.py`
- **commit 模板**（可拆 4 个）：
  - `refactor(flex_fab_agent): 清理智能体编排层 demo 字样（2a）`
  - `refactor(flex_fab_agent): 清理工具与检索层 demo 字样（2b）`
  - `refactor(flex_fab_agent): 清理排产与模拟层 demo 字样（2c）`
  - `refactor(flex_fab_agent): 清理服务基础设施层 demo 字样（2d）`
- **验证**：每个子阶段后 `compileall` + `run_all_tests.py`

---

### 阶段 3：M3 测试与评估层清理
- **模块**：`flex_fab_agent/{test_*.py,test_*.sh,smoke_test.py,smoke_test.sh,test_demo.sh,run_all_tests.py,run_eval_report.py,eval/}`
- **demo 字样定位**（已知）：
  - `smoke_test.py:5` — docstring / `argparse description` / `print` 标题 / **第 221 行 `AGENT_TRAINING_ROOT / "demo" / "data"`（关键：上游路径引用，需澄清是否在范围）**
  - `test_demo.sh` — 脚本名（改名为 `test_smoke.sh` 或类似）
  - `smoke_test.sh:1`、`run_all_tests.py`（已部分改，按 9b62c29 提交）
  - `eval/{judge,ragas_regression,test_smoke}.py`
  - `test_*.py` 系列（test_api_*/test_e2e_*/test_*）
- **commit**：`refactor(flex_fab_agent): 清理测试与评估层 demo 字样 + test_demo.sh 改名`
- **验证**：`run_all_tests.py` 全绿 + `python flex_fab_agent/smoke_test.py --skip-llm` 全过 + 冒烟脚本改名后调用一致
- **风险**：test_demo.sh 改名涉及 shell 调用点（如果有文档/脚本引用旧名）；AGENT_TRAINING_ROOT 路径若指向别仓的 demo/，可能不动

---

### 阶段 4：M4 包内文档重写
- **模块**：`flex_fab_agent/README.md`（**27 处 demo，最高密度**）
- **动作**：
  - 整篇重写标题 `# demo -- 制造业排产智能体（v3.0 · 2026-08-30）` → `# flex_fab_agent · 制造业 3D 打印智能排产系统`
  - 11 处"这个 demo 能做什么"等正文段落统一改写
  - 6 处指向文档仓的旧前缀引用（按 Q1 同步改）
  - 第 162 行 `--demo` 用法表（按 Q3 全部清零）
  - 第 681-704 行需求文档链接清单
- **commit**：`docs(flex_fab_agent): 包内 README 重写去除 demo 字样`
- **验证**：人工抽检 5 处引用 + `python -m mkdocs build`（如有）+ grep

---

### 阶段 5：M5 根仓库配置清理
- **模块**：根 `{README.md, CLAUDE.md, .env.example, .dockerignore, docker-compose.yml, requirements-flex-fab-agent.txt}`
- **demo 字样定位**（已知）：
  - `README.md:1` — 仓库根 README 含 demo 1 处
  - `CLAUDE.md:3` — 项目规范含 demo 3 处（指向文档仓的旧前缀 → 按 Q1 同步改）
  - `.env.example:1` — 环境变量模板
  - `.dockerignore:4` — 路径忽略
  - `docker-compose.yml:1` — 容器配置
  - `requirements-flex-fab-agent.txt:1` — 依赖注释
- **commit**：`chore(repo): 清理根仓库配置 demo 字样`
- **验证**：`docker compose config` + `.env.example` 占位符检查 + grep

---

### 阶段 6：M6 规则层清理
- **模块**：`rules/common/{docs-flow,pitfalls,llm-agent}.md`、`rules/stack-python/{database,arch}.md`、`rules/rules-index.md`
- **demo 字样定位**（已知）：
  - `rules/common/pitfalls.md:5`（最高密度）
  - `rules/common/llm-agent.md:3`
  - `rules/common/docs-flow.md:2`
  - `rules/rules-index.md:1`
  - `rules/stack-python/database.md:1`、`rules/stack-python/arch.md:1`
- **动作**：清理 demo 文本 + 按 Q1 同步改指向文档仓的旧前缀引用
- **commit**：`docs(rule): 清理规则层 demo 字样`
- **验证**：人工抽检 + grep

---

### 阶段 7：M7 文档仓清理（✅ 已完成）

#### 7.1 路径迁移 ✅
- **结果**：文档仓 8 个编号子目录已从原 `demo/` 层整体上移一层，直达 `docs/` 根；`credentials.local.md.example` 同步上移，`credentials.local.md`（gitignored，含真实口令）以普通 mv 同步迁移（迁移前已备份至 `tmp/backup-m7/`）
- **手法**：逐目录 `git mv`，共 91 个 tracked 文件全部以 rename 记录（内容零改动，`git log --follow` 可追溯）
- **commit**：`refactor(docs): docs/demo/ 八子目录向上迁移一层`

#### 7.2 全仓路径引用同步 ✅
- **结果**：36 个文件共 115 处旧文档仓前缀引用已同步为新前缀（CLAUDE.md、README、.env.example、docker-compose.yml、rules 4 文件、`flex_fab_agent/` 3 文件、docs 内文 28 文件）
- **关键修复**：`flex_fab_agent/config.py` 的凭据路径是分片字符串拼接，不匹配字面替换；若漏改会导致迁移后凭据**静默加载失败**（已实测新路径解析出 14 个 key）
- **顺手修既有 bug**：早期全局改名把 CLI `--demo` 误替为 `--flex_fab_agent`，3 处改正为 `--scenario`
- **commit**：`refactor(docs): 同步全仓 docs/demo 路径引用`

#### 7.3 文档仓内文清理 ✅
- **结果**：36 处功能性引用修正——容器名 `demo-api` → `flex-fab-agent-api`、卷名 `demo-runtime` → `flex-fab-agent-runtime`、CLI `--demo` → `--scenario`、测试函数名与 MCP client 标识同步；另修 6 处叙述性表述（「单机 demo 无登录」→「单机部署无登录」、「训练 Demo」→ 项目名等）
- **commit**：`docs: 清理文档仓内文 demo 字样`

#### 7.4 文件名清理 — Q4 拍板跳过
- 按 Q4 决定：保留归档文件名 `demo-*` 前缀不变（git blame 可读性优先）
- 仍做：新建文档统一用 `flex-fab-agent-` 前缀

#### 7.5 保留项（记录在案，非漏改）
| 类别 | 说明 |
|------|------|
| 历史迁移叙述 | 2026-08-22 模板包重构 plan/design、2026-08-30 独立开源计划、2 份同期 todo——其中的旧前缀是被叙述的历史事实，改写即伪造历史（比照 Q4） |
| 指向旧仓的绝对 URL | `github.com/sjs1919/agent-training/blob/main/...` 形式，仓库拆分后已失效；属独立开源计划「失效链接清理」，另案处理 |
| 训练仓文档名引用 | `7周路线-vs-demo-差距全景图.md` 等未随本库迁移的文件名（Q4 保留前缀） |
| 生成物 | `graphs/` 图谱产物留 M9；`web/dist/`、`.env`、`.codegraph/` 不入库 |
| skip-worktree 文件 | `OverviewView.vue`、`PortalView.vue` 为本地刻意设置（隐藏首页），其改动 git 不可见，留 M8 定夺 |
| 本计划的 commit message 原文（7.1/7.2 两行） | 必须与实际 git 历史逐字一致，改写即失真 |

> 另注：本文件自身是「去除 demo 痕迹」这一主题的规格书，正文中「demo 字样/demo 清理」等表述是文档主题本身所需，非待清理对象。

---

### 阶段 8：M8 前端清理（**Q3 已拍板：产品语义全部清零**）
- **模块**：`web/src/views/OverviewView.vue`、`web/src/views/DemoCasesView.vue`
- **demo 字样定位**（已知）：
  - `OverviewView.vue:3` — 指向文档仓 02-specs 的旧前缀引用（**改**）
  - `OverviewView.vue:136/137/406/416` — `.demo-entry`、`.demo-entry-text` CSS class + "现场 15 分钟演示脚本" 文案（**Q3 全部清零**）
  - `DemoCasesView.vue:6` — 指向文档仓 08-test 的旧前缀引用（**改**）
  - `DemoCasesView.vue:180/181/240/246` — `.demo-steps`、`.demo-step` CSS class（**Q3 全部清零**）
  - `DemoCasesView.vue:203` — "演示前建议" 文案（**Q3 全部清零**）
  - `DemoCasesView.vue` 组件名本身（**Q3 全部清零**——需在 router/web 同步改）
- **commit**：`refactor(web): 前端 demo 路径引用修正 + 产品语义全部清零（CSS class + 组件名 + 文案）`
- **验证**：`cd web && npm run build` + 演示 tab 联调（手动验证）
- **风险**：组件改名涉及 router 配置、CSS class 涉及全局样式引用
- **子决策（执行阶段时拍板）**：`DemoCasesView` 新组件名（候选 `PresetCasesView` / `ScenariosView` / 其他）

#### ✅ 执行结果（2026-09-16）
- **CSS 类全部清零**：`.demo-entry`/`.demo-entry-text` → `.script-entry`/`.script-entry-text`；`.demo-steps`/`.demo-step` → `.script-steps`/`.script-step`
- **变量/函数名**：`demoSteps` → `scriptSteps`；`goDemo` → `goManual`
- **文案**：「现场 15 分钟演示脚本」→「现场 15 分钟操作手册」、「演示前建议」→「使用前建议」、「15 分钟演示主线」→「15 分钟操作主线」、「查看演示脚本」→「查看操作手册」
- **额外发现并处理**：`OverviewView.vue` 与 `PortalView.vue` 处于 **skip-worktree**（2026-08-31 部署时「本地隐藏首页」的刻意设置）。
  - 解除 `OverviewView.vue` 的 skip-worktree 并提交其清理（其本地差异仅为本次改动，无隐藏首页内容）
  - **不重命名 `DemoCasesView.vue`**：`PortalView.vue` 本地隐藏首页且不入库，改名会使远端 `PortalView` 引用断链 → 组件标识 7 处保留
  - `PortalView.vue` 维持 skip-worktree 原状
- **验证**：`npm run build` 通过（vue-tsc + vite，2239 模块）

---

### 阶段 9：M9 图谱产物（**Q5 已拍板：先调查脚本**）
- **模块**：`flex_fab_agent/data/graph/call_graph.json`、`graphs/{understand-anything,vibegraph,codegraph}/*.json`
- **动作**：
  1. **调查**：grep 项目内是否有图谱生成脚本（`build_graph.py` / `make_callgraph.sh` / `codegraph.sh` / 等），或 `pyproject.toml` / `package.json` 中是否有 `build:graph` 之类命令
  2. **跑**：若找到，先 dry-run 验证，再正式跑重生成两个目录产物
  3. **跳过**：若找不到，阶段 9 标 ⚠️ 跳过；终验 grep 时 `--exclude-dir=graphs --exclude-dir=data/graph` 排除
- **commit**：`chore(graphs): 重生图谱产物（去除 demo 节点 metadata）`（若成功）；否则无 commit
- **验证**：图谱 UI 仍可访问 + 节点数无大幅变化

#### ✅ 执行结果（2026-09-16）
**调查结论：无法重生成。**
- `tmp/flex-fab-agent-graphs/codegraph_export.py`（`graphs/README.md` 记载的导出脚本）与 `build_viewers.py` 已随 tmp 清理**丢失**
- `docs/11-manuals/代码阅读指南.md:1357` 记载的 `codegraph analyze` 子命令在当前 codegraph CLI **v1.5.0 已不存在**（现有：init/index/sync/query/... 无 analyze）
- VibeGraph / understand-anything 需各自仓库或插件流水线，且其大数据产物按 `graphs/.gitignore` 本就不入库

**实际动作**（与 M7.2 同性质的路径引用同步，非重生成）：
- `graphs/` 入库产物：585 处旧文档仓前缀同步（`claude-knowledge-graph.md` 1、`viewers/codegraph.html` 2、`viewers/understand-anything.html` 583）+ 1 处无斜杠变体；内嵌 JSON 替换后校验可解析
- 节点名同步至 M3/M8 改名后的新标识 19 处（测试函数名、脚本名、`goDemo`/`demoSteps`）
- **保留**：19 处生成时对源码/文档名的引用快照，以及 `DemoCasesView` 相关节点

**`flex_fab_agent/data/graph/` 处置**：`{call_graph.json,module_graph.dot}`（1473 + 66 处）——2026-08-05 生成的旧图谱，节点名用的还是旧包名，无法重生成。**2026-09-16 用户指示整文件删除**，已执行（用户将另行用对应图谱工具重新生成）。

---

### 阶段 10：M10 终验
- **动作**：
  1. `grep -rE "\bdemo\b" projects/flex-fab-agent/ --exclude-dir=graphs --exclude-dir=data/graph --exclude-dir=.git` —— 仅可能剩 `test_demo.sh` 调用点（已改名）或 git 历史归档文件名 demo-*（按 Q4 保留）
  2. 三件门禁：`run_all_tests.py` + `npm run build` + `compileall`
  3. 关键链接抽检：README.md、flex_fab_agent/README.md、docs/ 文档清单 5 条
  4. 全量 diff 统计：跨多少文件、改动行数
- **commit**：（无，纯验证）+ 用户确认后整体合并到 `master`（或保留 feature 分支待开源准备时合并）
- **签署**：在 docs/05-tasklist 写 todo 收尾登记

#### ✅ 执行结果（2026-09-16）
- **三件门禁**：`run_all_tests.py` 540 passed / 1 skipped（与 Stage 0 基线一致）· `npm run build` 通过 · `compileall` 0 error
- **链接抽检**：docs/ 全部 .md 相对链接 183 通 / 0 断
- **终验 grep**：排除计划预批的生成物目录后，`git ls-files` 口径仅剩 9 处，全部为已记录类别
- **补漏两笔**（终验暴露的扫描盲区）：早前各阶段只扫 `*.py` 且大小写敏感，漏掉 `.sh`/`.sql`/`.ini`/`.example` 与大写 `Demo`；补漏含 `test_demo.sh` → `test_flex_fab_agent.sh` 改名（M3 计划项此前遗漏）
- **遗留清单**：见 todo「已知遗留」表

---

## 五、阶段依赖图（5 疑问已拍板，无阻塞）

```
阶段 0（前置）
   │
   ├─→ 阶段 1（M1 基础设施）──┐
   ├─→ 阶段 2（M2 业务 2a/b/c/d）─┤
   ├─→ 阶段 3（M3 测试评估）────┤
   ├─→ 阶段 4（M4 包内 README）──┤
   ├─→ 阶段 5（M5 根仓库配置）──┤
   ├─→ 阶段 6（M6 规则层）──────┤
   │                              │
   │   阶段 7（M7 文档仓）─────────┤  ← Q1 ✅ 已解锁
   │   阶段 8（M8 前端）──────────┤  ← Q3 ✅ 已解锁
   │   阶段 9（M9 图谱）──────────┤  ← Q5 ✅ 已解锁
   │                              ↓
   └──────────────────────→ 阶段 10（终验）
```

阶段 1-6 **互不依赖**（不同模块），可并行思路；阶段 7-9 已解锁；阶段 10 收口。

---

## 六、git 红线与提交策略

- 🚫 **禁止自动 commit / push** —— 每阶段完成后展示 diff，等用户拍板才提交
- 每个阶段一个 commit（除阶段 2 可拆 4 个）
- 提交信息模板 `<type>(<scope>): <description>`（commitlint 规范）
- 工作分支：`feature/20260916_clean_demo-traces`，完成后按 [project-flex-fab-agent-manual-kb-260907] 约定的「dev 合入 main」流程
- 提交前门禁：`python run_all_tests.py` + `cd web && npm run build` + `python -m compileall flex_fab_agent` 三件全绿
- **执行流程**：改 → grep 验证本阶段 → 跑三件门禁 → 展示 diff → **等用户确认才 git add + commit**

---

## 七、风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 文档仓旧前缀引用改动面广（36 文件） | 漏改某处链接死链 | 阶段 7.2 完成后 grep 全文验证 + 抽检关键链接 |
| `test_demo.sh` 改名 | 文档/调用点失效 | 阶段 3 前 grep 找全调用点 |
| 阶段 2 业务模块 demo 字样上下文复杂 | 误改产品语义/注释 | 每子阶段 grep 上下文 + 用户拍板改动后再 commit |
| `smoke_test.py:221` 行 `AGENT_TRAINING_ROOT / "demo" / "data"` 上游路径 | 不在本仓 | 阶段 3 评估是否动；可能属于训练仓跨引用，不在范围 |
| 阶段切分不当导致中间状态不一致 | 编译/测试红灯 | 每阶段独立 commit + 立即全量回归 |
| 中文路径 demo 残留漏扫 | 部分归档漏改 | 全量 grep 时加 `-i` + 中文路径单独检查 |
| M8 前端组件 / CSS class 改名跨文件引用 | 全局样式/导航失效 | 阶段 8 前 grep 全仓找引用点 + 改名同步改 |
| M9 图谱重生成失败 | 阶段 9 跳过后仍含 demo 文本 | 标记 ⚠️ 跳过；终验 grep 排除；后续单独处理 |

---

## 八、验收清单（最终）

- [x] `grep -rE "\bdemo\b" ... --exclude-dir=graphs --exclude-dir=data/graph` 仅剩 Q4 保留的归档文件名与已记录豁免项 ✅（`git ls-files` 口径 9 处，见 todo 遗留表）
- [x] `python run_all_tests.py` 全绿（与基线耗时相当 ±20%）✅ 540 passed / 1 skipped（基线 1001.96s，终验 974.49s，-2.7%）
- [x] `cd web && npm run build` 通过 ✅
- [x] `python -m compileall flex_fab_agent` 通过 ✅
- [x] 全仓旧文档仓前缀 grep 零命中 ✅（豁免清单见阶段 7.5，Q1 已确认执行）
- [x] 仓库根 README + flex_fab_agent/README.md + CLAUDE.md + rules/ 全无 demo 字样 ✅（仅剩 Q4 保护的训练仓文件名引用 1 处）
- [x] 前端 OverviewView / DemoCasesView 路径引用全部修正 + 产品语义 demo 全清零 ✅（`DemoCasesView` 组件标识按 M8 拍板保留）
- [x] 关键链接抽检转正为全量脚本 `tmp/linkcheck.py`：docs/ 相对链接 183 通 / 0 断 ✅（超出「抽检 10 处」目标）
- [x] docs/05-tasklist 收尾登记 ✅ + 项目内存档（MEMORY.md）

---

## 九、变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-09-16 | v0.1 | 初稿：按「路径范围」（A-F）切分 5 阶段，5 疑问 Q1-Q5 待拍板 |
| 2026-09-16 | v0.2 | **按用户反馈改为「模块」切分**：10 阶段 + 前置 1 阶段；新增阶段依赖图、模块清单一览表、阶段子阶段拆解；保留 5 疑问 Q1-Q5 |
| 2026-09-16 | v1.0 | **5 疑问全部 ✅ 拍板**：Q1 文档仓子目录上移一层 + 内文清理；Q3 产品语义全部清零；Q4 保留 `demo-*` 文件名前缀；Q5 尝试重生成（回退跳过）。阶段 7-9 解锁；阶段依赖图无阻塞；待用户拍板启动阶段 0 |

---

## 十、待用户拍板的启动决策

| 决策点 | 选项 |
|--------|------|
| **是否启动阶段 0**（建分支 `feature/20260916_clean_demo-traces` + 基线回归） | 待用户拍板 |
| 执行顺序（阶段 1-6 可并行思路，是否按某顺序） | 待用户拍板（默认按 1→6 顺序） |
| 工作分支命名是否调整 | `feature/20260916_clean_demo-traces`（默认） |

阶段执行过程中会遇到的小决策（CLI 新名字、组件新名字等）在对应阶段执行时再拍板。

---

## 十一、执行收口（2026-09-16）

**结论：M0-M10 全部完成，全部 commit 落在 `feature/20260916_clean_demo-traces` 分支（commit 清单见下表）。**
累计 diff 以 `git diff main..HEAD --shortstat` 为准（含本次收尾笔）。

| 阶段 | commit | 要旨 |
|------|--------|------|
| 0 | — | 基线 540 passed / 1 skipped（起 MySQL 后） |
| 计划落盘 | `b37c967` | 计划 v1.0 + todo 跟踪表入库（M7 迁移前入库以便 git mv 追踪） |
| M1 | `a556bfb` | 基础设施层；CLI `--demo` → `--scenario` |
| M2 | `c6ef57c` `712e45a` `692f57a` `feee1aa` | graph / tools / scheduler+simulator+backtest / api+auth+observability |
| M3 | `8980be0` | 测试与评估层（含 `test_demo_package_importable` 改名） |
| M4 | `5d50a4a` | 包内 README |
| M5 | `a954ff3` | 根配置；修正 `.dockerignore` 4 条失效路径规则 |
| M6 | `9488fb3` | 规则层 |
| M7 | `0d74fdd` `1be6017` `80222fa` `6d345ae` | 文档仓 91 文件上移 + 36 文件 115 处引用同步 + 内文清理 + 链接修复 |
| M8 | `24f4e02` | 前端 CSS/变量/文案清零（组件名按拍板保留） |
| M9 | `8329a36` `c4247a2` | 图谱路径与节点名同步（重生成不可行） |
| M10 | `5245159` `873f2b7` `6ffa599` | 补漏（`test_demo.sh` 改名 + 非 .py 文件 + 设计稿陈旧变量名）+ 收尾登记 |

> **验证脚本自查记录**：M10 首轮 grep 用 `git ls-files` 直接喂路径给 Python，因默认 `core.quotePath` 转义，**所有中文名文件被静默跳过**（`except: continue` 吞掉了异常），导致漏报 2 处残留。改用 `git -c core.quotePath=false ls-files -z` 后修正。同类全仓扫描务必用此口径。

**过程中发现并处置的既有缺陷（非本次引入）**
1. `.dockerignore` 4 条运行时数据排除规则指向包名重构前的失效路径 —— 会导致 chroma_db/checkpoints.db/cache_db 被打进镜像
2. `config.py` 凭据路径为分片字符串拼接，不匹配字面替换 —— 若漏改会使凭据静默加载失败（本次已实测修正）
3. 早期全局改名把 CLI `--demo` 误替为 `--flex_fab_agent`（3 处）
4. `test_config.py::test_get_data_source_default_csv` 依赖测试执行顺序（他测直接改 `os.environ` 泄漏）—— 基线 540 passed 属顺序依赖，待专项修复
5. 文档仓 2 处迁移前既有失效相对链接
6. `graphs/README.md` 的重生成指引指向已丢失的脚本

**扫描方法论的教训**
早前各阶段扫描只覆盖 `*.py` 且大小写敏感，导致 `.sh`/`.sql`/`.ini`/`.example` 与大写 `Demo` 被漏到 M10 才由终验暴露。后续同类清理应一开始就用 `git ls-files` 全类型 + 大小写不敏感口径。
