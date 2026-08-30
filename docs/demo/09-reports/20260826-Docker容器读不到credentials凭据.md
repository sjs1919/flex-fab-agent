# Docker 容器部署读不到 credentials.local.md：`_cred` vs `_env_or_cred`

> **日期**：2026-08-26
> **环境**：WSL2 Docker 部署 demo-api，mysql 数据源
> **结论**：MySQL/Redis 连接口令必须用 `_env_or_cred`（env 优先），不能用 `_cred`（只读凭据文件）——容器里没有 `docs/demo/credentials.local.md`，`_cred` 必然读空。

---

## 现象

- 容器部署（`docker compose up`）后，`/kpi`、`/schedule/latest`、`/sim/start` 全部 500
- 容器日志：

```
File "/app/demo/api.py", line 148, in sim_start
    with get_connection() as conn:
RuntimeError: 缺少 MySQL 口令：请填写 docs/demo/credentials.local.md 的 {{MYSQL_PASSWORD}}（gitignored，不提交）
```

- 但容器内 `env` 明明有 `MYSQL_PASSWORD`（经 compose `env_file: .env` 注入）
- `/health`、`/config` 正常（不连 MySQL 的路径 OK）

## 根因

`demo/config.py` 有两个读凭据的函数，行为不同：

| 函数 | 行为 | 容器场景 |
|------|------|---------|
| `_cred(name)` | 只读 `credentials.local.md` 文件（`_CREDENTIALS` dict） | ❌ 容器无此文件 → 返回空 |
| `_env_or_cred(env_key, cred_key)` | **先读环境变量**，为空/占位符才回落凭据文件 | ✅ 读到 compose 注入的 env |

`get_mysql_dsn()` 和 `get_redis_config()` 用的是 `_cred`，容器里 `_CREDENTIALS` 为空 → 口令必空 → 抛「缺少 MySQL 口令」。

其它敏感配置（VOLC_API_KEY / DEEPSEEK_API_KEY 等）一直用 `_env_or_cred`，所以没踩这个坑——**MySQL/Redis 是漏改的少数派**。

## 复现验证（容器内）

```bash
docker exec demo-api python -c "
from demo.config import _cred, _env_or_cred, get_mysql_dsn, _CREDENTIALS
print(len(_CREDENTIALS))                    # 0（无凭据文件）
print(repr(_cred('MYSQL_PASSWORD','')))     # ''（读不到）
print(repr(_env_or_cred('MYSQL_PASSWORD','MYSQL_PASSWORD','')))  # 'w9Ab***'（env 生效）
get_mysql_dsn()                             # 抛 '缺少 MySQL 口令'
"
```

## 修复

`demo/config.py`：`get_mysql_dsn()` / `get_redis_config()` 里所有 `_cred(...)` 改为 `_env_or_cred(KEY, KEY, default)`。

```python
# 改前
password = _cred("MYSQL_PASSWORD", "")
# 改后（env 优先，容器友好）
password = _env_or_cred("MYSQL_PASSWORD", "MYSQL_PASSWORD", "")
```

## 配套（容器部署时）

- 凭据经 compose `env_file: .env` 注入（.env gitignored，不入库）
- `docker-compose.yml` 加 `extra_hosts: host.docker.internal:host-gateway` + `MYSQL_HOST=host.docker.internal`（容器内 127.0.0.1 是容器自身，不是宿主 MySQL）
- Dockerfile 只 `COPY demo/`，`docs/` 不在镜像里——所以容器**不可能**走 `_cred` 文件路径，只能走 env

## 经验

1. 部署态敏感信息统一走 env 注入；凭据文件机制只服务本机/开发态
2. 新写敏感配置读取，一律用 `_env_or_cred`（`_cred` 只在明确只读文件时用）
3. 容器部署后先冒烟（S2/S3 会暴露数据层连接问题），别只看 /health
