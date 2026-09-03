# flex-fab-agent · 图谱产物区

本文件夹存放对 flex-fab-agent 生成的**知识图谱 / 代码图谱**产物，供随时打开、查阅、交互。均为**本地文件、未纳入 git**（`graphs/.gitignore` 已自忽略；若想提交，删掉 `.gitignore` 内容并自行 `git add`）。

| 图谱 | 说明 | 位置 / 产物 |
|---|---|---|
| **Claude 知识图谱** | 我通读源码+docs+索引后写的分层架构图，含 Mermaid + 模块实体表 + 关键调用边 + 数据模型 | `claude-knowledge-graph.md` |
| **codegraph 代码图谱** | tree-sitter 确定性索引（2,657 节点/7,349 边）；全量节点边导出 + 文件级依赖表 + 模块依赖 + 使用手册 | 索引 `../.codegraph/`；导出见 `codegraph/` |
| **VibeGraph 图谱** | AST 交互调用图数据（2,019 节点/6,349 边，React Flow 格式） | `vibegraph/graph_data.json` |
| **understand-anything 图谱** | 多 agent 流水线已生成（702 节点/1,569 边/10 层/9 巡览，中文），产物在项目根 `../.understand-anything/`（knowledge-graph.json + 指纹 + meta） | 留档 `understand-anything/knowledge-graph.json`，说明见下 |

---

## 怎么用

### Claude 知识图谱
直接打开 `claude-knowledge-graph.md`（VS Code 预览 Mermaid 需装 Markdown Preview Mermaid 扩展；或在 https://mermaid.live 粘贴 flow 块）。

### codegraph（可随时增量查询）
```bash
cd projects/flex-fab-agent
codegraph status .          # 索引统计
codegraph files             # 178 文件结构
codegraph query <词>        # 符号检索
codegraph callers <符号>    # 谁调用它
codegraph callees <符号>    # 它调用谁
codegraph impact <符号>     # 改动影响面
codegraph sync .            # 改代码后增量同步
```
改动代码后想更新导出：`python tmp/flex-fab-agent-graphs/codegraph_export.py`（脚本仍在 tmp，产物会覆盖本 `codegraph/`）。

### VibeGraph（交互式调用图预览）
数据已生成，可直接用 VibeGraph 的 explorer 打开：
```bash
cd projects/VibeGraph
# 1) 把 graph_data.json 放进 explorer/public/
cp <本目录>/vibegraph/graph_data.json explorer/public/
cd explorer && npm install && npm run dev   # 打开 http://localhost:5173
```
> 若要用 AI 讲解/聊天功能，需在 VibeGraph 根 `.env` 填 `OPENROUTER_API_KEY`，并 `python serve.py`（本目录 `vibegraph/venv` 已装好后端依赖，用它运行即可）。

### understand-anything（跑完后）
产物在项目根 `../.understand-anything/`（`knowledge-graph.json` + `config.json` + 原始批次）。
在 flex-fab-agent 里开 Claude Code 后执行 `/understand-dashboard` 打开交互看板，`/understand-chat <问题>` 提问，`/understand --auto-update` 打开增量更新。

> 提示：默认 `.understand-anything/` 也是本地产物；是否入库由插件 config 与你的 git 规则决定。

---

## 演示：单文件 HTML，双击即看（零环境）

三个图谱各有**单文件离线静态查看器**：`echarts` 已内联、数据已内嵌，**整个演示就是一个 `.html`**，双击即开；也可单独拷贝/上传/发给别人用，无需 npm / python / 服务器 / 网络 / API key：

| 图谱 | 单文件 | 大小 |
|---|---|---|
| understand-anything | `viewers/understand-anything.html` | ~1.6M |
| VibeGraph | `viewers/vibegraph.html` | ~2.4M |
| codegraph | `viewers/codegraph.html` | ~2.5M |

使用：顶部可调最大节点数（防大图卡顿）、搜索框模糊搜、图例点某色只看它、codegraph 有**模块下拉**；点图中/列表中节点 → 右侧看详情。浏览器建议 Chrome/Edge。

> 重生成：`python tmp/flex-fab-agent-graphs/build_viewers.py`（会覆盖这三个 html）。

---
*生成日期 2026-09-03。codegraph 索引、VibeGraph 导出、understand-anything 流水线均可随时重跑以刷新。*
