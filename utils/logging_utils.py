"""
GUI 元素探查器 - 日志工具模块

提供统一的日志配置。
遵循 DEVELOPMENT-METHOD.md 第 9.2 节日志规范：
- 关键链路必须记录日志
- 日志级别：DEBUG / INFO / WARNING / ERROR / CRITICAL
- 日志中不得出现敏感信息原文
"""

import logging
import os
from datetime import datetime


LOG_DIR = os.path.join(os.path.expanduser("~"), ".gui_inspector", "logs")


def _ensure_log_dir() -> None:
    """确保日志目录存在"""
    os.makedirs(LOG_DIR, exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    """
    获取指定名称的 logger。

    Args:
        name: 模块名称，通常传 __name__

    Returns:
        配置好的 logging.Logger 实例
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    _ensure_log_dir()
    log_file = os.path.join(
        LOG_DIR, f"inspector_{datetime.now().strftime('%Y%m%d')}.log"
    )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_fmt)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(file_fmt)
    logger.addHandler(console_handler)

    return logger