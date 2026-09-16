# VibeGraph 交互调用图 · 新手使用手册

> 版本：v1.0 · 日期：2026-09-04 · 适用项目：flex-fab-agent
> 工具来源：VibeGraph（AST 静态分析 + React Flow 交互式可视化）

---

## 一、这是什么？

**VibeGraph** 是一个**交互式调用图可视化工具**。它把代码里的函数调用关系抽出来，画成一张可以拖拽、缩放、点击探索的图。

和 codegraph 的区别：codegraph 偏"命令行查询"，VibeGraph 偏"看图探索"——你用鼠标点点点，就能顺着调用链一路挖下去。

### 核心特点

| 特点 | 说明 |
|------|------|
| 🖱️ **纯交互** | 鼠标点拖拽，不用记命令 |
| 🔍 **渐进式探索** | 点一个节点展开它的邻居，不会一上来就 2000 个节点糊一脸 |
| 📊 **React Flow 格式** | 标准格式，数据可以导入其他工具 |
| 🤖 **AI 讲解（可选）** | 接入 LLM 后可以选中节点让 AI 解释 |

### 在 flex-fab-agent 项目里的规模

| 指标 | 值 |
|------|-----|
| 节点数 | 2,019 |
| 边数 | 6,349 |
| 格式 | React Flow（nodes + edges） |
| 生成日期 | 2026-09-03 |

### 产物位置

| 位置 | 说明 |
|------|------|
| `projects/flex-fab-agent/graphs/vibegraph/graph_data.json` | 原始数据（React Flow 格式，~2.9MB） |
| `projects/flex-fab-agent/graphs/viewers/vibegraph.html` | 单文件离线查看器（双击即开，~2.4MB） |
| `projects/VibeGraph/` | VibeGraph 工具源码（独立仓库，已加入 .gitignore） |

---

## 二、三种打开方式

### ✅ 方式一：单文件 HTML（最快，推荐新手）

**零环境，双击就看。**

1. 打开文件管理器，找到：
   ```
   projects/flex-fab-agent/graphs/viewers/vibegraph.html
   ```
2. 双击，浏览器自动打开（推荐 Chrome / Edge）

这是最简单的方式，整个 HTML 自包含 ECharts + 数据，不需要装任何东西。

### ✅ 方式二：VibeGraph Explorer（完整版功能）

如果你想用 VibeGraph 的全部功能（AI 讲解、聊天、渐进式探索），用源码版：

```bash
cd projects/VibeGraph/explorer
npm install
npm run dev
# 打开 http://localhost:5173
```

然后把 `graphs/vibegraph/graph_data.json` 拷到 `explorer/public/` 下，或者在界面里上传。

**什么时候用完整版**：
- 你想要 AI 讲解某个模块
- 你想要渐进式探索（点一个展开一个，不卡）
- 你想体验完整的 VibeGraph 功能

### ✅ 方式三：原始 JSON + 自己处理

`graphs/vibegraph/graph_data.json` 是标准 React Flow 格式：

```json
{
  "nodes": [
    {
      "id": "函数名",
      "type": "default",
      "data": { "label": "函数名", "type": "function" },
      "position": { "x": 0, "y": 0 }
    }
  ],
  "edges": [
    {
      "id": "边id",
      "source": "调用方",
      "target": "被调方",
      "animated": true
    }
  ],
  "meta": { ... }
}
```

可以导入任何支持 React Flow 的工具，或者自己写脚本分析。

---

## 三、单文件查看器使用指南

打开 `graphs/viewers/vibegraph.html` 后，界面大致是这样：

```
┌─────────────────────────────────────────────────┐
│ 🔍 搜索框  📊 节点数滑块  🎨 图例              │  ← 顶部工具栏
├──────────────┬──────────────────────────────────┤
│              │                                  │
│  节点列表    │         图谱可视化区              │
│  (左侧)      │         (中间，力导向图)          │
│              │                                  │
│              │                                  │
├──────────────┴──────────────────────────────────┤
│  节点详情面板 (右侧/底部，点击节点后显示)        │
└─────────────────────────────────────────────────┘
```

