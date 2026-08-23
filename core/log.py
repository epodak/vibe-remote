"""loguru 统一日志: 控制台精简格式 + logs/ 目录按天轮转文件 (DEBUG 级全量)。

排查现场就看 logs/vremote_YYYY-MM-DD.log —— 所有模块的完整运行轨迹都在。
"""
import os
import sys

from loguru import logger

LOG_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "logs"))
os.makedirs(LOG_DIR, exist_ok=True)

logger.remove()
logger.add(
    sys.stderr, level="INFO", colorize=True,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | {message}")
logger.add(
    os.path.join(LOG_DIR, "vremote_{time:YYYY-MM-DD}.log"), level="DEBUG",
    rotation="10 MB", retention="7 days", encoding="utf-8", enqueue=True,
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <7} | {name}:{function}:{line} | {message}")

__all__ = ["logger"]
