"""Raw Input 设备源仲裁器 —— 根治「全局钩子误伤 PC 原生键盘」(ISSUE-01)。

## 问题本质

`WH_KEYBOARD_LL` 的回调结构体 `KBDLLHOOKSTRUCT` 只有 `vkCode/scanCode/flags`,
**没有设备句柄**。X6 遥控器的 OK/Del/返回/Esc 用的就是标准键码 (0x0D/0x2E/0x1B…),
一旦映射为 `left_hold`/`block`, 钩子会把原生键盘的同名按键一起吞掉 ——
用户按 Enter 变成鼠标拖拽、按 Backspace 删不掉字。

## 本模块的解法: 权威判定 + 活跃门控 + 吞噬补偿重放

Raw Input (`RegisterRawInputDevices` + `WM_INPUT`) 能拿到 `RAWINPUTHEADER.hDevice`,
是**唯一**能区分"这一下按键来自哪个物理设备"的用户态 API。但它有两个约束:

1. 只能观测, **不能拦截** —— 拦截仍必须由 LL 钩子完成;
2. `WM_INPUT` 走消息队列, 通常**晚于** LL 钩子回调若干毫秒到达。

于是三层协同:

```
  按键 ──► LL 钩子 (必须同步裁决)            Raw Input 线程 (权威但迟到)
            │                                        │
            ├─① classify(): 命中最近 12ms 的         ├─ 解析 hDevice -> VID/PID
            │   raw 记录 -> 权威来源, 直接裁决        ├─ 写入"最近事件"环形缓冲 (供①)
            │                                        │
            ├─② 查不到 -> 看"X6 活跃门控"            ├─ 匹配 arm_replay 登记的待判事件:
            │   (最近一次键盘输入是否来自 X6)          │    · 证实来自 X6  -> 无事发生
            │                                        │    · 证否(原生键盘) -> SendInput
            └─③ 判为 X6 且真吞了 -> arm_replay()      │      原样重放, 用户无感
                登记待判, 由 Raw 线程事后裁决 ────────┘
```

最坏情况: 用户刚用完遥控器、门控还开着就去敲主键盘 —— 那一下按键先被吞、
几毫秒后被 SendInput 原样补回 (功能不丢), 同时立刻复位可能被按住的鼠标键,
并计入 `mispredict`。此后 last_source 变为 native, 门控关闭, 整个打字过程安全。
遥控器空闲时 (日常打字场景) 原生键盘 **100% 豁免**, 钩子完全不介入。

反过来的代价也说清楚: 门控关着时遥控器的**第一个**脉冲会漏判并透传。
X6 固件是脉冲连发, 后续脉冲在 raw 事件到达 (~ms) 后即被正确映射, 因此
表现为一次几十毫秒的延迟, 而不是功能失效。两害相权 —— 宁可漏一个脉冲,
不可吞用户的 Enter。

## 设备绑定

绑定按身份而非句柄, 因为一支遥控器会枚举成多个 HID 集合 (Col01/Col02…):
  · **MAC 优先** —— X6 走 BLE HID, 设备路径内嵌蓝牙地址 (…_b0efd78b56ac&Col01),
    与 config.REMOTE_MAC 直接对上, 开机零配置自动绑定, 且同机多支遥控器不会串;
  · VID&PID —— USB 接收器形态的回退身份;
  · 专属键自动学习 —— 收到 X6 独有键 (语音 0xAA / LaunchApp 0xB6 / 返回 0xA6…) 时绑定;
  · 手动学习 —— GUI 里点"学习设备", 下一个按键的来源即被绑定 (兜底歧义场景)。
绑定结果持久化在 device_binding.json。

**未绑定时刻意退回旧行为** (见 isolation_active): 此时"哪台是遥控器"无从判断,
一律豁免会让映射彻底失灵, 比原缺陷更糟; GUI 会显式告警并提供一键学习。
"""

import ctypes
import json
import os
import re
import threading
import time
from collections import deque
from ctypes import wintypes

from .log import logger

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# ---------------- Win32 常量 ----------------

WM_INPUT = 0x00FF
WM_QUIT = 0x0012
HWND_MESSAGE = wintypes.HWND(-3)

RIDEV_INPUTSINK = 0x00000100
RIDEV_REMOVE = 0x00000001
RID_INPUT = 0x10000003
RIDI_DEVICENAME = 0x20000007
RIM_TYPEKEYBOARD = 1

