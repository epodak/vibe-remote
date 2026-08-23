"""loguru 统一日志: 控制台精简格式 + logs/ 目录按天轮转文件 (DEBUG 级全量)。

排查现场就看 logs/vremote_YYYY-MM-DD.log —— 所有模块的完整运行轨迹都在。
"""
import os
import sys

from loguru import logger


def _resolve_log_dir() -> str:
    """自适应获取日志存放目录 (兼顾源码运行与 PyInstaller 打包运行态)。"""
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(base_dir, "logs")


def setup_logger():
    """初始化并配置全局 logger。"""
    log_dir = _resolve_log_dir()
    os.makedirs(log_dir, exist_ok=True)

    logger.remove()

    # 防御 PyInstaller windowed 模式下 sys.stderr 为 None 导致 loguru 抛 TypeError: Cannot log to objects of type 'NoneType'
    if sys.stderr is not None:
        try:
            logger.add(
                sys.stderr, level="INFO", colorize=True,
                format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | {message}")
        except Exception:
            pass

    logger.add(
        os.path.join(log_dir, "vremote_{time:YYYY-MM-DD}.log"), level="DEBUG",
        rotation="10 MB", retention="7 days", encoding="utf-8", enqueue=True,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <7} | {name}:{function}:{line} | {message}")
    return log_dir


LOG_DIR = setup_logger()

__all__ = ["logger", "LOG_DIR", "setup_logger"]

