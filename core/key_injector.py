"""带状态验证的按键注入层 —— 系统性根治修饰键逻辑残留 (Win/Ctrl/Alt 卡死)。

实测 (2026-08-23 矩阵实验) 得出的关键结论，本模块的正确性建立在这些事实上:
  1. 按下与弹起必须用完全相同的 (vk, 扫描码, EXT标志) 组合——形态不配对的
     KEYUP 解不开对应形态的按下状态 (例: EXT 按下的 Ctrl 用无 EXT 的 KEYUP
     释放，系统里永远残留一个"右Ctrl"按下态);
  2. 右 Alt (VK_RMENU) 只有 vk-only 形式 (扫描码0+无EXT) 能进入系统键态，
     带扫描码的形式会被输入管线吞掉 (疑似 IME 层拦截);
  3. 注入后必须用 GetAsyncKeyState 验证真实状态，"发出"不等于"生效"，
     失败要重发。

旧实现的缺陷: 扫描码全传 0 或乱传、KEYUP 发出不验证、多线程无互斥。
"""

import ctypes
import threading
import time
from ctypes import wintypes
from .log import logger

user32 = ctypes.windll.user32
user32.GetAsyncKeyState.argtypes = [wintypes.INT]
user32.GetAsyncKeyState.restype = wintypes.SHORT
# 注意用无符号 BYTE: VK_RMENU=0xA5(165) 超出有符号字节范围
user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ctypes.c_size_t]

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001

# VK -> (扫描码, 是否扩展键)。全部经矩阵实验验证: 按下落位正确 + 同形态释放干净。
_SCAN = {
    0x11: (0x1D, False),  # VK_CONTROL  左Ctrl
    0xA2: (0x00, False),  # VK_RCONTROL
    0x5B: (0x5B, False),  # VK_LWIN
    0x5C: (0x5C, False),  # VK_RWIN
    0x12: (0x00, False),  # VK_MENU     左Alt (Alt 族带扫描码会被吞)
    0xA5: (0x00, False),  # VK_RMENU    右Alt (同上, 只认 vk-only)
    0x10: (0x2A, False),  # VK_SHIFT
    0xA0: (0x2A, False),  # VK_LSHIFT
    0xA1: (0x36, False),  # VK_RSHIFT
    0x56: (0x2F, False),  # 'V' (Ctrl+V 粘贴用)
}

# 全部左右修饰键 (紧急复位用)
_ALL_MODIFIERS = (0x11, 0xA2, 0x5B, 0x5C, 0x12, 0xA4, 0xA5, 0x10, 0xA0, 0xA1)

_lock = threading.Lock()
_down = set()  # 本模块当前按下的 VK (跨调用跟踪)


def _send(vk: int, up: bool):
    sc, ext = _SCAN.get(vk, (0, False))
    _send_form(vk, sc, ext, up=up)


def _is_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def _forms(vk: int):
    """一个 VK 的全部注入形态: 首选经实验验证的规范形态，其后是变体。

    释放"形态不匹配的按下态"时需要逐个变体尝试——历史遗留的卡死键可能
    是任意形态按下的 (EXT/无EXT、带扫描码/不带)，总有一个 KEYUP 能解开。
    """
    sc, ext = _SCAN.get(vk, (0, False))
    forms = [(sc, ext), (0, False), (sc, not ext), (0, not ext)]
    seen, out = set(), []
    for f in forms:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def _send_form(vk: int, sc: int, ext: bool, up: bool):
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if ext else 0)
    user32.keybd_event(vk, sc, flags, 0)


def _press_verified(vk: int) -> bool:
    """按下并验证。未落位不算错误——事件仍会经过 LL 钩子链 (输入法会消费
    组合键的某些事件)，功能照常触发；只需补一个配对 KEYUP 保持卫生，
    且不加入跟踪集 (状态里本来就没按下)。"""
    sc, ext = _SCAN.get(vk, (0, False))
    for _ in range(2):
        _send_form(vk, sc, ext, up=False)
        time.sleep(0.006)
        if _is_down(vk):
            return True
    _send_form(vk, sc, ext, up=True)  # 卫生释放，避免孤儿按下
    return False


def _release_verified(vk: int, retries: int = 3) -> bool:
    """释放并验证，失败走形态变体阶梯。

    典型卡死场景: 按下是 A 形态 (如 EXT+扫描码)，KEYUP 是 B 形态，
    系统里残留 A 形态的按下态，B 形态的 KEYUP 永远解不开——
    必须换回 A 形态 (或其他变体) 才能释放。
    """
    if not _is_down(vk):
        return True  # 状态里本来就是起的 (可能按下时被钩子消费)
    for sc, ext in _forms(vk):
        for _ in range(retries):
            _send_form(vk, sc, ext, up=True)
            time.sleep(0.006)
            if not _is_down(vk):
                return True
    logger.error(f"  ⚠️ [KeyInjector] VK 0x{vk:02X} 全形态释放失败，仍处于按下状态!")
    return False


def is_stuck() -> list:
    """诊断: 返回当前逻辑上处于按下状态的修饰键 VK 列表。"""
    return [vk for vk in _ALL_MODIFIERS if _is_down(vk)]


def press(vks):
    """按下一组键 (顺序按下)。会先清掉本模块残留的按下状态。

    被钩子消费而未落位的键不进跟踪集——状态里没有按下态，就不会卡死。
    """
    with _lock:
        for vk in _down.copy():
            _release_verified(vk)
        _down.clear()
        for vk in vks:
            if _press_verified(vk):
                _down.add(vk)


def release(vks):
    """逆序弹起一组键并逐一验证。"""
    with _lock:
        for vk in reversed(vks):
            _release_verified(vk)
            _down.discard(vk)


def pulse(vks, hold: float = 0.04):
    """按下-保持-弹起 一个组合，全程持锁，确保不与其他注入交错。"""
    with _lock:
        for vk in _down.copy():
            _release_verified(vk)
        _down.clear()
        try:
            for vk in vks:
                if _press_verified(vk):
                    _down.add(vk)
            time.sleep(hold)
        finally:
            for vk in reversed(vks):
                _release_verified(vk)
                _down.discard(vk)


def release_all():
    """释放本模块按下的所有键 (带验证)。会话结束/异常恢复时调用。"""
    with _lock:
        for vk in _down.copy():
            _release_verified(vk)
        _down.clear()


def panic_release_all_modifiers():
    """无差别强制释放所有左右修饰键 (不管是谁按下的)。

    仅用于程序退出或用户明确要求复位: 若用户此刻真实按着修饰键打字，
    此操作会打断其输入状态。
    """
    with _lock:
        for vk in _ALL_MODIFIERS:
            _release_verified(vk, retries=2)
        _down.clear()