RI_KEY_BREAK = 0x01   # 抬起 (0 = 按下)
RI_KEY_E0 = 0x02      # 扩展键前缀
RI_KEY_E1 = 0x04

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002

REPLAY_TAG = 0x0000D0CE  # dwExtraInfo 标记: 本模块补偿重放的事件

# X6 专属键 —— 收到即可判定该设备是遥控器接收器 (原生键盘不会有语音搜索键)
X6_SIGNATURE_VKS = frozenset({
    0xAA,  # VK_BROWSER_SEARCH  语音键
    0xB6,  # VK_LAUNCH_APP1     "e" 键
    0xB7,  # VK_LAUNCH_APP2
    0xA6,  # VK_BROWSER_BACK    返回键
    0xAC,  # VK_BROWSER_HOME    主页键
})

# 判定参数
CORRELATE_WINDOW_S = 0.012   # 钩子回溯窗口: raw 记录若在此窗口内视为同一次按键
REPLAY_WAIT_S = 0.090        # 待判事件的最长等待 (超时未被 raw 证实 -> 丢弃)
# X6 活跃门控的时长。判别力主要来自"最近一次键盘输入是谁"而非时间本身,
# 时间只是防陈旧的兜底 —— 取值太短 (试过 1.5s) 会让遥控器操作间隔一超窗就
# 漏掉首个脉冲, 8s 覆盖真实的操作停顿, 而误判代价由补偿重放 + 鼠标复位兜住。
ACTIVE_GATE_S = 8.0

SOURCE_REMOTE = "remote"
SOURCE_NATIVE = "native"
SOURCE_UNKNOWN = "unknown"

_BINDING_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "device_binding.json"))


# ---------------- 结构体 ----------------

class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD),
                ("hDevice", wintypes.HANDLE), ("wParam", wintypes.WPARAM)]


class RAWKEYBOARD(ctypes.Structure):
    _fields_ = [("MakeCode", wintypes.USHORT), ("Flags", wintypes.USHORT),
                ("Reserved", wintypes.USHORT), ("VKey", wintypes.USHORT),
                ("Message", wintypes.UINT), ("ExtraInformation", wintypes.ULONG)]


class RAWINPUT_KB(ctypes.Structure):
    """RAWINPUT 的键盘特化 (union 中 RAWKEYBOARD 分支, 偏移与完整 RAWINPUT 一致)。"""
    _fields_ = [("header", RAWINPUTHEADER), ("keyboard", RAWKEYBOARD)]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT),
                ("dwFlags", wintypes.DWORD), ("hwndTarget", wintypes.HWND)]


class RAWINPUTDEVICELIST(ctypes.Structure):
    _fields_ = [("hDevice", wintypes.HANDLE), ("dwType", wintypes.DWORD)]


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("_pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p,
                                   ctypes.POINTER(wintypes.UINT), wintypes.UINT]
user32.GetRawInputDeviceInfoW.argtypes = [wintypes.HANDLE, wintypes.UINT,
                                          ctypes.c_void_p, ctypes.POINTER(wintypes.UINT)]
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_longlong


# ---------------- 设备名解析 ----------------

_HEX = set("0123456789ABCDEF")


def _parse_identity(device_name: str) -> dict:
    """从 Raw Input 设备名解析设备身份 (vid / pid / mac)。

    两种真实形态 (本机实测):

    · USB HID   ``\\\\?\\HID#VID_1C4F&PID_0002&MI_00#8&1271477b&0&0000#{guid}``
    · BLE HID   ``\\\\?\\HID#{00001812-…}_Dev_VID&021d5a_PID&c081_REV&0000_b0efd78b56ac&Col01#…``

    X6 走 BLE, 其路径里**内嵌了遥控器 MAC** (b0efd78b56ac = B0:EF:D7:8B:56:AC),
    而 BLE 的 ``VID&021d5a`` 前两位是地址类型/厂商命名空间, 真正的 VID 是后 4 位。
    MAC 是最强身份 —— 同一遥控器的全部 HID 集合 (Col01/Col02…) 共享它,
    因此优先用 MAC 绑定, 可与 config.REMOTE_MAC 直接对上, 零配置。
    """
    if not device_name:
        return {"vid": None, "pid": None, "mac": None}
    up = device_name.upper()

    # VID/PID 的分隔符两种形态都有: USB 用 `VID_1C4F`, BLE 用 `VID&021D5A`;
    # BLE 值是 6 位 (前两位是地址类型/命名空间), 统一取末 4 位才是真 VID。
    def _grab(prefix):
        m = re.search(prefix + r"[_&]([0-9A-F]{4,6})", up)
        return m.group(1)[-4:] if m else None

    # MAC 只按 \ # & _ 切分后找 12 位纯十六进制 —— 刻意不拿 '-' 当分隔符,
    # 否则设备接口 GUID 的末段 (…-00A0C91405DD) 会被误认成蓝牙地址。
    mac = None
    for token in up.replace("\\", "#").replace("&", "#").replace("_", "#").split("#"):
        if len(token) == 12 and all(c in _HEX for c in token):
            mac = token
    return {"vid": _grab("VID"), "pid": _grab("PID"), "mac": mac}


