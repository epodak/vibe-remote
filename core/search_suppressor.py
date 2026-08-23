"""系统级按键抑制器 (WH_KEYBOARD_LL) + 设备源仲裁接线。

2026-08-23 重构 —— 修复 ISSUE-01「全局钩子误伤 PC 原生键盘」:

旧版对 X6 与原生键盘一视同仁, `viewer3d` 预设把 Enter/Backspace/Esc 映射成
鼠标动作后, 用户的物理键盘同名键全部被 `return 1` 当场吞噬。
新版每一个事件都先过 `device_source.arbiter` 裁决来源:

    remote  -> 走映射引擎 (拦截/注入鼠标)
    native  -> 原样透传, 且不进事件流 (顺带解决"记录用户全部击键"的隐私问题)
    unknown -> 看 X6 活跃门控; 判为 remote 且真吞了就登记补偿重放,
               Raw Input 事后证否时自动把按键补回系统

另新增紧急逃生口: Ctrl+Alt+F12 一键切换全局拦截总开关 —— 万一仲裁失效,
用户不必杀进程就能立刻拿回键盘。
"""

import ctypes
import threading
from ctypes import wintypes

from .device_source import SOURCE_NATIVE, SOURCE_REMOTE, arbiter
from .log import logger

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

VK_BROWSER_SEARCH = 0xAA  # 170 (X6 语音键)
VK_LAUNCH_APP1 = 0xB6     # 182 ("e" 键)
VK_LAUNCH_APP2 = 0xB7     # 183

# 紧急逃生热键: Ctrl + Alt + F12 切换拦截总开关
VK_F12 = 0x7B
VK_CONTROL = 0x11
VK_MENU = 0x12

LLKHF_EXTENDED = 0x01
LLKHF_INJECTED = 0x10

HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

WM_QUIT = 0x0012

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK

user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL

user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_longlong

user32.GetAsyncKeyState.argtypes = [wintypes.INT]
user32.GetAsyncKeyState.restype = wintypes.SHORT


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulonglong)
    ]


