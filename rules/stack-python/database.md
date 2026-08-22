# 数据库规则（stack-python / MySQL）

## 环境红线

- **MySQL / PostgreSQL / Chroma 向量库服务一律跑 WSL**；Windows 侧只经 `localhost` 访问（WSL2 端口转发）。🚫 禁止在 Windows 本机安装这些服务。

## 连接与事务

- 连接串统一 `config.py:MYSQL_DSN`（.env 配置）；连接池后续引入时只改 data 层。
- 短事务原则：模拟器 tick 内「批次->设备->状态日志」多写必须单事务原子提交，失败整体回滚（禁止半写脏状态）。
- 单写者原则：模拟器是运行数据唯一写者（agent 经工具写审批/排产除外）；API/agent 读侧不要求强一致。

## 数据规则

- **tenant_id 过滤强制**（R8）：所有业务查询带 `WHERE tenant_id=?`，新表新查询不得遗漏。
- schema 变更必须有回滚路径（down 脚本或备份兜底）。
- 种子数据脚本化可重建（`demo/simulator/seed.py`），禁止手改库。
- 密钥只在 `.env` / `docs/demo/credentials.local.md`；代码与文档永远留占位符。
- 基础设施存储（checkpoints.db/tokens.db/llm_cache.db/cache_db/chroma_db/audit.jsonl/cases.jsonl）不进 MySQL，边界见重构方案 §2.2。