### 3.1 基础操作

| 你想做什么 | 怎么操作 |
|-----------|---------|
| 放大/缩小 | 鼠标滚轮 |
| 移动视图 | 拖拽空白处 |
| 选中一个节点 | 单击节点 |
| 看节点详情 | 单击节点 → 右侧/底部面板 |
| 找某个函数 | 顶部搜索框输入名字 |
| 只看某类节点 | 点顶部图例里的颜色 |

### 3.2 节点类型说明

| 颜色 / 类型 | 含义 | 说明 |
|-------------|------|------|
| function | 函数节点 | 项目里定义的函数 |
| class | 类节点 | 类定义 |
| external | 外部依赖 | 从第三方库导入的（比如 `vite.defineConfig`） |
| unresolved | 未解析 | 找不到定义的符号（可能是动态生成或全局变量） |

> 💡 小贴士：`external` 和 `unresolved` 的节点可以先忽略，重点看项目内部的 function/class。

### 3.3 节点太多太卡怎么办？

2019 个节点全显示可能会卡。几个办法：

1. **调小"最大节点数"滑块** — 只显示最重要的节点
2. **用搜索筛选** — 搜你关心的关键词，只显示匹配的
3. **按类型筛选** — 点图例，只看 function，隐藏 external/unresolved
4. **用完整版 Explorer** — 支持渐进式展开，默认只显示少量节点

---

## 四、VibeGraph Explorer（完整版）使用指南

### 4.1 启动

```bash
cd projects/VibeGraph
# 拷贝数据到 explorer
cp ../flex-fab-agent/graphs/vibegraph/graph_data.json explorer/public/

# 启动前端
cd explorer
npm install   # 第一次需要
npm run dev   # 打开 http://localhost:5173
```

### 4.2 AI 讲解功能（可选）

如果想让 AI 帮你解释代码：

1. 在 VibeGraph 根目录创建 `.env` 文件：
   ```
   OPENROUTER_API_KEY=你的key
   ```
2. 启动后端：
   ```bash
   cd projects/VibeGraph
   source vibegraph/venv/bin/activate   # 虚拟环境已装好
   python serve.py
   ```
3. 前端界面里选中节点，点"AI 解释"

> 💡 flex-fab-agent 的 `graphs/vibegraph/venv` 已装好后端依赖，可以直接用。

### 4.3 渐进式探索

完整版 Explorer 的最大亮点是**渐进式探索**：

1. 一开始只显示几个核心节点
2. 点一个节点 → 它会展开这个节点的"邻居"（调用方和被调方）
3. 再点新展开的节点 → 继续往下挖
4. 像"剥洋葱"一样，一层一层深入，不会一下被 2000 个节点淹没

**推荐用法**：从入口函数开始（比如 `main`、`app`），顺着调用链一层一层点进去。

---

## 五、新手实战场景

### 场景 1："我想看看前端页面怎么调用后端 API"

**步骤**：
1. 打开 `vibegraph.html`
2. 搜索框搜 "api" 或 "axios"
3. 找到相关节点，点击查看详情
4. 顺着边找：哪些函数调用了 API → API 返回值去了哪里

> ⚠️ 注意：VibeGraph 的调用图主要是**前端代码**的 AST 分析（2019 节点大部分是前端），后端 Python 的调用关系用 codegraph 查更准。

---

### 场景 2："我想理解一个复杂组件的调用链"

**步骤**：
1. 搜索组件名（比如 "Dashboard"、"ScheduleView"）
2. 点击组件节点
3. 看它调用了哪些函数（出边）
4. 看哪些地方用到了它（入边）
5. 一层一层往下点，画出完整的调用树

---

### 场景 3："我要重构这块代码，先看看依赖关系"

