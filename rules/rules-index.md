# 规则总索引

> **规则优先级（冲突裁决顺序）**：项目 CLAUDE.md 附加红线 > `stack-*/` > `common/`。

## 触发场景 -> 加载文件

| 触发场景 | 加载文件 |
|---------|---------|
| TDD / 单测 / 集成测试 / E2E（流程与分层） | -> `common/testing.md` |
| 任务拆分 / 四门禁 / 执行模式（自动挡） | -> `common/workflow.md` |
| 提问 / 需求澄清 / Bug 修复节奏 | -> `common/conversation.md` |
| 需求澄清 / UI 原型设计（Superpowers Brainstorming） | -> `common/skill-integration.md` |
| 需求变更影响分析 / 知识图谱（CodeGraph + Understand-Anything） | -> `common/skill-integration.md` |
| 分支 / 提交 / 代码更新 | -> `common/git.md` |
| 文档流转 / 归档 / 待办登记 | -> `common/docs-flow.md` |
| 踩坑 / 教训沉淀 / 规范反哺 | -> `common/pitfalls.md` |
| 前后端接口对接 / API 文档同步 | -> `common/api-contract.md` |
| 部署 / 发布 / 镜像构建 / 回滚 | -> `common/deployment.md` |
| 服务器操作（读/写边界） | -> `common/server-approval.md` |
| demo 分层 / 工具注册 / 数据源抽象 | -> `stack-python/arch.md` |
| 异常处理 / 工具返回值 | -> `stack-python/error.md` |
| 观测 / 审计 / span | -> `stack-python/logging.md` |
| MySQL / 迁移 / 种子数据 / tenant_id / WSL 数据库 | -> `stack-python/database.md` |
| Python 测试执行 / pytest / mock LLM / eval | -> `stack-python/testing.md` |
| Python 版本 / Docker / WSL 构建 | -> `stack-python/ops-build.md` |

> `common/` 永不因换栈修改 -- 通用层与语言无关，新技术栈只做追加，不动已有文件。
