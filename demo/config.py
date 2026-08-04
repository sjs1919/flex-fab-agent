"""配置中心 -- 统一加载 .env + 集中 Provider 注册表。

为什么单列 config：
  week1/2/3 各自维护了一份 PROVIDERS（重复 3 份），改主备顺序要改三处。
  集中到这里后，全项目只此一处 provider 配置，是主备架构的单一事实源。
  调主备 = 改下面 PROVIDERS 列表顺序 + 同步 .env 注释，无需动业务代码。
"""
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


def available_providers() -> list[dict]:
    """返回当前可用的 provider 列表（已启用 + key 已配置）。"""
    return [p for p in PROVIDERS if p.get("enabled") and _is_real_key(p["api_key"])]
