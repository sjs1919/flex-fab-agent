"""logging 统一配置 — 入口调用一次即可。

为什么独立文件：各入口（main.py / api.py / eval runner）都需要初始化
logging 格式和级别，避免复制粘贴。

用法：
    from .core.logging_setup import setup_logging
    setup_logging()  # 入口处调用一次

环境变量 LOG_LEVEL 控制级别（默认 INFO）：DEBUG / INFO / WARNING / ERROR
"""
import logging
import os


def setup_logging(level: str | None = None) -> None:
    """配置根 logger 的格式和级别。

    多次调用幂等（通过检查 handler 是否已存在）。
    level 参数优先于 LOG_LEVEL 环境变量。
    """
    root = logging.getLogger()

    # 幂等：已经配置过就不重复加 handler
    if root.handlers:
        if level:
            root.setLevel(level.upper())
        return

    log_level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    root.setLevel(log_level)

    handler = logging.StreamHandler()
    handler.setLevel(log_level)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)
