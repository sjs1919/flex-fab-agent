"""工具执行沙箱 -- 超时控制 + 指数退避重试 + 异常标准化（R1 缺陷修复）。

设计要点：
  - 每个工具调用包裹在沙箱中执行：超时 → 重试 → 结构化错误返回。
  - 指数退避：1s → 2s → 4s，最多 3 次。
  - 可通过 env 配置：TOOL_TIMEOUT（默认 10s）、TOOL_MAX_RETRIES（默认 3）。
  - 返回 (result: str, success: bool, retries: int) 三元组，
    让上层（registry.execute / Agent）知道执行是否成功。
  - 当前用 threading.Timer 做超时控制（跨平台），生产换 subprocess 子进程真隔离。
"""
import os
import time
import traceback
from typing import Any, Callable


TOOL_TIMEOUT = float(os.getenv("TOOL_TIMEOUT", "10"))
TOOL_MAX_RETRIES = int(os.getenv("TOOL_MAX_RETRIES", "3"))


class ToolExecutionError(Exception):
    """工具执行失败（含重试信息）。"""
    def __init__(self, tool_name: str, attempts: int, last_error: str):
        self.tool_name = tool_name
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"工具 '{tool_name}' 执行失败（{attempts} 次尝试）: {last_error}")


def run_with_retry(handler: Callable[..., Any], args: dict,
                   tool_name: str = "",
                   timeout: float | None = None,
                   max_retries: int | None = None,
                   ) -> tuple[str, bool, int]:
    """在沙箱中执行工具调用，含超时 + 指数退避重试。

    Args:
        handler: 工具函数
        args: 过滤后的参数字典
        tool_name: 工具名（日志用）
        timeout: 超时秒数，默认 TOOL_TIMEOUT
        max_retries: 最大重试次数，默认 TOOL_MAX_RETRIES

    Returns:
        (result_str, success, retries_used)
    """
    timeout = timeout if timeout is not None else TOOL_TIMEOUT
    max_retries = max_retries if max_retries is not None else TOOL_MAX_RETRIES

    last_error = ""
    for attempt in range(max_retries + 1):
        try:
            # ---- 超时控制 ----
            # 用 threading.Timer（跨平台），生产换 subprocess 子进程
            import threading
            result_container: dict[str, Any] = {}
            exception_container: dict[str, Exception | None] = {"exc": None}

            def _run():
                try:
                    result_container["value"] = handler(**args)
                except Exception as e:
                    exception_container["exc"] = e

            t = threading.Thread(target=_run, daemon=True)
            t.start()
            t.join(timeout=timeout)

            if t.is_alive():
                raise TimeoutError(f"工具执行超时（>{timeout}s）")

            if exception_container["exc"]:
                raise exception_container["exc"]

            result = result_container.get("value", "")
            return (str(result), True, attempt)

        except TimeoutError as e:
            last_error = str(e)
            if attempt < max_retries:
                wait = 2 ** attempt  # 1s, 2s, 4s
                print(f"  ⚠️  [{tool_name}] 超时，{wait}s 后重试（{attempt + 1}/{max_retries}）...")
                time.sleep(wait)
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            traceback.print_exc()
            if attempt < max_retries:
                wait = 2 ** attempt
                print(f"  ⚠️  [{tool_name}] 失败: {last_error[:80]}，{wait}s 后重试（{attempt + 1}/{max_retries}）...")
                time.sleep(wait)

    # 全部重试失败
    return (
        f"❌ 工具 '{tool_name}' 执行失败（{max_retries + 1} 次尝试均失败）\n"
        f"最后错误: {last_error}\n"
        f"建议：检查工具数据源是否正常，或换个方式提问。",
        False,
        max_retries,
    )
