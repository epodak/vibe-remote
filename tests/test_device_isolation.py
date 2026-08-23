"""设备源隔离的裁决回归测试 (ISSUE-01)。

不需要真机: 直接构造 KBDLLHOOKSTRUCT 喂给 SearchSuppressor._hook_proc, 并把
仲裁器的内部状态摆成各种场景, 断言"拦 / 不拦"与"是否调用映射引擎"。

钉死的铁律 (回归时最先炸的就是它们):
  1. 来源判定为原生键盘 -> 绝不拦截, 且不进映射引擎;
  2. 来源未知且门控关闭 -> 绝不拦截 (日常打字场景);
  3. 来源未知但门控开着 -> 拦截并登记补偿, 事后被证否会原样重放;
  4. 拦截总开关关闭 (Ctrl+Alt+F12) -> 一切透传;
  5. 注入事件 (含自己的重放) -> 一律透传, 不形成回环。

运行: python vRemote_win/tests/test_device_isolation.py
"""

import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from core import device_source
from core.device_source import (
    SOURCE_NATIVE, SOURCE_REMOTE, DeviceSourceArbiter, _Pending, _RawEvent,
    _parse_identity, normalize_mac,
)
from core.search_suppressor import (
    KBDLLHOOKSTRUCT, LLKHF_INJECTED, SearchSuppressor, WM_KEYDOWN,
)

HC_ACTION = 0
VK_RETURN = 0x0D
SC_RETURN = 0x1C

_failures = []


