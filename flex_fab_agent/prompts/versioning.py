"""Prompt 版本化（R-4，v2 C3/C8）-- 版本目录 + 加载器 + 回滚。

结构：
  prompts/versions/
    versions.json          {"current": "v1", "versions": {"v1": {desc, created}}}
    v1/system_prompt.txt   当前主 Agent 系统提示词（v1 自 system_prompts.py 原样搬出）

主 Agent（single_agent）经 load_system_prompt() 取当前版本内容；
`--rollback <version>`（main.py）调 rollback() 切 current 并写审计 prompt_rollback。
多 Agent 各角色 Prompt（review/production/supervisor）暂不入版本化（v2 范围仅主 Prompt）。
"""
import json
from pathlib import Path

_VERSIONS_DIR = Path(__file__).parent / "versions"


def _read_meta(versions_dir: Path) -> dict:
    return json.loads((versions_dir / "versions.json").read_text(encoding="utf-8"))


def load_system_prompt() -> str:
    """按 versions.json 的 current 加载当前版本系统提示词。"""
    meta = _read_meta(_VERSIONS_DIR)
    version = meta["current"]
    path = _VERSIONS_DIR / version / "system_prompt.txt"
    if not path.exists():
        raise FileNotFoundError(f"prompt 版本 {version} 缺少 system_prompt.txt: {path}")
    text = path.read_text(encoding="utf-8")
    # 文本文件按惯例以换行结尾；逻辑内容不含它（v1 与原 SINGLE_AGENT_PROMPT 逐字一致）
    return text[:-1] if text.endswith("\n") else text


def rollback(version: str, audit=None) -> str:
    """回滚到指定版本：改 versions.json 的 current，写审计 prompt_rollback。

    幂等：回滚到当前版本不报错（内容无变化）。未知版本抛 ValueError。
    """
    meta = _read_meta(_VERSIONS_DIR)
    if version not in meta["versions"]:
        raise ValueError(
            f"未知 prompt 版本：{version}（可用：{', '.join(meta['versions'])}）")
    meta["current"] = version
    (_VERSIONS_DIR / "versions.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if audit is not None:
        audit.log("prompt_rollback", "system", version, {},
                  f"当前 prompt 版本切换为 {version}")
    return version


def list_versions() -> list[dict]:
    """版本清单（调试/展示用）。"""
    meta = _read_meta(_VERSIONS_DIR)
    return [{"version": v, **info, "current": v == meta["current"]}
            for v, info in meta["versions"].items()]
