"""写工具配额（R-D2）-- 同 subject 对同一写工具 5min 滑窗内最多 N 次。

v2 §6 配置项 `write_quota_per_window` 默认 3 次/5min；上限/窗口可用环境变量
WRITE_QUOTA_LIMIT / WRITE_QUOTA_WINDOW 覆盖（system_config 表接线在 T4a.5）。

拒绝路径在 guard（洋葱顺序 token -> RBAC -> 配额 -> execute），
拒绝时写审计 `quota_exceeded` + tracer span，见 guard.check_tool_permission。
"""
import os
import time
from collections import defaultdict, deque

DEFAULT_LIMIT = 3
DEFAULT_WINDOW_SECONDS = 300.0


class WriteQuota:
    """内存滑窗计数器（subject, tool）-> 时间戳队列。demo 单进程足够。"""

    def __init__(self, limit: int | None = None, window: float | None = None):
        self.limit = limit if limit is not None else int(
            os.getenv("WRITE_QUOTA_LIMIT", str(DEFAULT_LIMIT)))
        self.window = window if window is not None else float(
            os.getenv("WRITE_QUOTA_WINDOW", str(DEFAULT_WINDOW_SECONDS)))
        self._calls: dict[tuple[str, str], deque] = defaultdict(deque)

    def check_and_consume(self, subject: str, tool_name: str) -> tuple[bool, str]:
        """放行则计数并返回 (True, "ok")；超限不计数，返回 (False, 原因)。"""
        now = time.time()
        q = self._calls[(subject, tool_name)]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False, (
                f"配额超限：{subject} 在 {int(self.window / 60)} 分钟内对 "
                f"{tool_name} 已执行 {len(q)} 次写操作（上限 {self.limit}，R-D2）"
            )
        q.append(now)
        return True, "ok"

    def reset(self) -> None:
        self._calls.clear()


write_quota = WriteQuota()