def normalize_mac(mac: str) -> str:
    """B0:EF:D7:8B:56:AC -> B0EFD78B56AC (与设备路径内嵌形态对齐)。"""
    return (mac or "").replace(":", "").replace("-", "").upper()


def _friendly_name(device_name: str) -> str:
    """查注册表把 Raw Input 设备路径翻译成人类可读名 (失败则回退设备路径尾段)。"""
    try:
        import winreg
        parts = device_name.lstrip("\\?").lstrip("\\").split("#")
        if len(parts) >= 3:
            key_path = "SYSTEM\\CurrentControlSet\\Enum\\" + "\\".join(parts[:3])
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as k:
                for field in ("FriendlyName", "DeviceDesc"):
                    try:
                        val = winreg.QueryValueEx(k, field)[0]
                        # DeviceDesc 常是 "@input.inf,%hid_device%;USB 输入设备" 形式
                        return val.split(";")[-1].strip()
                    except OSError:
                        continue
    except Exception:
        pass
    tail = device_name.split("#")
    return tail[1] if len(tail) > 1 else device_name


# ---------------- 仲裁器 ----------------

class _RawEvent:
    __slots__ = ("ts", "vk", "scan", "is_down", "handle", "is_remote", "used")

    def __init__(self, ts, vk, scan, is_down, handle, is_remote):
        self.ts = ts
        self.vk = vk
        self.scan = scan
        self.is_down = is_down
        self.handle = handle
        self.is_remote = is_remote
        self.used = False


class _Pending:
    __slots__ = ("ts", "vk", "scan", "ext", "is_down")

    def __init__(self, ts, vk, scan, ext, is_down):
        self.ts = ts
        self.vk = vk
        self.scan = scan
        self.ext = ext
        self.is_down = is_down


