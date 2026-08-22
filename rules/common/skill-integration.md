# 技能集成：工作流中的 Skill 联动

本文件定义三个外部 Skill 在项目工作流中的触发时机和使用方式。

## Skill 总览

| Skill | 本质 | 安装方式 | 解决的问题 |
|-------|------|---------|-----------|
| **Superpowers-zh Brainstorming** | 需求设计协作 Skill | `npx superpowers-zh` | 需求澄清阶段，有原型时提供视觉伴侣 |
| **CodeGraph** | MCP 语义知识图谱 | `npx @mschreib28/codegraph` | 需求变更时快速掌握代码结构、分析影响面 |
| **Understand-Anything** | 交互式知识图谱 Skill | 由 registry 安装 | 将代码库转化为可探索的知识图谱，辅助变更方案设计 |

## 触发时机 → 使用方式

```
阶段0 (需求澄清)                        阶段1 (任务拆分)
  │                                       │
  ├─ 有 UI 原型？                          │
  │  → Superpowers Brainstorming           │
  │    视觉伴侣协助界面设计                │
  │                                       ├─ 需求变更？
  │                                       │  → CodeGraph + Understand-Anything
  │                                       │    影响分析 → 外科手术式变更方案
  │                                       │
  │                                       ├─ 门禁2 代码验收
  │                                       │  → CodeGraph 辅助审查代码覆盖
  │                                       │
  │                                       └─ 门禁3 CR 走读
  │                                          → Understand-Anything
  │                                            diff + 影响面审查
```

## 场景一：需求澄清 + UI 原型 → Superpowers Brainstorming

### 触发条件

- **阶段**：阶段0（需求澄清）
- **信号**：用户提供了 UI 原型（Figma/Sketch/Axure 截图、纸面草稿、PRD 上的界面描述）
- **不触发**：纯功能/非 UI 类需求（API、后台逻辑、数据库变更）

### 使用步骤

1. 在需求澄清阶段识别到 UI 原型后，提议使用 **Superpowers Brainstorming 视觉伴侣**
2. 视觉伴侣在浏览器中展示原型、生成布局对比图、交互线框图
3. 对话确认 UI 方案，将设计结论写入 spec
4. 视觉伴侣提议必须是一条独立消息，不可与澄清问题合并

### 在 spec 中的落点

```
§3 设计 → 界面设计
  ├─ 原型来源（用户提供的截图/链接）
  ├─ 布局方案（Brainstorming 视觉伴侣输出的推荐方案）
  └─ 交互说明（各状态的流转关系）
```

> **依赖前置**：项目已安装 `npx superpowers-zh`（`code-repo-template/README.md` 有安装说明）。

## 场景二：需求变更 → CodeGraph + Understand-Anything

### 触发条件

- **阶段**：阶段0 至阶段1 过渡（需求确认后、任务拆分前）
- **信号**：① 原 spec 范围变更 ② 用户追加需求 ③ 修复需要在已有功能上做修改
- **不触发**：独立新功能（不涉及现有代码修改）

### CodeGraph 的使用

CodeGraph 构建语义知识图谱（符号关系、调用链、类继承、路由注册），用于快速定位变更点：

```
需求变更描述
    │
    ├── codegraph_search      → 定位涉及的符号（函数/类/组件/路由）
    ├── codegraph_callers     → 向上追溯调用链（谁调了这些函数？）
    ├── codegraph_callees     → 向下查看依赖链（这些函数调了什么？）
    └── codegraph_impact      → 整体影响面分析（变更波及哪些文件？）
```

**核心原则**：使用 CodeGraph 时，通过 Explore Agent 调用 `codegraph_context` 和 `codegraph_explore`（返回大量源码）；主会话仅调轻量工具（`codegraph_search` / `codegraph_impact` / `codegraph_callers` / `codegraph_callees` / `codegraph_node`）。

### Understand-Anything 的使用

Understand-Anything 将代码库转为交互式知识图谱，用于全局理解：

```
/understand               → 构建代码库知识图谱（首次运行 token 消耗大，后续增量）
/understand-dashboard     → 打开浏览器图可视化面板
/understand-diff          → 分析变更波及的文件（变更前必过步骤）
/understand-chat <问题>   → 自然语言查询代码库："登录模块依赖哪些服务？"
/understand-explain <路径> → 深度解释单个文件的结构
```

**推荐流程**：

1. 项目初次启用时跑一次 `/understand` 建图（`.understand-anything/` 可提交 Git，新成员免重跑）
2. 需求变更到来时，先跑 `/understand-diff` 看变更波及范围
3. 对波及的模块用 `codegraph_impact` 精准分析影响面
4. 综合两份信息 → 方案文档 → 写入 spec §4 变更

### 在 spec 中的落点

```
§4 变更（需求变更专属）
  ├─ 变更源（原 spec 的哪个章节哪条需求被修改）
  ├─ 影响分析（CodeGraph 影响面 + Understand-Anything diff）
  ├─ 变更点清单（逐个文件/逐个符号列出）
  └─ 废弃保留（被替换的原功能如何处置）
```

> **依赖前置**：CodeGraph 通过 `npx @mschreib28/codegraph` 安装 + `codegraph init -i` 建图；Understand-Anything 通过 registry 安装，首次跑 `/understand` 建图。

## 集成检查清单

每启用一个新项目时检查以下三项是否就绪：

- [ ] **Superpowers-zh**：`npx superpowers-zh` 可用，`using-superpowers` bootstrap 已配置
- [ ] **CodeGraph**：`.codegraph/` 索引已构建，`codegraph_search` 等 MCP 工具可用
- [ ] **Understand-Anything**：Skill 已注册，`/understand` 命令可执行
