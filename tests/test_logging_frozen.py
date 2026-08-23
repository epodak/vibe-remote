"""无控制台/打包环境下的日志系统健壮性测试 (INC-04)。

验证目标 (不需要真机 / 锁住 INC-04 不复发):
  1. 当 sys.stderr 为 None 时 (PyInstaller console=False / windowed 模式)，
     模块加载与 setup_logger() 不会抛出 TypeError: Cannot log to objects of type 'NoneType';
  2. 当 sys.stdout / sys.stderr 均为 None 时，文件日志仍可正常写入且目录自适应;
  3. 当 sys.frozen = True 时，日志路径自动基于可执行文件基准目录解析。

运行: python vRemote_win/tests/test_logging_frozen.py
"""

import importlib
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from core import log


class TestLoggingFrozen(unittest.TestCase):

    def test_logger_with_none_stderr(self):
        """模拟 PyInstaller windowed 模式 (sys.stderr is None)"""
        orig_stderr = sys.stderr
        orig_stdout = sys.stdout
        try:
            sys.stderr = None
            sys.stdout = None

            # 重新调用 setup_logger，确保无异常
            log_dir = log.setup_logger()
            self.assertTrue(os.path.exists(log_dir))

            # 测试写入日志不会崩溃
            log.logger.info("Test message with None stderr")
            log.logger.debug("Debug message with None stderr")
        finally:
            sys.stderr = orig_stderr
            sys.stdout = orig_stdout

    def test_frozen_path_resolution(self):
        """测试打包模式下的路径解析"""
        orig_frozen = getattr(sys, "frozen", False)
        orig_exe = sys.executable
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                fake_exe = os.path.join(tmpdir, "vibe-remote.exe")
                sys.frozen = True
                sys.executable = fake_exe

                resolved = log._resolve_log_dir()
                expected = os.path.join(tmpdir, "logs")
                self.assertEqual(os.path.normpath(resolved), os.path.normpath(expected))
            finally:
                if not orig_frozen and hasattr(sys, "frozen"):
                    delattr(sys, "frozen")
                sys.executable = orig_exe


if __name__ == "__main__":
    unittest.main()
