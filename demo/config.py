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


def _is_real_key(key: str) -> bool:
    """判断 key 是否为真实配置（非空、非占位符 'your-...'）。"""
    return bool(key) and "your-" not in key.lower()


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
        "api_key": os.getenv("VOLC_API_KEY", ""),
        "base_url": os.getenv("VOLC_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3"),
        "model": os.getenv("VOLC_MODEL", "ark-code-latest"),
        "note": "主用 · 字节编程套餐 · 端点 /api/coding/v3",
    },
    {
        "name": "DeepSeek",
        "enabled": True,
        "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        "note": "备用1 · ¥1/百万Token · OpenAI 兼容",
    },
    {
        "name": "Kimi(coding)",
        "enabled": os.getenv("KIMI_ENABLED", "false").lower() == "true",
        "api_key": os.getenv("KIMI_API_KEY", ""),
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

# 凭据文件：gitignored，真实口令只在此处。解析为 {占位符: 真实值}
CREDENTIALS_FILE = PROJECT_ROOT / "docs" / "demo" / "credentials.local.md"


def _parse_credentials_file(path: Path) -> dict[str, str]:
    """解析 credentials.local.md（markdown 表格）为 {占位符: 真实值}。

    表格行格式：`| {{KEY}} | 用途 | 值 |`。文件缺失/格式不符时返回空 dict，
    调用方（get_mysql_dsn）据此给中文报错提示（验收清单 M1-1）。
    """
    creds: dict[str, str] = {}
    if not path.exists():
        return creds
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|") or "{{" not in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        key = cells[0].strip("`{}").strip()
        value = cells[2].strip()
        if key and value and value not in ("（填入）", "（未用）"):
            creds[key] = value
    return creds


# 模块级缓存：启动读一次（v2 C4 约定），测试用 monkeypatch 覆盖
_CREDENTIALS: dict[str, str] = _parse_credentials_file(CREDENTIALS_FILE)


def get_data_source() -> str:
    """当前数据源：csv | mysql。实时读 env（测试可 monkeypatch）。"""
    return os.getenv("DEMO_DATA_SOURCE", "csv")


def get_mysql_dsn() -> str:
    """合成 MySQL DSN（口令来自 credentials.local.md）。

    口令缺失时抛中文报错提示填写凭据文件（验收清单 M1-1：缺连接串时报错）。
    """
    password = _CREDENTIALS.get("MYSQL_PASSWORD", "")
    if not password:
        raise RuntimeError(
            "缺少 MySQL 口令：请填写 docs/demo/credentials.local.md 的 {{MYSQL_PASSWORD}}（gitignored，不提交）"
        )
    host = _CREDENTIALS.get("MYSQL_HOST", "127.0.0.1")
    port = _CREDENTIALS.get("MYSQL_PORT", "3306")
    db = _CREDENTIALS.get("MYSQL_DB", "demo_scheduling")
    user = _CREDENTIALS.get("MYSQL_USER", "demo_sched")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{db}?charset=utf8mb4"


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
    from .cache import llm_cache
    return llm_cache.get_scene_version()
