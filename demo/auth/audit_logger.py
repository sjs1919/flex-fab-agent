"""审计日志 -- 记录 Agent 调用的完整链路。

记录：主体(谁) / 操作(做了什么) / 目标(对谁) / 参数 / 结果摘要 / 时间戳 / Trace ID。
Trace ID 串联全链路：一个用户请求对应一个 Trace ID，所有日志都带它，
出问题按 Trace ID 查即可还原完整调用链。
"""
import json
import uuid
from datetime import datetime
from typing import Any


class AuditLogger:
    """结构化审计日志记录器。"""

    def __init__(self, log_path: str | None = None):
        # 缺口#6：log_path 当前仅内存，未落盘；后续可写 JSONL 到 log_path
        self._trace_id = uuid.uuid4().hex[:12]
        self._entries: list[dict[str, Any]] = []
        self._log_path = log_path

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
        return entry_id

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
