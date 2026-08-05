"""审计日志 -- 记录 Agent 调用的完整链路。

记录：主体(谁) / 操作(做了什么) / 目标(对谁) / 参数 / 结果摘要 / 时间戳 / Trace ID。
Trace ID 串联全链路：一个用户请求对应一个 Trace ID，所有日志都带它，
出问题按 Trace ID 查即可还原完整调用链。

持久化：默认写入 {RUNTIME_DIR}/audit.jsonl（JSONL 格式，一行一条记录）。
设 AUDIT_LOG=none 可切回纯内存模式（测试/调试用）。
"""
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


def _resolve_log_path() -> Path | None:
    """解析审计日志持久化路径。"""
    mode = os.getenv("AUDIT_LOG", "").lower()
    if mode == "none":
        return None
    from ..config import RUNTIME_DIR
    custom = os.getenv("AUDIT_LOG_PATH", "")
    return Path(custom) if custom else RUNTIME_DIR / "audit.jsonl"


class AuditLogger:
    """结构化审计日志记录器。"""

    def __init__(self, log_path: str | None = None):
        self._trace_id = uuid.uuid4().hex[:12]
        self._entries: list[dict[str, Any]] = []
        # 优先使用传入路径，其次环境变量，最后默认 RUNTIME_DIR/audit.jsonl
        self._log_path = log_path or str(_resolve_log_path()) if _resolve_log_path() else None

    @property
    def trace_id(self) -> str:
        return self._trace_id

    def log(self, action: str, subject: str, target: str,
            params: dict | None = None, result: str = "", level: str = "INFO") -> str:
        entry_id = uuid.uuid4().hex[:8]
        entry = {
            "id": entry_id,
            "trace_id": self._trace_id,
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "action": action,
            "subject": subject,
            "target": target,
            "params": params or {},
            "result_summary": result[:200],
        }
        self._entries.append(entry)
        print(f"[审计] [{self._trace_id}] {action} -> {target} ({level})")
        # 持久化写入：每条记录即时追加到 JSONL 文件
        self._persist(entry)
        return entry_id

    def _persist(self, entry: dict[str, Any]) -> None:
        """追加一条记录到 JSONL 文件。"""
        if not self._log_path:
            return
        try:
            Path(self._log_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as e:
            print(f"[审计] 写入失败: {e}")

    def get_report(self) -> str:
        """生成审计报告。"""
        if not self._entries:
            return "本次调用无审计记录。"
        lines = [
            f"🔍 审计报告 (Trace: {self._trace_id})",
            f"  调用次数：{len(self._entries)}",
            f"  时间范围：{self._entries[0]['timestamp']} ~ {self._entries[-1]['timestamp']}",
            "",
        ]
        for e in self._entries:
            lines.append(f"  [{e['level']}] {e['action']} -> {e['target']} @ {e['timestamp'][:19]}")
            if e["params"]:
                lines.append(f"       参数: {json.dumps(e['params'], ensure_ascii=False)[:100]}")
        return "\n".join(lines)