def check(name: str, cond: bool, detail: str = ""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _failures.append(name)


def _lparam(vk: int, scan: int = SC_RETURN, injected: bool = False):
    kb = KBDLLHOOKSTRUCT(vkCode=vk, scanCode=scan,
                         flags=LLKHF_INJECTED if injected else 0, time=0, dwExtraInfo=0)
    _lparam.keep = kb            # 防止结构体被 GC 掉后指针悬空
    return ctypes.addressof(kb)


def _make(arbiter):
    """造一个把映射调用记录下来的抑制器 (映射引擎一律回答"我拦了")。"""
    calls = []

    def on_key(vk, is_down):
        calls.append((vk, is_down))
        return True

    sup = SearchSuppressor(on_key_event=on_key)
    device_source.arbiter = arbiter          # 抑制器通过模块属性访问单例
    import core.search_suppressor as ss
    ss.arbiter = arbiter
    return sup, calls


def _bound_arbiter() -> DeviceSourceArbiter:
    arb = DeviceSourceArbiter()
    arb.bound_mac = "B0EFD78B56AC"           # 伪造"已绑定", 不碰磁盘
    arb.bound_name = "X6"
    arb.is_running = True                    # 伪造"Raw Input 在跑"
    arb.enabled = True
    return arb


def test_identity_parsing():
    print("[设备身份解析]")
    ble = (r"\\?\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&021d5a_PID&c081"
           r"_REV&0000_b0efd78b56ac&Col01#9&18a35dbc&0&0000#{884b96c3-56ef-11d1-bc8c}")
    usb = r"\\?\HID#VID_1C4F&PID_0002&MI_00#8&1271477b&0&0000#{884b96c3-56ef-11d1-bc8c}"
    check("BLE 路径提取 MAC", _parse_identity(ble)["mac"] == "B0EFD78B56AC",
          str(_parse_identity(ble)))
    check("BLE 路径 VID 取末四位", _parse_identity(ble)["vid"] == "1D5A")
    check("USB 路径提取 VID/PID",
          (_parse_identity(usb)["vid"], _parse_identity(usb)["pid"]) == ("1C4F", "0002"))
    check("USB 路径无 MAC", _parse_identity(usb)["mac"] is None)
    check("MAC 归一化", normalize_mac("b0:ef:d7:8b:56:ac") == "B0EFD78B56AC")


def test_native_never_intercepted():
    print("[铁律 1: 原生键盘按键绝不被拦截]")
    arb = _bound_arbiter()
    # 权威判定: 最近 raw 记录说这一下来自非遥控器设备
    arb._recent.append(_RawEvent(time.time(), VK_RETURN, SC_RETURN, True, 111, is_remote=False))
    sup, calls = _make(arb)
    ret = sup._hook_proc(HC_ACTION, WM_KEYDOWN, _lparam(VK_RETURN))
    check("Enter 透传 (返回值非 1)", ret != 1, f"ret={ret}")
    check("映射引擎未被调用", calls == [], str(calls))
    check("classify 判定为 native",
          arb.classify(VK_RETURN, True) in (SOURCE_NATIVE, "unknown"))


def test_gate_closed_passthrough():
    print("[铁律 2: 来源未知 + 门控关闭 -> 透传]")
    arb = _bound_arbiter()
    arb.last_source = SOURCE_NATIVE          # 用户刚在物理键盘上打字
    arb.last_native_ts = time.time()
    sup, calls = _make(arb)
    ret = sup._hook_proc(HC_ACTION, WM_KEYDOWN, _lparam(VK_RETURN))
    check("门控关闭", arb.remote_recently_active() is False)
    check("Enter 透传", ret != 1, f"ret={ret}")
    check("映射引擎未被调用", calls == [])
    check("未登记补偿重放", len(arb._pending) == 0)


def test_gate_open_intercepts_and_arms():
    print("[铁律 3: 来源未知 + 门控开启 -> 拦截并登记补偿]")
    arb = _bound_arbiter()
    arb.last_source = SOURCE_REMOTE          # 最近一次输入来自遥控器
    arb.last_remote_ts = time.time()
    sup, calls = _make(arb)
    ret = sup._hook_proc(HC_ACTION, WM_KEYDOWN, _lparam(VK_RETURN))
    check("门控开启", arb.remote_recently_active() is True)
    check("Enter 被拦截", ret == 1, f"ret={ret}")
    check("映射引擎被调用一次", calls == [(VK_RETURN, True)], str(calls))
    check("已登记补偿重放", len(arb._pending) == 1)


def test_replay_on_disproof():
    print("[铁律 3b: 被证否 -> 补偿重放 + 复位鼠标]")
    arb = _bound_arbiter()
    fired = []
    arb.on_mispredict = lambda: fired.append(1)
    arb.arm_replay(VK_RETURN, SC_RETURN, False, True)
    with arb._lock:
        pend = arb._match_pending(VK_RETURN, True, is_remote=False, now=time.time())
    check("证否产生 1 个待重放事件", len(pend) == 1)
    check("待判队列已清空", len(arb._pending) == 0)

    arb.arm_replay(VK_RETURN, SC_RETURN, False, True)
    with arb._lock:
        pend2 = arb._match_pending(VK_RETURN, True, is_remote=True, now=time.time())
    check("证实来自遥控器则不重放", pend2 == [])

    arb.arm_replay(VK_RETURN, SC_RETURN, False, True)
    with arb._lock:
        expired = arb._match_pending(0xFF, True, is_remote=False,
                                     now=time.time() + device_source.REPLAY_WAIT_S + 1)
    check("超时未被证实的待判被丢弃", expired == [] and len(arb._pending) == 0)


def test_intercept_switch_and_injected():
    print("[铁律 4/5: 总开关关闭 与 注入事件]")
    arb = _bound_arbiter()
    arb.last_source = SOURCE_REMOTE
    arb.last_remote_ts = time.time()

    sup, calls = _make(arb)
    sup.intercept_enabled = False
    ret = sup._hook_proc(HC_ACTION, WM_KEYDOWN, _lparam(VK_RETURN))
    check("总开关关闭时透传", ret != 1, f"ret={ret}")
    check("总开关关闭时不进映射引擎", calls == [])

    sup2, calls2 = _make(arb)
    ret2 = sup2._hook_proc(HC_ACTION, WM_KEYDOWN, _lparam(VK_RETURN, injected=True))
    check("注入事件透传 (不形成重放回环)", ret2 != 1, f"ret={ret2}")
    check("注入事件不进映射引擎", calls2 == [])


def test_unbound_falls_back_to_legacy():
    print("[未绑定时退回旧行为 (避免映射彻底失灵)]")
    arb = DeviceSourceArbiter()
    arb.bound_mac = arb.bound_vid = None
    arb.is_running = True
    check("未绑定 -> 隔离不生效", arb.isolation_active is False)
    check("未绑定 -> classify 一律 remote", arb.classify(VK_RETURN, True) == SOURCE_REMOTE)
    check("未绑定 -> 门控常开", arb.remote_recently_active() is True)
    arb.arm_replay(VK_RETURN, SC_RETURN, False, True)
    check("未绑定 -> 不登记重放 (否则会把遥控器自己的键补发一遍)",
          len(arb._pending) == 0)


def test_signature_keys_always_intercepted():
    print("[铁律 6: X6 专属键 (语音/e) 100% 拦截驱动, 绝不透传]")
    arb = _bound_arbiter()
    # 模拟 Raw Input 记录为 native (例如 ConvertedDevice 场景)
    arb._recent.append(_RawEvent(time.time(), 0xAA, 0, True, 999, is_remote=False))
    
    voice_down_called = []
    sup = SearchSuppressor(on_voice_down=lambda: voice_down_called.append(True))
    import core.search_suppressor as ss
    ss.arbiter = arb

    # VK_BROWSER_SEARCH (0xAA) down
    ret = sup._hook_proc(HC_ACTION, WM_KEYDOWN, _lparam(0xAA))
    check("语音键 100% 被拦截 (返回值 1)", ret == 1, f"ret={ret}")
    check("语音键 down 回调成功触发", voice_down_called == [True])

    # VK_LAUNCH_APP1 (0xB6) "e" 键
    ret_e = sup._hook_proc(HC_ACTION, WM_KEYDOWN, _lparam(0xB6))
    check("e 键 100% 被拦截", ret_e == 1, f"ret={ret_e}")


def main():
    for fn in (test_identity_parsing, test_native_never_intercepted,
               test_signature_keys_always_intercepted,
               test_gate_closed_passthrough, test_gate_open_intercepts_and_arms,
               test_replay_on_disproof, test_intercept_switch_and_injected,
               test_unbound_falls_back_to_legacy):
        fn()
    print()
    if _failures:
        print(f"❌ {len(_failures)} 项失败: {', '.join(_failures)}")
        return 1
    print("✅ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
