# flex-fab-agent 代码图谱（codegraph @colbymchenry/codegraph v1.5.0）

> 索引方式：`codegraph init`（tree-sitter 解析，**本地确定式、无 API key**）
> 索引位置：`projects/flex-fab-agent/.codegraph/codegraph.db`（已被仓库 .gitignore）
> 产物目录：本文件同级的 `graph_export.json`（全量节点+边）、`file_import_edges.csv`（380 对文件依赖）

---

## 1. 索引统计

| 项 | 值 |
|---|---|
| 文件数 | 178（python 155 / typescript 11 / vue 11 / yaml 1） |
| 节点 | 2,657（function 1,218 · import 636 · variable 253 · method 181 · file 176 · constant 85 · class 80 · interface 15 · component 11） |
| 边 | 7,349（calls 3,229 · contains 2,634 · imports 826 · references 403 · instantiates 247 · extends 10） |
| 索引耗时 | ~1.3s |

## 2. 文件级依赖（Top，src→dst import 边数）

| 源文件 | 目标文件 | 边数 |
|---|---|---|
| tools/scheduler_tools.py | scheduler/assessment.py | …（详见 `file_import_edges.csv` 全量排序） |

模块级入度 Top（谁最被依赖）：`tools` 74 > `flex_fab_agent`(根) 49 > `observability` 33 > `scheduler` 24 > `simulator`（详见 `module_imports.md`）。

## 3. 典型调用链（codegraph callers 实测）

**写路径（排产触发）**
```
api.py:293 schedule_load  ─┐
main.py:58 main            ├─► run_scheduling(tools/scheduler_tools.py) ─► solver.solve + persist(schedule_versions)
auto_scheduler.py:111 _auto_schedule ─┘
```

**审批路径**
```
api.py:331 schedule_approve (POST /schedule/approve)   ─┐
auto_scheduler.py:153 _fifo_approve (FIFO 自动审批)      ├─► approve_schedule(tools) ─► approvals 落库 + orders 状态流转
```

**求解路径**：`solver.solve` 的直接调用者是 `scheduler/solver.py:256 main` + 单测；生产调用经 `run_scheduling → solve`（见上）。

## 4. 如何交互式使用（在这个项目里）

```bash
cd projects/flex-fab-agent
codegraph status .            # 索引状态/统计
codegraph files               # 178 文件结构 + 每文件符号数
codegraph query <关键词>       # 符号检索（模糊）
codegraph node <符号>          # 单个符号源码 + 调用方/被调方轨迹
codegraph callers <符号>       # 谁调用了它（↑ 上面演示）
codegraph callees <符号>       # 它调用了谁
codegraph impact <符号>        # 改动影响面
codegraph explore <问题>       # 相关符号源码 + 调用路径一次给出
codegraph sync .              # 增量同步（改代码后）
```

> 机器可读：`graph_export.json` = {nodes, edges}；`file_import_edges.csv` = 文件级 import 依赖表。
> 若要可视化：把 `graph_export.json` 喂给任意图工具（Gephi/networkx/d3）。

---
*生成：codegraph v1.5.0 init/index + 手工 callers 抽查；时间 2026-09-03。*
