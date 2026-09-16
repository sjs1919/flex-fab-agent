# codegraph 代码图谱 · 新手使用手册

> 版本：v1.0 · 日期：2026-09-04 · 适用项目：flex-fab-agent
> 工具来源：`codegraph`（@colbymchenry/codegraph v1.5.0，tree-sitter 确定性解析）

---

## 一、这是什么？

**codegraph** 是一个**本地、确定、零依赖 API**的代码图谱工具。它用 tree-sitter 解析你的源码，把所有函数、类、变量、导入关系都抽出来，建成一张可以查询的图。

和 grep 不一样的是：grep 只能搜文本，codegraph 懂代码结构——它知道谁调用了谁、谁被谁调用、改一个函数会影响哪些地方。

### 核心特点

| 特点 | 说明 |
|------|------|
| 🖥️ **纯本地** | 不联网、不上传、不需要 API key |
| ⚡ **速度快** | 178 个文件只要 1.3 秒就能建好索引 |
| 🎯 **确定性** | tree-sitter 语法解析，同样的代码每次结果完全一样 |
| 🔍 **结构感知** | 懂调用关系、继承关系、导入关系，不是纯文本搜索 |

### 在 flex-fab-agent 项目里的规模

| 指标 | 值 |
|------|-----|
| 索引文件数 | 178（Python 155 / TypeScript 11 / Vue 11 / YAML 1） |
| 节点总数 | 2,657 |
| 边总数 | 7,349 |
| 函数节点 | 1,218 |
| 类节点 | 80 |
| 调用边 | 3,229 |
| 导入边 | 826 |

### 产物位置

| 位置 | 说明 |
|------|------|
| `projects/flex-fab-agent/.codegraph/codegraph.db` | **索引数据库**（SQLite，7.8MB，已 gitignore） |
| `projects/flex-fab-agent/graphs/codegraph/` | 导出产物（graph_export.json、file_import_edges.csv、module_imports.md） |
| `projects/flex-fab-agent/graphs/viewers/codegraph.html` | 单文件离线查看器（双击即开，~2.5MB） |

---

## 二、三种打开方式

### ✅ 方式一：命令行查询（最常用，推荐）

codegraph 主要是**命令行工具**，在终端里敲命令查询。这也是最灵活的用法。

先确保你在项目目录下：
```bash
cd projects/flex-fab-agent
```

### ✅ 方式二：单文件 HTML（可视化浏览）

想看图的话，直接双击：
```
projects/flex-fab-agent/graphs/viewers/codegraph.html
```

- 顶部有**模块下拉菜单**（按模块筛选）
- 搜索框模糊搜节点
- 点节点看详情 + 相邻关系
- 调最大节点数防卡顿

### ✅ 方式三：导出数据自己玩（高级）

`graphs/codegraph/graph_export.json` 是完整的节点+边导出，结构：
```json
{
  "nodes": [
    { "id": "...", "type": "function", "name": "solve", "file": "scheduler/solver.py", ... }
  ],
  "edges": [
    { "source": "...", "target": "...", "type": "calls", ... }
  ]
}
```

可以喂给 Gephi、D3、networkx 等工具做自定义分析。

---

## 三、命令行速查表（新手最常用的 8 个）

> 所有命令都在 `projects/flex-fab-agent/` 目录下执行。

### 1. `codegraph status` — 看看索引状态

```bash
codegraph status .
```

输出索引统计：多少文件、多少节点、多少边、最后同步时间。

**什么时候用**：刚打开项目，确认索引在不在、新不新。

---

### 2. `codegraph files` — 项目文件总览

```bash
codegraph files
```

列出所有 178 个文件，每个文件后面标了有多少符号（函数/类/变量）。

**什么时候用**：想知道项目大概有哪些文件、哪些文件比较复杂（符号多）。

---

### 3. `codegraph query <关键词>` — 符号搜索

```bash
codegraph query solve
```

模糊搜索所有名字里带 "solve" 的函数、类、变量，告诉你它们在哪个文件第几行。

**比 grep 好在哪**：只搜符号名（函数名/类名/变量名），不会搜到注释里的、字符串里的。

---

### 4. `codegraph callers <符号>` — 谁调用了它？ ⭐

```bash
codegraph callers run_scheduling
```

列出**所有调用了** `run_scheduling` 的地方，包括调用链。

**这是最实用的命令之一。** 你想改一个函数，但不知道哪些地方会用到它——用这个。

**例子**：
```
$ codegraph callers run_scheduling

tools/scheduler_tools.py:120  def run_scheduling(...)    # 函数定义
  ↳ api.py:293  schedule_load()
  ↳ main.py:58  main()
  ↳ auto_scheduler.py:111  _auto_schedule()
```

告诉你：`run_scheduling` 在 3 个地方被调用了。

---

### 5. `codegraph callees <符号>` — 它调用了谁？

```bash
codegraph callees run_scheduling
```

列出 `run_scheduling` 函数**内部调用了**哪些其他函数。

**什么时候用**：你在读一个函数，想知道它依赖了什么、往下会走到哪。

---

### 6. `codegraph node <符号>` — 单个符号详情

```bash
codegraph node solve
```

展示某个符号的完整信息：定义位置、源码片段、调用方、被调方。

相当于把 `callers` + `callees` + 源码 放在一起看。

---

### 7. `codegraph impact <符号>` — 改动影响面 ⭐

```bash
codegraph impact solve
```

**估算改这个函数会影响多大范围**。它会反向遍历调用链，告诉你：
- 直接调用者有多少
- 间接影响到多少层
- 涉及哪些模块

**改代码前必看**，尤其是改底层函数的时候。

---

### 8. `codegraph sync` — 增量同步索引

