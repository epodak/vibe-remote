"""单实例锁 —— 防止多个 vRemote 进程抢占 X6 的 GATT 会话。

实测: 第二个客户端做 ATVV 特征值发现会被 X6/Windows 以 ProtocolError
(status=3, 0 个特征值) 拒绝, 且旧实例占着订阅, 双方都工作不正常。
PID 锁: .vremote.lock 记录持锁进程, 新进程启动时若持锁者仍存活则拒绝启动。
"""
import ctypes
import os

from .log import logger

_LOCK_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".vremote.lock"))
_kernel32 = ctypes.windll.kernel32
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _pid_alive(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    h = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    # 进程存活还需校验镜像名: PID 会被系统复用, 误判会永久堵死启动
    import ctypes as _ct
    buf = _ct.create_unicode_buffer(512)
    size = _ct.c_uint32(512)
    ok = _kernel32.QueryFullProcessImageNameW(h, 0, buf, _ct.byref(size))
    _kernel32.CloseHandle(h)
    if not ok:
        return True  # 查询失败时保守认为存活
    exe = buf.value.lower()
    return ("python" in exe) or ("vremote" in exe)


def acquire() -> int | None:
    """尝试取锁。返回 None=成功; 返回冲突进程 PID=已有实例在运行。"""
    try:
        with open(_LOCK_PATH, encoding="utf-8") as f:
            old = int(f.read().strip())
        if _pid_alive(old):
            return old
    except (OSError, ValueError):
        pass
    try:
        with open(_LOCK_PATH, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except OSError as e:
        logger.warning(f"单实例锁写入失败(继续运行): {e!r}")
    return None


def release():
    try:
        os.remove(_LOCK_PATH)
    except OSError:
        pass
