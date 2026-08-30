# flex-fab-agent · 制造业 3D 打印智能排产系统

> 面向**3D 打印柔性制造**的智能排产智能体：订单自动排队、CP-SAT 约束求解算最优排单方案、事件驱动生产模拟、Agent 对话式调度、全链路无人值守，从下单到打印完成自动闭环。
>
> 开源地址：<https://github.com/sjs1919/flex-fab-agent> ｜ License：MIT

## 这个项目解决什么问题

3D 打印多品种小批量柔性制造，排产靠人工 Excel 慢、来急单/设备故障就全乱、交期只能拍脑袋。flex-fab-agent 把「**下单 → 排队 → 排产 → 审批 → 上机打印 → 完成**」全流程自动化：

| 能力 | 说明 |
|------|------|
| 对话式智能体 | 用自然语言查订单/设备/库存/客户/合同，跑排产、审批版本（LangGraph 编排，18 种工具自动调度） |
| 数学规划排产 | OR-Tools CP-SAT 约束求解（C1-C9 九大约束），算全局最优排单方案，不是拍脑袋 |
| 事件驱动模拟 | 生产流程仿真：订单到达 → 前道 → 打印 → 完成，设备故障/插单随机事件 |
| 全链路自动化 | 自动排产调度器 + FIFO 审批 + 幂等防重复，同一订单只被打印一次 |
| Web 控制台 | 看板 / 调试台 / 审批 / 案例 / 资源 / 配置 / 演示 多 tab，ECharts 可视化 |
| 评估体系 | 三层评估（工具/轨迹/语义）、RAGAS 回归、61 个自动化测试文件 |

## 快速开始

### Docker 方式（推荐）

```bash
docker compose build
docker compose up -d
# 浏览器打开 http://localhost:8000
```

### 本地方式

```bash
pip install -r requirements-flex-fab-agent.txt
cp .env.example .env            # 填 LLM API Key 与 MySQL
python -m flex_fab_agent.schema.migrate --up   # 建表
python -m flex_fab_agent.main --check          # 地基自检
uvicorn flex_fab_agent.api:app --host 0.0.0.0 --port 8000
```

### 前端单独开发

```bash
cd web && npm install && npm run dev   # http://localhost:5173
```

## 技术架构

```
数据层（订单/设备/库存/客户） → 求解层（CP-SAT 数学规划） → 模拟层（事件驱动生产仿真）
    → 智能体层（LangGraph 对话 + 工具调度） → 服务层（FastAPI） → 界面层（Vue3 控制台）
```

三个设计亮点：
1. **数学规划排产** —— CP-SAT 约束求解算全局最优，非启发式拍脑袋。
2. **全链路自动化** —— 下单到完成无人值守，幂等保证订单只打印一次。
3. **对话式智能体** —— 自然语言驱动 18 种工具，支持查数据/跑排产/批版本。

## 测试

```bash
python run_all_tests.py                    # 全量单测（mock LLM，零成本）
python flex_fab_agent/smoke_test.py --skip-llm       # 部署冒烟 S0-S11
python -m flex_fab_agent.eval.runner       # 三层评估（真实 LLM）
```

## 目录结构

```
flex-fab-agent/
├── flex_fab_agent/      # Python 包（scheduler/simulator/agents/graph/rag/tools/...）
├── web/                 # Vue3 前端控制台
├── docs/                # 文档仓（spec/plan/todo/test/deployment/manuals/reports）
├── rules/               # 项目编码规范
├── Dockerfile / docker-compose.yml
└── requirements*.txt
```

## 配置与凭据

- 环境变量模板见 `.env.example`（复制为 `.env` 填写，`.env` 已 gitignore）。
- 敏感口令写入 `docs/demo/credentials.local.md`（gitignore，不入库），或通过环境变量注入。

## License

[MIT](./LICENSE)