**步骤**：
1. 找到你要重构的函数/组件
2. 看入边（谁调用它）→ 评估改动影响面
3. 看出边（它调用谁）→ 评估依赖
4. 把相关节点都标出来，画一个子图

> 💡 提示：影响面分析也可以用 `codegraph impact <符号>`，命令行更快。

---

## 六、和另外两个图谱的对比

三个图谱各有侧重，配合使用效果最好：

| 维度 | Understand-Anything | codegraph | VibeGraph |
|------|---------------------|-----------|-----------|
| **生成方式** | 多 Agent 理解总结 | tree-sitter 确定性解析 | AST 静态分析 |
| **内容侧重** | 架构分层、概念、中文描述 | 精确调用关系、符号定义 | 前端调用图可视化 |
| **交互方式** | 聊天提问 + 可视化看板 | 命令行查询 | 鼠标拖拽点击 |
| **适合新手吗** | ✅ 非常适合（有讲解） | ⚠️ 需要记命令 | ✅ 直观，看图就行 |
| **精度** | 概念级 | 语法级（最准） | AST 级 |
| **中文** | ✅ 全中文 | ❌ 代码原名 | ❌ 代码原名 |
| **强项** | 快速入门、建立整体认知 | 精确查找、影响面分析 | 交互探索、可视化 |

### 新手推荐学习路径

```
第 1 步：Understand-Anything（建立整体认知）
   ↓
第 2 步：VibeGraph（看着图探索，建立直觉）
   ↓
第 3 步：codegraph（精确定位、深入分析）
```

---

## 七、常见问题

### Q1：为什么 VibeGraph 里大部分是前端代码？

VibeGraph 最初是为前端项目设计的（React/Vue 调用图），所以对前端代码的解析比较完善。后端 Python 的调用关系推荐用 codegraph。

### Q2：和 codegraph 的数据能互导吗？

两者格式不一样（codegraph 是自己的节点/边格式，VibeGraph 是 React Flow 格式），但都可以导出 JSON，写个脚本转换就行。

`graphs/viewers/` 下三个单文件 HTML 用的是**同一套查看器模板**（ECharts 力导向图），所以操作方式基本一致。

### Q3：数据怎么更新？

代码改了之后，需要重新生成 `graph_data.json`。

用 VibeGraph 工具重新扫描项目：
```bash
cd projects/VibeGraph
# 用 VibeGraph 的 CLI 或脚本重新生成
# 具体命令参考 VibeGraph 项目 README
```

生成后把新的 `graph_data.json` 覆盖到 `graphs/vibegraph/` 下就行。

### Q4：能用来读后端 Python 代码吗？

可以但不推荐。VibeGraph 对 Python 的支持不如前端完善，而且 Python 侧的调用图用 codegraph 更准确、查询也更方便。

如果你就是想看 Python 的可视化调用图，用 `codegraph` 的 `graph_export.json` + `viewers/codegraph.html` 就行。

### Q5：单文件 HTML 能发别人看吗？

可以！整个 HTML 是自包含的（ECharts 库 + 数据全内联），直接发文件就行，对方收到双击就能看，**不需要任何环境、不需要联网**。

---

## 八、快速上手 Checklist

- [ ] 双击打开 `graphs/viewers/vibegraph.html`，看看图长什么样
- [ ] 滚轮缩放一下，拖拽平移一下
- [ ] 搜索一个你认识的函数名（比如 "main"、"scheduler"）
- [ ] 点击一个节点，看右侧详情面板
- [ ] 试试图例筛选，把 external / unresolved 都关掉，只看 function
- [ ] （可选）启动完整版 Explorer，体验渐进式探索
- [ ] （可选）配置 API Key，试试 AI 讲解功能

完成这几步，VibeGraph 就算入门了 🎉

---

*本手册基于 VibeGraph 与 flex-fab-agent 2026-09-03 调用图编写。如有更新请对应调整。*