class DeviceSourceArbiter:
    """键盘事件设备源仲裁 (单例, 由 core.device_source.arbiter 提供)。

    线程模型:
      · Raw Input 线程   —— 独占消息循环, 写 _recent / 消费 _pending / 触发重放
      · LL 钩子线程      —— 只读 _recent (classify) 与写 _pending (arm_replay), 全程持锁但 O(k)
      · GUI 线程         —— snapshot() / start_learning() / bind_manual()
    """

    def __init__(self):
        self.enabled = True            # False = 退回旧行为 (一切按遥控器处理)
        self.is_running = False

        self._lock = threading.Lock()
        self._recent = deque(maxlen=64)      # [_RawEvent] 最近 raw 事件 (供钩子回溯)
        self._pending = deque(maxlen=32)     # [_Pending]  被吞待判事件
        self._names = {}                     # handle(int) -> (device_name, friendly)
        self._devices = {}                   # handle(int) -> {name, friendly, vid, pid, hits, last_ts, remote}

        self.bound_vid = None
        self.bound_pid = None
        self.bound_mac = None                # 最强身份 (BLE 设备路径内嵌)
        self.bound_name = None
        self.expected_mac = None             # 来自 config.REMOTE_MAC, 用于零配置自动绑定
        self._learning = False               # 手动学习模式: 下一个按键的设备即 X6

        self.last_source = None              # 最近一次 raw 事件来源 (remote/native)
        self.last_remote_ts = 0.0
        self.last_native_ts = 0.0
        self.stat_remote = 0                 # 判定为遥控器的按键数
        self.stat_native = 0                 # 豁免的原生键盘按键数
        self.stat_replayed = 0               # 补偿重放次数 (= 误吞并已补回)
        self.stat_authoritative = 0          # 钩子侧命中权威判定的次数

        self.stat_mispredict = 0             # 门控猜错的次数 (= 已补偿的误吞)
        self.on_mispredict = None            # 回调: 猜错时立刻复位映射引擎的鼠标状态

        self._hwnd = None
        self._thread = None
        self._wndproc_ref = None
        self._class_name = "vRemoteRawInputSink"

        self._load_binding()

    # ================= 绑定持久化 =================

    def set_expected_mac(self, mac: str):
        """告知遥控器 MAC (config.REMOTE_MAC) —— BLE HID 路径内嵌 MAC, 据此零配置绑定。"""
        self.expected_mac = normalize_mac(mac) or None
        if self.expected_mac:
            with self._lock:
                for h, d in self._devices.items():
                    if d.get("mac") == self.expected_mac and not d["remote"]:
                        self._bind(h, "MAC 匹配 config.REMOTE_MAC")
                        break

    def _load_binding(self):
        try:
            with open(_BINDING_PATH, encoding="utf-8") as f:
                data = json.load(f)
            self.bound_vid = data.get("vid")
            self.bound_pid = data.get("pid")
            self.bound_mac = data.get("mac")
            self.bound_name = data.get("friendly")
            if self.bound_mac or self.bound_vid:
                logger.info(f"  🎯 [DeviceSource] 已载入 X6 接收器绑定: "
                            f"{self.bound_id_str()} ({self.bound_name})")
        except (OSError, ValueError, TypeError):
            pass

    def bound_id_str(self) -> str:
        if self.bound_mac:
            return "MAC " + ":".join(self.bound_mac[i:i + 2] for i in range(0, 12, 2))
        if self.bound_vid:
            return f"VID_{self.bound_vid}&PID_{self.bound_pid}"
        return "—"

    @property
    def is_bound(self) -> bool:
        return bool(self.bound_mac or self.bound_vid)

    def _save_binding(self):
        try:
            with open(_BINDING_PATH, "w", encoding="utf-8") as f:
                json.dump({"vid": self.bound_vid, "pid": self.bound_pid,
                           "mac": self.bound_mac, "friendly": self.bound_name,
                           "bound_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                          f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.warning(f"  ⚠️ [DeviceSource] 绑定写入失败: {e}")

    def unbind(self):
        """解除绑定 (回到"未识别"状态, 下次遇到 X6 专属键会重新自动学习)。"""
        with self._lock:
            self.bound_vid = self.bound_pid = self.bound_mac = self.bound_name = None
            for d in self._devices.values():
                d["remote"] = False
        try:
            os.remove(_BINDING_PATH)
        except OSError:
            pass
        logger.info("  🎯 [DeviceSource] 已解除 X6 接收器绑定")

    def start_learning(self):
        """进入手动学习: 下一个按键事件的来源设备即被绑定为 X6 接收器。"""
        with self._lock:
            self._learning = True
        logger.info("  🎯 [DeviceSource] 学习模式已开启 —— 请按遥控器任意键")

    def cancel_learning(self):
        with self._lock:
            self._learning = False

    @property
    def is_learning(self) -> bool:
        return self._learning

    def _bind(self, handle_int: int, why: str):
        """(持锁调用) 绑定某设备为 X6, 并把同身份的全部 HID 集合一并标记。"""
        info = self._devices.get(handle_int)
        if not info or not (info.get("mac") or info.get("vid")):
            return
        self.bound_mac = info.get("mac")
        self.bound_vid, self.bound_pid = info.get("vid"), info.get("pid")
        self.bound_name = info["friendly"]
        for d in self._devices.values():
            d["remote"] = self._matches_binding(d)
        self._save_binding()
        logger.info(f"  🎯 [DeviceSource] 绑定 X6 接收器 ({why}): "
                    f"{self.bound_name} · {self.bound_id_str()}")

    def _matches_binding(self, info: dict) -> bool:
        """MAC 优先 (BLE 多集合共享); 无 MAC 时退回 VID+PID。"""
        if self.bound_mac:
            return info.get("mac") == self.bound_mac
        if self.bound_vid:
            return info.get("vid") == self.bound_vid and info.get("pid") == self.bound_pid
        return False

    # ================= 钩子侧 API (必须 O(k) 快进快出) =================

    @property
    def isolation_active(self) -> bool:
        """隔离是否真正生效。

        未绑定 X6 时**刻意退回旧行为** —— 此时"哪台是遥控器"无从判断,
        若一律按原生键盘豁免会让映射彻底失灵 (比原缺陷更糟)。绑定发生在
        X6 的第一次按键 (MAC 匹配或专属键), 之后立即转入严格隔离。
        未绑定状态由 GUI 显式告警, 并提供一键学习。
        """
        return self.enabled and self.is_running and self.is_bound

    def classify(self, vk: int, is_down: bool) -> str:
        """权威判定: 最近 CORRELATE_WINDOW_S 内是否有同 (vk, 边沿) 的 raw 记录。

        命中 -> 返回该记录的真实来源; 未命中 -> SOURCE_UNKNOWN。
        隔离未生效时一律返回 SOURCE_REMOTE (等价于本模块不存在的旧行为)。
        """
        if not self.isolation_active:
            return SOURCE_REMOTE
        now = time.time()
        with self._lock:
            for ev in reversed(self._recent):
                if now - ev.ts > CORRELATE_WINDOW_S:
                    break
                if ev.vk == vk and ev.is_down == is_down and not ev.used:
                    ev.used = True
                    self.stat_authoritative += 1
                    return SOURCE_REMOTE if ev.is_remote else SOURCE_NATIVE
        return SOURCE_UNKNOWN

    def remote_recently_active(self) -> bool:
        """活跃门控: 最近一次键盘 raw 事件来自 X6, 且未超过 ACTIVE_GATE_S。

        用"最近一次来源"而非单纯时间窗 —— 用户一旦碰了主键盘, 门控立刻关闭,
        后续原生按键不再有被误吞的机会。
        """
        if not self.isolation_active:
            return True
        return (self.last_source == SOURCE_REMOTE
                and time.time() - self.last_remote_ts < ACTIVE_GATE_S)

    def arm_replay(self, vk: int, scan: int, ext: bool, is_down: bool):
        """登记一个"猜是遥控器所以吞掉"的事件, 交给 Raw 线程事后裁决。

        raw 证实来自原生键盘 -> 原样重放补回; 证实来自 X6 -> 什么都不做。
        """
        if not self.isolation_active:
            return  # 未绑定时无从判断真伪, 绝不重放 (否则会把 X6 自己的键补发一遍)
        with self._lock:
            self._pending.append(_Pending(time.time(), vk, scan, ext, is_down))

    # ================= Raw Input 线程 =================

    def start(self):
        if self.is_running:
            return
        self._thread = threading.Thread(target=self._run, name="RawInputSink", daemon=True)
        self._thread.start()
        # 等待窗口就绪, 避免钩子先于 Raw Input 起来导致首批按键无权威来源
        for _ in range(40):
            if self.is_running:
                break
            time.sleep(0.02)

    def stop(self):
        self.is_running = False
        hwnd = self._hwnd
        if hwnd:
            user32.PostMessageW(hwnd, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(timeout=1.5)
        self._thread = None

    def _run(self):
        try:
            hinst = kernel32.GetModuleHandleW(None)
            self._wndproc_ref = WNDPROC(self._wndproc)
            wc = WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wc.lpfnWndProc = self._wndproc_ref
            wc.hInstance = hinst
            wc.lpszClassName = self._class_name
            if not user32.RegisterClassExW(ctypes.byref(wc)):
                err = kernel32.GetLastError()
                if err != 1410:  # ERROR_CLASS_ALREADY_EXISTS
                    logger.error(f"  ❌ [DeviceSource] 注册窗口类失败: {err}")
                    return
            hwnd = user32.CreateWindowExW(
                0, self._class_name, "vRemote RawInput Sink", 0, 0, 0, 0, 0,
                HWND_MESSAGE, None, hinst, None)
            if not hwnd:
                logger.error(f"  ❌ [DeviceSource] 创建消息窗口失败: {kernel32.GetLastError()}")
                return
            self._hwnd = hwnd

            rid = RAWINPUTDEVICE(0x01, 0x06, RIDEV_INPUTSINK, wintypes.HWND(hwnd))
            if not user32.RegisterRawInputDevices(ctypes.byref(rid), 1,
                                                  ctypes.sizeof(RAWINPUTDEVICE)):
                logger.error(f"  ❌ [DeviceSource] 注册 Raw Input 失败: {kernel32.GetLastError()}")
                user32.DestroyWindow(hwnd)
                self._hwnd = None
                return

            self._enumerate_devices()
            self.is_running = True
            logger.info("  🎯 [DeviceSource] Raw Input 设备源仲裁已就绪 "
                        "(原生键盘将被逐事件豁免)")

            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as e:
            logger.error(f"  ❌ [DeviceSource] Raw Input 线程异常: {e!r}")
        finally:
            self.is_running = False
            if self._hwnd:
                try:
                    rid = RAWINPUTDEVICE(0x01, 0x06, RIDEV_REMOVE, None)
                    user32.RegisterRawInputDevices(ctypes.byref(rid), 1,
                                                   ctypes.sizeof(RAWINPUTDEVICE))
                    user32.DestroyWindow(self._hwnd)
                except Exception:
                    pass
                self._hwnd = None

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_INPUT:
            try:
                self._on_raw_input(lparam)
            except Exception as e:
                logger.debug(f"[DeviceSource] WM_INPUT 处理异常: {e!r}")
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _on_raw_input(self, lparam):
        size = wintypes.UINT(0)
        hdr_size = ctypes.sizeof(RAWINPUTHEADER)
        if user32.GetRawInputData(wintypes.HANDLE(lparam), RID_INPUT, None,
                                  ctypes.byref(size), hdr_size) != 0:
            return
        buf = ctypes.create_string_buffer(max(size.value, ctypes.sizeof(RAWINPUT_KB)))
        if user32.GetRawInputData(wintypes.HANDLE(lparam), RID_INPUT, buf,
                                  ctypes.byref(size), hdr_size) != size.value:
            return
        raw = ctypes.cast(buf, ctypes.POINTER(RAWINPUT_KB)).contents
        if raw.header.dwType != RIM_TYPEKEYBOARD:
            return

        kb = raw.keyboard
        vk = kb.VKey
        if vk in (0, 0xFF):   # 0xFF = 部分键盘的哑事件前缀
            return
        is_down = not (kb.Flags & RI_KEY_BREAK)
        handle = int(raw.header.hDevice or 0)
        now = time.time()

        info = self._device_info(handle)
        is_remote = bool(info.get("remote"))

        with self._lock:
            # ---- 专属键兜底: 无论设备是否枚举出 MAC (如 Windows Consumer 转换设备 ConvertedDevice), 专属键必来自遥控器 ----
            if vk in X6_SIGNATURE_VKS:
                is_remote = True

            # ---- 学习优先级: 手动 > MAC 匹配 config > X6 专属键 ----
            if info.get("mac") or info.get("vid"):
                if self._learning:
                    self._learning = False
                    self._bind(handle, "手动学习")
                    is_remote = True
                elif not self.is_bound:
                    if self.expected_mac and info.get("mac") == self.expected_mac:
                        self._bind(handle, "MAC 匹配 config.REMOTE_MAC")
                        is_remote = True
                    elif vk in X6_SIGNATURE_VKS:
                        self._bind(handle, f"专属键 VK 0x{vk:02X}")
                        is_remote = True

            info["hits"] = info.get("hits", 0) + 1
            info["last_ts"] = now
            self._recent.append(_RawEvent(now, vk, kb.MakeCode, is_down, handle, is_remote))
            if is_remote:
                self.stat_remote += 1
                self.last_source = SOURCE_REMOTE
                self.last_remote_ts = now
            else:
                self.stat_native += 1
                self.last_source = SOURCE_NATIVE
                self.last_native_ts = now

            replays = self._match_pending(vk, is_down, is_remote, now)

        for p in replays:
            self._replay(p)
        if replays:
            # 猜错了: 这一下其实来自物理键盘, 但映射动作已经注入出去。
            # 最坏情况是 left_hold 把鼠标左键按住不放 —— 立刻复位, 别让它挂着。
            self.stat_mispredict += len(replays)
            if self.on_mispredict:
                try:
                    self.on_mispredict()
                except Exception as e:
                    logger.debug(f"[DeviceSource] mispredict 回调异常: {e!r}")

    def _match_pending(self, vk: int, is_down: bool, is_remote: bool, now: float) -> list:
        """(持锁) 消费待判事件, 返回需要补偿重放的列表。"""
        out = []
        resolved = False
        keep = deque(maxlen=self._pending.maxlen)
        for p in self._pending:
            if now - p.ts > REPLAY_WAIT_S:
                continue  # 超时: 没有对应 raw 事件, 丢弃
            if not resolved and p.vk == vk and p.is_down == is_down:
                resolved = True            # 一个 raw 事件只裁决一个待判事件
                if not is_remote:
                    out.append(p)          # 证否 -> 重放补回
                continue
            keep.append(p)
        self._pending = keep
        return out

    def _replay(self, p: _Pending):
        """把被误吞的原生键盘事件原样注入回系统 (带 INJECTED 标记, 不会再被自己吞)。"""
        flags = (KEYEVENTF_EXTENDEDKEY if p.ext else 0) | (0 if p.is_down else KEYEVENTF_KEYUP)
        inp = INPUT(type=INPUT_KEYBOARD)
        inp.u.ki = KEYBDINPUT(wVk=p.vk, wScan=p.scan, dwFlags=flags, time=0,
                              dwExtraInfo=REPLAY_TAG)
        sent = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        if sent:
            self.stat_replayed += 1
            logger.debug(f"[DeviceSource] 原生键盘误吞已补偿重放: "
                         f"VK 0x{p.vk:02X} {'down' if p.is_down else 'up'}")

    # ================= 设备台账 =================

    def _device_info(self, handle: int) -> dict:
        info = self._devices.get(handle)
        if info is not None:
            return info
        name = self._query_device_name(handle)
        ident = _parse_identity(name)
        info = {
            "handle": handle, "name": name,
            "friendly": _friendly_name(name) if name else "未知设备 (注入事件)",
            "hits": 0, "last_ts": 0.0, **ident,
        }
        info["remote"] = self._matches_binding(info)
        self._devices[handle] = info
        return info

    @staticmethod
    def _query_device_name(handle: int) -> str:
        if not handle:
            return ""
        size = wintypes.UINT(0)
        user32.GetRawInputDeviceInfoW(wintypes.HANDLE(handle), RIDI_DEVICENAME,
                                      None, ctypes.byref(size))
        if size.value == 0 or size.value > 4096:
            return ""
        buf = ctypes.create_unicode_buffer(size.value + 2)
        if user32.GetRawInputDeviceInfoW(wintypes.HANDLE(handle), RIDI_DEVICENAME,
                                         buf, ctypes.byref(size)) == 0xFFFFFFFF:
            return ""
        return buf.value

    def _enumerate_devices(self):
        """启动时枚举全部键盘设备 (让 UI 在用户按键前就能看到候选列表)。"""
        count = wintypes.UINT(0)
        item_size = ctypes.sizeof(RAWINPUTDEVICELIST)
        if user32.GetRawInputDeviceList(None, ctypes.byref(count), item_size) != 0:
            return
        if count.value == 0:
            return
        arr = (RAWINPUTDEVICELIST * count.value)()
        n = user32.GetRawInputDeviceList(arr, ctypes.byref(count), item_size)
        if n == 0xFFFFFFFF:
            return
        with self._lock:
            for i in range(n):
                if arr[i].dwType == RIM_TYPEKEYBOARD:
                    self._device_info(int(arr[i].hDevice or 0))

    # ================= GUI 快照 =================

    def snapshot(self) -> dict:
        now = time.time()
        with self._lock:
            devices = [
                {"friendly": d["friendly"], "vid": d["vid"], "pid": d["pid"],
                 "mac": d["mac"], "hits": d["hits"], "remote": d["remote"],
                 "active": now - d["last_ts"] < 1.0 if d["last_ts"] else False}
                for d in self._devices.values() if d.get("name")
            ]
            devices.sort(key=lambda d: (not d["remote"], -d["hits"]))
            return {
                "enabled": self.enabled,
                "running": self.is_running,
                "active": self.isolation_active,
                "learning": self._learning,
                "bound": self.is_bound,
                "bound_name": self.bound_name,
                "bound_id": self.bound_id_str() if self.is_bound else None,
                "last_source": self.last_source,
                "gate_open": (self.last_source == SOURCE_REMOTE
                              and now - self.last_remote_ts < ACTIVE_GATE_S),
                "remote_events": self.stat_remote,
                "native_exempt": self.stat_native,
                "replayed": self.stat_replayed,
                "mispredict": self.stat_mispredict,
                "authoritative": self.stat_authoritative,
                "devices": devices,
            }


arbiter = DeviceSourceArbiter()
