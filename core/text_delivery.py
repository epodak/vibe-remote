"""文本投递 (Windows 实现): 剪贴板 + 粘贴 + 气泡通知。

设计决策 (对应"光标不在可输入处"的需求):
  跨应用可靠检测"焦点是否可输入"做不到 (浏览器/自绘 UI 无统一标志),
  因此采用「先剪贴板、后粘贴」策略 —— 两分支天然覆盖:
    · 焦点可输入 -> Ctrl+V 直接上屏
    · 焦点不可输入 -> 粘贴落空, 但文本已在剪贴板, 气泡通知告知用户
  任何情况下语音文本都不会丢失。
"""
import ctypes
import threading
import time
from ctypes import wintypes

from . import key_injector, user_settings
from .log import logger
from .hud_toast import show_hud

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
VK_CONTROL = 0x11
VK_V = 0x56

user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]


def set_clipboard_text(text: str) -> bool:
    if not text:
        return False
    if not user32.OpenClipboard(None):
        return False
    try:
        user32.EmptyClipboard()
        buf = ctypes.create_unicode_buffer(text)
        size = ctypes.sizeof(buf)
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not h:
            return False
        ptr = kernel32.GlobalLock(h)
        if not ptr:
            return False
        ctypes.memmove(ptr, buf, size)
        kernel32.GlobalUnlock(h)
        return bool(user32.SetClipboardData(CF_UNICODETEXT, h))
    finally:
        user32.CloseClipboard()


def get_clipboard_text() -> str:
    if not user32.OpenClipboard(None):
        return ""
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return ""
        ptr = kernel32.GlobalLock(h)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def deliver(text: str, paste: bool | None = None):
    """剪贴板 -> 粘贴 -> 优雅 HUD 提醒。返回是否成功写入剪贴板。

    paste=None 时读用户偏好 auto_paste (默认开)。若开启 restore_clipboard,
    粘贴完成后把用户原来的剪贴板内容还回去 —— 转写文本只是"过路",
    不再霸占剪贴板 (代价: 粘贴失败时文本不会留在剪贴板, 故默认关闭)。
    """
    if paste is None:
        paste = bool(user_settings.get("auto_paste", True))
    restore = bool(user_settings.get("restore_clipboard", False)) and paste
    prev = get_clipboard_text() if restore else None

    if not set_clipboard_text(text):
        logger.error("❌ 写入剪贴板失败")
        show_hud("写入剪贴板失败", "转写文本未能送达", duration_ms=2600, accent="red")
        return False

    preview = text if len(text) <= 60 else text[:60] + "…"
    if paste:
        key_injector.pulse([VK_CONTROL, VK_V], hold=0.05)
        if restore and prev:
            # 让目标应用先消费完粘贴事件, 再把原内容还回剪贴板
            threading.Timer(0.45, lambda: set_clipboard_text(prev)).start()

    show_hud("文字已复制并粘贴" if paste else "文字已复制到剪贴板",
             preview, duration_ms=1800, accent="green")
    logger.info(f"📋 已投递文本 ({len(text)}字, {'自动粘贴' if paste else '仅剪贴板'}): {preview}")
    return True


# ================= 转写过程 HUD 阶段 (对应 vokie 原生 UI 的过程态) =================

def hud_recording():
    """会话开始: 录音中提示 —— 常驻整个会话 (被下一阶段消息顶替, 不自动消失)。"""
    show_hud("录音中", "再按一下语音键结束", duration_ms=600_000, accent="red")


def hud_session_stopping():
    """会话结束: 立即顶掉常驻的录音胶囊, 随后被转写心跳接管。"""
    show_hud("录音结束", "正在保存并准备转写…", duration_ms=2000, accent="teal")


class TranscribeTicker:
    """转写过程 HUD 心跳: 每 300ms 刷新已耗时, 让后台转写过程显式可见。

    vokie 的 offline2pass 是同步接口 (无 job/progress 端点, 实测 404),
    因此用本端墙钟计时呈现过程; 每次刷新都重置胶囊, 形成跳动的秒表效果。
    """

    def __init__(self, label: str = "vokie 转写中"):
        self._stop = threading.Event()
        self._label = label
        self._t0 = time.time()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while not self._stop.wait(0.3):
            show_hud(self._label, f"{time.time() - self._t0:.1f}s",
                     duration_ms=2000, accent="teal")

    def stop(self):
        self._stop.set()