class SearchSuppressor:
    """系统级按键静默抑制器 (对齐 macOS vRemote X6SearchSuppressor)。

    on_key_event(vk, is_down) -> bool: 其余按键的映射裁决回调
    (KeyMapper.handle_hook_key)。返回 True = 拦截, False = 透传。
    注入事件 (LLKHF_INJECTED) 一律跳过裁决, 防自锁与重放回环。
    """

    def __init__(self, on_voice_down=None, on_voice_up=None, on_key_event=None,
                 on_intercept_toggled=None):
        self.on_voice_down = on_voice_down
        self.on_voice_up = on_voice_up
        self.on_key_event = on_key_event
        self.on_intercept_toggled = on_intercept_toggled
        self.h_hook = None
        self.hook_thread = None
        self._callback = HOOKPROC(self._hook_proc)
        self.is_running = False
        self.intercept_enabled = True   # 紧急逃生开关 (Ctrl+Alt+F12)

    # ---------------- 总开关 ----------------

    def set_intercept_enabled(self, on: bool):
        if on == self.intercept_enabled:
            return
        self.intercept_enabled = on
        logger.info(f"  🛡️ [SearchSuppressor] 全局拦截已{'恢复' if on else '暂停'}"
                    f"{'' if on else ' —— 所有按键原样透传 (Ctrl+Alt+F12 恢复)'}")
        if self.on_intercept_toggled:
            try:
                self.on_intercept_toggled(on)
            except Exception:
                pass

    def _check_escape_hotkey(self, vk: int, is_down: bool) -> bool:
        """Ctrl+Alt+F12: 切换拦截总开关。返回 True = 该事件已被消费。"""
        if vk != VK_F12:
            return False
        if not is_down:
            return True  # 吞掉配对的 up, 避免半个组合键漏给系统
        ctrl = user32.GetAsyncKeyState(VK_CONTROL) & 0x8000
        alt = user32.GetAsyncKeyState(VK_MENU) & 0x8000
        if not (ctrl and alt):
            return False
        self.set_intercept_enabled(not self.intercept_enabled)
        return True

    # ---------------- 钩子回调 (必须快进快出) ----------------

    def _hook_proc(self, nCode, wParam, lParam):
        if nCode >= 0:
            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk = kb.vkCode
            injected = bool(kb.flags & LLKHF_INJECTED)
            is_down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)

            # 0. 紧急逃生热键 —— 早于一切裁决, 拦截暂停时也必须可用
            if not injected and self._check_escape_hotkey(vk, is_down):
                return 1

            # 1. X6 专属键: 语音键 / "e" 键 —— 无论驱动是否标记了 injected (Windows 蓝牙 Consumer 驱动常带 0x10 Injected 标记)
            # 必须 100% 拦截并销毁, 驱动语音会话, 绝不下发给 Chrome / Explorer
            if vk in (VK_BROWSER_SEARCH, VK_LAUNCH_APP1, VK_LAUNCH_APP2):
                logger.info(f"  🎙️ [HID-Hook] 成功截获 X6 专属键: VK 0x{vk:02X} ({'down' if is_down else 'up'}) [Injected={injected}]")
                if vk == VK_BROWSER_SEARCH:
                    if is_down:
                        logger.info("  🎙️ [HID-Hook] 触发语音会话 on_voice_down")
                        if self.on_voice_down:
                            self.on_voice_down()
                    elif self.on_voice_up:
                        logger.info("  🎙️ [HID-Hook] 触发语音会话 on_voice_up")
                        self.on_voice_up()
                # 返回 1 彻底销毁事件, 绝不下发给 Chrome / Explorer
                return 1

            if injected or not self.intercept_enabled:
                return user32.CallNextHookEx(None, nCode, wParam, lParam)

            # 打印所有到达钩子的事件 (诊断)
            logger.info(f"  🔍 [HOOK] VK=0x{vk:02X} ({vk}) {'DOWN' if is_down else 'UP'} flags=0x{kb.flags:X}")

            # 2. 其余按键: 设备源仲裁 -> 映射引擎裁决
            if self.on_key_event:
                source = arbiter.classify(vk, is_down)
                if source == SOURCE_NATIVE:
                    return user32.CallNextHookEx(None, nCode, wParam, lParam)  # 原生键盘 100% 豁免
                presumed = (source != SOURCE_REMOTE)  # unknown -> 靠门控猜
                if presumed and not arbiter.remote_recently_active():
                    return user32.CallNextHookEx(None, nCode, wParam, lParam)
                if self.on_key_event(vk, is_down):
                    if presumed:
                        # 猜的, 且真吞了 -> 登记待判; Raw Input 证否时原样补回
                        arbiter.arm_replay(vk, kb.scanCode,
                                           bool(kb.flags & LLKHF_EXTENDED), is_down)
                    return 1

        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    # ---------------- 生命周期 ----------------

    def start(self):
        if self.is_running:
            return

        self.is_running = True
        self.hook_thread = threading.Thread(target=self._run_loop, daemon=True)
        self.hook_thread.start()

    def _run_loop(self):
        self.h_hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            self._callback,
            None,
            0
        )
        if not self.h_hook:
            logger.error(f"❌ [SearchSuppressor] 安装全局键盘钩子失败: {kernel32.GetLastError()}")
            return

        logger.info("  🛡️ [SearchSuppressor] 搜索拦截器已就绪 (Ctrl+Alt+F12 可紧急暂停全局拦截)")
        msg = wintypes.MSG()
        while self.is_running and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        if self.h_hook:
            user32.UnhookWindowsHookEx(self.h_hook)
            self.h_hook = None

    def stop(self):
        """唤醒钩子线程的消息循环并等待其自行 Unhook。

        注意: PostQuitMessage 只作用于调用线程自己的队列，钩子线程收不到；
        必须用 PostThreadMessageW 向钩子线程定向投递 WM_QUIT，
        否则 GetMessageW 永久阻塞，UnhookWindowsHookEx 永远不会执行。
        """
        self.is_running = False
        tid = self.hook_thread.ident if self.hook_thread else None
        if tid:
            user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
            self.hook_thread.join(timeout=1.5)
        self.hook_thread = None