```bash
codegraph sync .
```

你改了代码之后，用这个更新索引。**增量**的，很快（不到 1 秒）。

**什么时候用**：改了代码之后，发现 `callers` / `callees` 结果不对了，就 sync 一下。

---

### bonus：`codegraph explore <问题>` — 自然语言探索

```bash
codegraph explore "排产审批的流程是什么？"
```

用自然语言提问，codegraph 会给出相关的符号和调用路径。

> 💡 这个功能依赖 LLM 吗？取决于 codegraph 版本。v1.5.0 的 explore 是本地符号匹配+路径搜索，不需要联网。

---

## 四、新手实战场景

### 场景 1："我想找到排产求解的入口"

**步骤**：
```bash
# 1. 搜一下关键词
codegraph query scheduling

# 2. 看到有个 run_scheduling，看看谁调用它
codegraph callers run_scheduling

# 3. 顺着调用链往上找，找到最顶层的入口
codegraph node api.schedule_load
```

**结论**：排产有三个入口——API 接口（`api.py:schedule_load`）、CLI 主函数（`main.py:main`）、自动调度器（`auto_scheduler.py:_auto_schedule`）。

---

### 场景 2："我要改 solver.solve，会不会搞崩别的？"

**步骤**：
```bash
# 1. 先看影响面
codegraph impact solve

# 2. 看看谁调用了它
codegraph callers solve

# 3. 对着调用列表一个个评估风险
```

如果影响面太大（比如有几十个调用方），改的时候要小心，最好加单元测试兜底。

---

### 场景 3："这个函数到底在干嘛？读不懂"

**步骤**：
```bash
# 1. 看函数详情和源码
codegraph node 复杂函数名

# 2. 看它调用了谁（往下走的路径）
codegraph callees 复杂函数名

# 3. 看谁调用了它（上下文）
codegraph callers 复杂函数名
```

从"它依赖什么"和"什么依赖它"两个方向理解，比死读函数体快得多。

---

## 五、可视化查看器使用指南

打开 `graphs/viewers/codegraph.html` 后：

### 顶部工具栏

| 控件 | 作用 |
|------|------|
| 🔍 搜索框 | 模糊搜节点名，支持中文 |
| 📊 最大节点数滑块 | 节点太多卡顿的时候调小，默认显示全部 |
| 📁 模块下拉 | 按模块筛选（只看 scheduler / tools / simulator 等） |
| 🎨 图例 | 点颜色可以显示/隐藏某类节点 |

### 图操作

| 操作 | 效果 |
|------|------|
| 滚轮 | 缩放 |
| 拖拽空白处 | 平移视图 |
| 点击节点 | 选中，右侧显示详情，相邻节点高亮 |
| 点击节点列表 | 同点击图中节点 |

### 节点颜色含义

| 颜色 | 节点类型 | 说明 |
|------|---------|------|
| 🔵 蓝色 | function | 函数（最多，1218 个） |
| 🟢 绿色 | class | 类（80 个） |
| 🟡 黄色 | variable | 变量 |
| 🟣 紫色 | import | 导入语句 |
| 🔴 红色 | method | 类方法 |

---

## 六、常见问题

### Q1：codegraph 和 Understand-Anything 有什么区别？

| 维度 | codegraph | Understand-Anything |
|------|-----------|---------------------|
| 生成方式 | tree-sitter 语法解析，确定性 | 多 Agent 理解，带总结归纳 |
| 内容侧重 | 精确的调用关系、符号定义 | 架构分层、概念理解、中文描述 |
| 查询方式 | 命令行（callers/callees/impact...） | 聊天式提问 + 可视化看板 |
| 精度 | 非常精确（语法级） | 概念级，可能有遗漏 |
| 更新速度 | 极快（增量 sync < 1s） | 慢（要重新跑流水线） |
| 中文 | 否（代码原名） | 是（带中文描述） |

**简单说**：codegraph 是"手术刀"，精确查代码结构；Understand-Anything 是"地图"，给你整体认知。两个配合着用。

### Q2：和 VibeGraph 又有什么区别？

VibeGraph 也是调用图，但侧重**交互式可视化**（React Flow 格式），更偏"看图"。codegraph 更偏"查"和"分析"。

数据量上 codegraph 更大（2657 节点 vs 2019 节点），因为 codegraph 索引了 Python + 前端所有代码，VibeGraph 主要是前端调用图。

### Q3：索引在哪？占空间吗？

索引是一个 SQLite 数据库：`.codegraph/codegraph.db`，flex-fab-agent 项目大约 7.8MB。已经被 `.gitignore` 了，不会提交到仓库。

### Q4：我换项目了怎么用？

在新项目根目录执行 `codegraph init .` 就行。第一次会全量索引，之后用 `codegraph sync .` 增量更新。

### Q5：支持哪些语言？

Python、TypeScript、JavaScript、Vue、Go、Rust……主流语言基本都支持（靠 tree-sitter 的 parser）。

---

## 七、快速上手 Checklist

- [ ] 在 `projects/flex-fab-agent/` 下执行 `codegraph status .`，确认索引存在
- [ ] 试试 `codegraph query solve`，搜一个你认识的函数
- [ ] 试试 `codegraph callers run_scheduling`，看调用关系
- [ ] 试试 `codegraph impact solve`，看影响面
- [ ] 双击打开 `graphs/viewers/codegraph.html`，看看图
- [ ] 改一个小函数，`codegraph sync .` 后再查，确认更新了

完成这 6 步，codegraph 就算入门了 🎉

---

*本手册基于 codegraph v1.5.0 与 flex-fab-agent 2026-09-03 索引编写。工具如有版本升级请对应调整命令。*
