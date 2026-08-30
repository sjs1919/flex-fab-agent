# flex-fab-agent 项目规范

## 定位

制造业排程排产多 Agent 智能体（flex-fab-agent）：CP-SAT 约束排产 + 事件驱动模拟 + Agent 调度闭环 + 自动排产调度器 + Web 控制台。代码 + 文档 + 规范同仓。

## 红线

- 🚫 **禁止自动 git**：commit / push 必须用户发起
- 🚫 **敏感信息不入库**：密码/密钥只留占位符，真实值在 `docs/demo/credentials.local.md`（gitignored）或环境变量
- 🚫 **未测试禁止部署**：`python run_all_tests.py` 全过 + 前端构建成功才可提请部署

## 命令

| 命令 | 说明 |
|------|------|
| `python run_all_tests.py` | 全量单测（WSL 下，mock LLM 零成本） |
| `python -m flex_fab_agent.smoke_test --skip-llm` | 部署冒烟 S0-S11 |
| `python -m compileall flex_fab_agent` | 静态检查 |
| `cd web && npm run build` | 前端构建（WSL 下，含 vue-tsc 类型检查） |
| `docker compose build && docker compose up -d` | Docker 部署 |

## 编码原则

1. **先思考** — 明假设、曝困惑、呈权衡；不默选、敢反对
2. **简单优先** — 最少代码解决问题；不预设扩展
3. **外科手术** — 只改要求的；不动相邻代码/格式
4. **目标驱动** — 先定义可验证标准；多步任务列「步骤→验证」清单

## 文档

- 文档仓：`docs/demo/`（01-requirements / 02-specs / 04-plans / 05-tasklist / 08-test / 09-reports / 10-deployment / 11-manuals）
- 任务登记：`docs/demo/05-tasklist/todo-<主题>-YYYYMMDD.md`（索引 `todo.md`）

## 环境

- Python >= 3.10、Node >= 18
- 测试 / 构建 / Docker 在 **WSL** 下执行
- 代理：家里 Clash `7890` / 公司 `3450`（如访问外网模型）
- LLM Provider 主备降级：DeepSeek 主用 → 火山豆包 → Kimi；凭据双源（env → credentials.local.md 兜底）
