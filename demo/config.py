"""配置中心 -- 统一加载 .env + 集中 Provider 注册表。

为什么单列 config：
  week1/2/3 各自维护了一份 PROVIDERS（重复 3 份），改主备顺序要改三处。
  集中到这里后，全项目只此一处 provider 配置，是主备架构的单一事实源。
  调主备 = 改下面 PROVIDERS 列表顺序 + 同步 .env 注释，无需动业务代码。
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

# agent-training 根目录（demo 的上一级），.env 在这里
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# 数据目录（demo/data/）-- 工具层和 RAG 层都从这里读
DATA_DIR = Path(__file__).resolve().parent / "data"

# 运行时数据目录：checkpoints.db / cache_db / chroma_db 落此处。
# 默认同 DATA_DIR（宿主跑行为不变）；容器内设 DEMO_RUNTIME_DIR 指向挂载卷，
# 与 bake 进镜像的业务数据（csv/contracts）分离，卷持久化跨容器重建。
RUNTIME_DIR = Path(os.getenv("DEMO_RUNTIME_DIR", str(DATA_DIR)))

# 凭据文件：gitignored，真实口令只在此处。解析为 {占位符: 真实值}
CREDENTIALS_FILE = PROJECT_ROOT / "docs" / "demo" / "credentials.local.md"


def _parse_credentials_file(path: Path) -> dict[str, str]:
    """解析 credentials.local.md（markdown 表格）为 {占位符: 真实值}。

    按表头列名取值（行 → dict，用 key 访问），列顺序/列数变化不影响解析。
    文件缺失/格式不符时返回空 dict，调用方据此给中文报错提示。
    """
    creds: dict[str, str] = {}
    if not path.exists():
        return creds

    lines = path.read_text(encoding="utf-8").splitlines()
    headers: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]

        # 跳过分隔行（|---|---|）
        if all(set(c) <= set("-: ") for c in cells):
            continue

        # 第一行有效表格行 = 表头
        if not headers:
            headers = cells
            continue

        # 数据行不足列数跳过
        if len(cells) < len(headers):
            continue

        # 行 → dict，按列名 key 访问
        row = dict(zip(headers, cells))
        placeholder = row.get("占位符", "")
        value = row.get("真实值", "")

        if "{{" not in placeholder:
            continue
        key = placeholder.strip("`{}").strip()
        if key and value and value not in ("（填入）", "（未用）"):
            creds[key] = value

    return creds


# 模块级缓存：启动读一次（v2 C4 约定），测试用 monkeypatch 覆盖
_CREDENTIALS: dict[str, str] = _parse_credentials_file(CREDENTIALS_FILE)


def _is_real_key(key: str) -> bool:
    """判断 key 是否为真实配置（非空、非占位符 'your-...'）。"""
    return bool(key) and "your-" not in key.lower()


def _cred(name: str, default: str = "") -> str:
    """读 credentials.local.md 中的占位符值，缺省返回 default。

    命名约定：占位符 `{{MYSQL_PASSWORD}}` 对应 key 名 `MYSQL_PASSWORD`
    （调用方去掉花括号，与环境变量同名，便于 env ↔ creds 双源切换）。
    """
    return _CREDENTIALS.get(name, default) or default


def _env_or_cred(env_key: str, cred_key: str = "", default: str = "") -> str:
    """优先读环境变量，环境变量为空或占位符时回落 credentials.local.md。

    开发态：.env 直接写真实值 → 走 env 路径，方便。
    部署态：.env 留空或写 your-xxx → 走 cred 路径，敏感信息与代码分离。
    两者都没配 → 返回 default。
    """
    env_val = os.getenv(env_key, "")
    if _is_real_key(env_val):
        return env_val
    cred_val = _cred(cred_key or env_key, "")
    if _is_real_key(cred_val):
        return cred_val
    return default


# Provider 注册表：列表顺序即 fallback 顺序，第一个成功即返回。
# 三家均为 OpenAI 兼容协议，代码层只差 base_url + api_key + model。
# 新增 provider 只需在此追加一项，全项目自动支持。
# 主备切换：设 PRIMARY_PROVIDER 环境变量（如 "DeepSeek"）可把指定 provider
# 提到列表最前，无需改代码。火山豆包配额恢复后 unset 即可回到默认顺序。
PRIMARY_PROVIDER = os.getenv("PRIMARY_PROVIDER", "")
PROVIDERS = [
    {
        "name": "火山豆包(coding)",
        "enabled": True,
        "api_key": _env_or_cred("VOLC_API_KEY", "VOLC_API_KEY"),
        "base_url": os.getenv("VOLC_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3"),
        "model": os.getenv("VOLC_MODEL", "ark-code-latest"),
        "note": "主用 · 字节编程套餐 · 端点 /api/coding/v3",
    },
    {
        "name": "DeepSeek",
        "enabled": True,
        "api_key": _env_or_cred("DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"),
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        "note": "备用1 · ¥1/百万Token · OpenAI 兼容",
    },
    {
        "name": "Kimi(coding)",
        "enabled": os.getenv("KIMI_ENABLED", "false").lower() == "true",
        "api_key": _env_or_cred("KIMI_API_KEY", "KIMI_API_KEY"),
        "base_url": os.getenv("KIMI_BASE_URL", "https://api.kimi.com/coding/v1"),
        "model": os.getenv("KIMI_MODEL", "kimi-for-coding"),
        "note": "备用2 · 会员过期暂禁用 · 续费改 KIMI_ENABLED=true",
    },
]

if PRIMARY_PROVIDER:
    for i, p in enumerate(PROVIDERS):
        if p["name"] == PRIMARY_PROVIDER and i != 0:
            PROVIDERS.insert(0, PROVIDERS.pop(i))
            break


def available_providers() -> list[dict]:
    """返回当前可用的 provider 列表（已启用 + key 已配置）。"""
    return [p for p in PROVIDERS if p.get("enabled") and _is_real_key(p["api_key"])]


# ---- M1 数据源扩展（v2 重构方案 A1/C4/F 组）----

# 数据源：csv（默认，CSV 兜底）| mysql（MySQL 业务库，WSL）
DEMO_DATA_SOURCE = os.getenv("DEMO_DATA_SOURCE", "csv")

# ============================================================
# 全局配置集中导出（各模块一律 from .config import XXX，不直接 os.getenv）
# 非敏感配置走环境变量；敏感配置走 _env_or_cred（支持 credentials 回落）
# ============================================================

# ---- 缓存 ----
LLM_CACHE = os.getenv("LLM_CACHE", "on")
LLM_CACHE_TTL = int(os.getenv("LLM_CACHE_TTL", "3600"))
SEMANTIC_CACHE = os.getenv("SEMANTIC_CACHE", "on")
CACHE_THRESHOLD = float(os.getenv("CACHE_THRESHOLD", "0.25"))
# 语义缓存 TTL（秒）：只对状态类（订单/状态/进度等）做短缓存；知识类保持不过期（0），行为不变
SEMANTIC_CACHE_TTL = int(os.getenv("SEMANTIC_CACHE_TTL", "0"))  # 知识类，0 = 不过期（现状）
SEMANTIC_CACHE_STATE_TTL = int(os.getenv("SEMANTIC_CACHE_STATE_TTL", "60"))  # 状态类，默认对齐模拟器 tick(60s)

# ---- LLM 预算 ----
LLM_BUDGET_LIMIT = float(os.getenv("LLM_BUDGET_LIMIT", "5.0"))
LLM_BUDGET_WARN = float(os.getenv("LLM_BUDGET_WARN", "0.8"))

# ---- 图 / 上下文 ----
CHECKPOINTER = os.getenv("CHECKPOINTER", "sqlite")
CONTEXT_MAX_CHARS = int(os.getenv("CONTEXT_MAX_CHARS", "8000"))
CONTEXT_KEEP_RECENT = int(os.getenv("CONTEXT_KEEP_RECENT", "6"))
CONTEXT_COMPRESS_CHUNK = int(os.getenv("CONTEXT_COMPRESS_CHUNK", "10"))

# ---- 工具 ----
TOOL_TIMEOUT = float(os.getenv("TOOL_TIMEOUT", "10"))
TOOL_MAX_RETRIES = int(os.getenv("TOOL_MAX_RETRIES", "3"))
MCP_MODE = os.getenv("MCP_MODE", "local")  # local | mcp

# ---- 安全 / 鉴权 ----
GUARDRAILS_MODE = os.getenv("GUARDRAILS_MODE", "warn")  # block | warn | off
FORCE_TENANT = os.getenv("FORCE_TENANT", "false")
TOKEN_STORE = os.getenv("TOKEN_STORE", "sqlite")  # sqlite | redis
WRITE_QUOTA_LIMIT = int(os.getenv("WRITE_QUOTA_LIMIT", "3"))
WRITE_QUOTA_WINDOW = float(os.getenv("WRITE_QUOTA_WINDOW", "300"))
AUDIT_LOG = os.getenv("AUDIT_LOG", "on")
AUDIT_LOG_PATH = os.getenv("AUDIT_LOG_PATH", "")  # 空 = 默认 RUNTIME_DIR/audit.jsonl

# ---- 模拟器 ----
SIM_TICK_SECONDS = float(os.getenv("SIM_TICK_SECONDS", "60"))

# ---- 自动排产调度器 ----
AUTO_SCHEDULE_ENABLED = os.getenv("AUTO_SCHEDULE_ENABLED", "on")      # off 关闭自动排产
AUTO_SCHEDULE_TICK_INTERVAL = int(os.getenv("AUTO_SCHEDULE_TICK_INTERVAL", "3"))  # 每 N tick 排一轮
AUTO_APPROVE_TOP_N = int(os.getenv("AUTO_APPROVE_TOP_N", "5"))         # 保留最近 N 个待审核版本，更早自动通过（定稿：20→5）
FIFO_AGE_TIMEOUT = float(os.getenv("FIFO_AGE_TIMEOUT", "24"))           # 最早待审版本超龄兜底阈值（模拟小时，定稿 §3.D）

# ---- 可观测性 ----
OTEL_EXPORTER = os.getenv("OTEL_EXPORTER", "console")  # none | console | otel
OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")


def get_data_source() -> str:
    """当前数据源：csv | mysql。实时读 env（测试可 monkeypatch）。"""
    return os.getenv("DEMO_DATA_SOURCE", "csv")


def get_mysql_dsn() -> str:
    """合成 MySQL DSN（口令来自 env 或 credentials.local.md）。

    用 _env_or_cred（env 优先）：容器部署无凭据文件时，凭环境变量注入口令。
    口令缺失时抛中文报错提示填写凭据文件（验收清单 M1-1：缺连接串时报错）。
    """
    password = _env_or_cred("MYSQL_PASSWORD", "MYSQL_PASSWORD", "")
    if not password:
        raise RuntimeError(
            "缺少 MySQL 口令：请填写 docs/demo/credentials.local.md 的 {{MYSQL_PASSWORD}}（gitignored，不提交）或设置 MYSQL_PASSWORD 环境变量"
        )
    host = _env_or_cred("MYSQL_HOST", "MYSQL_HOST", "127.0.0.1")
    port = _env_or_cred("MYSQL_PORT", "MYSQL_PORT", "3306")
    db = _env_or_cred("MYSQL_DB", "MYSQL_DB", "demo_scheduling")
    user = _env_or_cred("MYSQL_USER", "MYSQL_USER", "demo_sched")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{db}?charset=utf8mb4"


def get_redis_config() -> dict:
    """Redis 连接配置（host/port/password/db），口令来自 env 或 credentials.local.md。

    未配置口令时 password=None（Redis 无认证）。
    """
    return {
        "host": _env_or_cred("REDIS_HOST", "REDIS_HOST", "127.0.0.1"),
        "port": int(_env_or_cred("REDIS_PORT", "REDIS_PORT", "6379")),
        "password": _env_or_cred("REDIS_PASSWORD", "REDIS_PASSWORD", "") or None,
        "db": int(_env_or_cred("REDIS_DB", "REDIS_DB", "0")),
    }


def get_config(category: str, key: str, default: str = "") -> str:
    """读 system_config 表（v2 C4 / §6 配置表）。未配置或读库失败回落 default。

    惰性导入 data 层避免循环依赖；调用方按需转换类型（int/float/bool）。
    """
    try:
        from .tools.data import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT value FROM system_config WHERE category=%s AND `key`=%s",
                    (category, key))
                row = cur.fetchone()
    except Exception:
        return default
    return row[0] if row and row[0] is not None else default


def set_config(category: str, key: str, value: str) -> None:
    """写 system_config（upsert，M6 T6.6 /config PUT 用）。写失败向上抛。"""
    from .tools.data import get_connection
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO system_config (category, `key`, value) VALUES (%s, %s, %s) "
                "ON DUPLICATE KEY UPDATE value=VALUES(value)",
                (category, key, value))
        conn.commit()


def get_routing_policy() -> dict:
    """B3 模型路由策略（v2 C7）：system_config 路由/routing_policy 的 JSON
    （如 {"simple": "DeepSeek", "complex": "火山豆包(coding)"}）。异常回落 {}。"""
    raw = get_config("路由", "routing_policy", "{}")
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {}
    except (TypeError, ValueError):
        return {}


def get_scene_version() -> int:
    """R-3：当前 scene_version（llm_cache 单调递增，模拟器每 tick bump）。"""
    from .cache.manager import cache_manager
    return cache_manager.get_scene_version()
