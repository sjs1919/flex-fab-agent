# 运维与构建规则（stack-python）

- Python **3.11 锁定**；依赖增删改 requirements-demo.txt 且不随意升级版本。
- **Docker / 前端 / 镜像构建必须在 WSL 下执行**（Windows npm/Docker 有 EPERM 文件锁与上下文爆炸教训）。
- **MySQL / PostgreSQL / Chroma 向量库服务跑 WSL**（见 database.md 环境红线）。
- 不入库：`.env`、`checkpoints.db`、`cache_db/`、`chroma_db/`、`*.log`、`demo/eval/reports/`。
- compose 必须带健康检查；`/health` 端点需报数据源与模拟器 tick 状态。
- 服务器操作读/写边界：读直接执行，写必须先问用户（rules/common/server-approval.md）。
