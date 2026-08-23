"""X6 实体按键 -> 鼠标动作映射引擎 (产品化 tools/test_airmouse_click.py 的交互)。

设计要点:
1. 钩子回调内只做 mouse_event 快速注入 (微秒级 syscall), 不做任何带 sleep 的
   验证注入 —— 遵守项目 "LL 钩子零重活" 铁律;
2. X6 固件是脉冲式按键 (down 连发无稳定 up), 触发类动作 (单击/切换锁定/滚轮)
   一律按 down 边沿 + 250ms 去抖窗口判定, 与语音键状态机同一套哲学;
3. 映射持久化在 keymap.json, 预设方案内置 (标准遥控 / 3D 查看器), 用户改任何
   单键即进入 "自定义" 方案;
4. 语音键 (0xAA) 与 e 键 (0xB6) 由 SearchSuppressor 专属逻辑处理, 不在本表内。
"""

import ctypes
import json
import os
import threading
import time
from ctypes import wintypes
from collections import deque
from .log import logger

user32 = ctypes.windll.user32
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.WPARAM]

LEFTDOWN, LEFTUP = 0x0002, 0x0004
RIGHTDOWN, RIGHTUP = 0x0008, 0x0010
MIDDLEDOWN, MIDDLEUP = 0x0020, 0x0040
WHEEL = 0x0800
WHEEL_DELTA = 120
INJECTED_TAG = 0x0000BEEF  # dwExtraInfo 标记, 供诊断区分本模块注入的鼠标事件

# ---------------- 键表 (实测 VK, 与 tools/test_airmouse_click.py 一致) ----------------

KEYS = {
    "ok":       {"vk": 0x0D, "name": "OK / 确认键", "icon": "OK"},
    "menu":     {"vk": 0x5D, "name": "菜单键 ≡", "icon": "≡"},
    "del":      {"vk": 0x2E, "name": "Del 删除键", "icon": "Del"},
    "back":     {"vk": 0xA6, "name": "返回键 ←", "icon": "←"},
    "esc":      {"vk": 0x1B, "name": "ESC 键", "icon": "Esc"},
    "backspace": {"vk": 0x08, "name": "退格键", "icon": "⌫"},
    "home":     {"vk": 0xAC, "name": "主页键 ⌂", "icon": "⌂"},
    "up":       {"vk": 0x26, "name": "方向上 ▲", "icon": "▲"},
    "down":     {"vk": 0x28, "name": "方向下 ▼", "icon": "▼"},
    "left":     {"vk": 0x25, "name": "方向左 ◀", "icon": "◀"},
    "right":    {"vk": 0x27, "name": "方向右 ▶", "icon": "▶"},
    "pg_up":    {"vk": 0x21, "name": "翻页+ PgUp", "icon": "Pg+"},
    "pg_down":  {"vk": 0x22, "name": "翻页- PgDn", "icon": "Pg-"},
    "vol_up":   {"vk": 0xAF, "name": "音量 ＋", "icon": "V+"},
    "vol_down": {"vk": 0xAE, "name": "音量 －", "icon": "V-"},
    "mute":     {"vk": 0xAD, "name": "静音键", "icon": "MUT"},
}
VK_TO_KEY = {k["vk"]: kid for kid, k in KEYS.items()}

# ---------------- 动作表 ----------------

ACTIONS = {
    "passthrough":   {"name": "系统默认 (透传)", "desc": "按键原样交给 Windows 处理"},
    "block":         {"name": "拦截吞噬", "desc": "什么都不做, 防误触 (右键锁定中会顺带解锁)"},
    "left_click":    {"name": "鼠标左键单击", "desc": "单击一次鼠标左键"},
    "left_hold":     {"name": "鼠标左键按住拖拽", "desc": "按住=左键按下, 松开=弹起 (3D 旋转 Orbit)"},
    "right_click":   {"name": "鼠标右键单击", "desc": "单击一次鼠标右键"},
    "right_toggle":  {"name": "右键单击锁定平移", "desc": "按一下锁定右键 🔒 挥腕平移, 再按解锁 (3D 平移 Pan)"},
    "right_hold":    {"name": "右键按住平移", "desc": "按住=右键按下, 松开=弹起"},
    "wheel_up":      {"name": "滚轮向上 (放大)", "desc": "单击滚动一格滚轮向上 (3D 缩放 Zoom)"},
    "wheel_down":    {"name": "滚轮向下 (缩小)", "desc": "单击滚动一格滚轮向下"},
}

# 内置预设方案 (3D 查看器 = test_airmouse_click.py 的实测交互)
PRESETS = {
    "default": {
        "name": "标准遥控",
        "desc": "所有按键透传给系统, X6 原生多媒体行为",
        "maps": {},
    },
    "viewer3d": {
        "name": "3D 查看器",
        "desc": "OK 按住旋转 · 菜单/Del 锁定平移 · Pg± 缩放 · 返回防跳页 (来自 test_airmouse_click)",
        "maps": {
            "ok": "left_hold",
            "menu": "right_toggle",
            "del": "right_toggle",
            "back": "block",
            "esc": "block",
            "backspace": "block",
            "pg_up": "wheel_up",
            "pg_down": "wheel_down",
        },
    },
}

# 触发类动作: 只认 down 边沿 + 去抖 (X6 脉冲连发防重)
_EDGE_ACTIONS = {"left_click", "right_click", "right_toggle", "wheel_up", "wheel_down", "block"}


class KeyMapper:
    """线程安全 (钩子线程调用 handle_hook_key, GUI 线程调用 set_key_action/apply_preset)。"""

    def __init__(self, keymap_path=None):
        self.path = keymap_path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "keymap.json")
        self.lock = threading.Lock()
        self.active_profile = "default"
        self.maps = {}          # key_id -> action_id (当前生效)
        self.profile_name = PRESETS["default"]["name"]
        self.right_locked = False
        self.left_down = False
        self._last_fire = {}    # key_id -> ts (边沿去抖)
        self._down_seen = set() # 物理按下中的键 (hold 类动作的 up 判定)
        # UI 事件流: GUI 轮询 drain; 每项 (key_id, is_down, ts)
        self._events = deque(maxlen=64)

        self._load()

    # ---------------- 持久化 ----------------

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self.active_profile = data.get("active", "default")
            self.maps = {k: v for k, v in data.get("maps", {}).items()
                         if k in KEYS and v in ACTIONS}
            self.profile_name = data.get("profile_name", "自定义")
            logger.info(f"  🎮 [KeyMapper] 载入方案 '{self.profile_name}' ({len(self.maps)} 个映射)")
        except FileNotFoundError:
            self.apply_preset("default", save=False)
        except Exception as e:
            logger.warning(f"  ⚠️ [KeyMapper] keymap.json 解析失败, 回退标准方案: {e}")
            self.apply_preset("default", save=False)

    def _save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"active": self.active_profile, "profile_name": self.profile_name,
                           "maps": self.maps}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"  ⚠️ [KeyMapper] 保存失败: {e}")

    # ---------------- GUI 侧 API ----------------

    def apply_preset(self, preset_id: str, save=True):
        p = PRESETS.get(preset_id)
        if not p:
            return
        with self.lock:
            self.active_profile = preset_id
            self.profile_name = p["name"]
            self.maps = dict(p["maps"])
        if save:
            self._save()
        logger.info(f"  🎮 [KeyMapper] 应用预设方案: {p['name']}")

    def set_key_action(self, key_id: str, action_id: str):
        if key_id not in KEYS or action_id not in ACTIONS:
            return
        with self.lock:
            if action_id == "passthrough":
                self.maps.pop(key_id, None)
            else:
                self.maps[key_id] = action_id
            self.active_profile = "custom"
            self.profile_name = "自定义"
        self._save()

    def snapshot_maps(self):
        with self.lock:
            return {"profile": self.active_profile, "profile_name": self.profile_name,
                    "maps": dict(self.maps), "right_locked": self.right_locked}

    def drain_events(self):
        with self.lock:
            evts = list(self._events)
            self._events.clear()
            return evts

    def record_event(self, key_id: str, is_down: bool):
        """供协调器补充记录不在键表内的事件 (如语音键, 由抑制器专属处理)。"""
        with self.lock:
            self._events.append((key_id, is_down, time.time()))

    # ---------------- 钩子侧: LL 键盘回调 (必须快进快出) ----------------

    def handle_hook_key(self, vk: int, is_down: bool) -> bool:
        """返回 True = 拦截该事件 (不下发系统), False = 透传。"""
        now = time.time()
        key_id = VK_TO_KEY.get(vk)
        if key_id is None:
            # 未知键码 (背面 QWERTY 等): 不裁决, 但记录供工作台显像
            with self.lock:
                self._events.append((f"0x{vk:02X}", is_down, now))
            return False
        with self.lock:
            action = self.maps.get(key_id)
            if not action:
                self._events.append((key_id, is_down, now))
                return False  # 未映射 -> 透传, 但仍记录事件供 UI 显像
            self._events.append((key_id, is_down, now))

        # ---- 以下动作均设计为 O(1) 快速注入, 无 sleep/验证循环 ----
        if action in ("left_hold", "right_hold"):
            return self._hold_action(key_id, action, is_down)
        if not is_down:
            return True  # 触发类动作不看 up (X6 脉冲 up 无意义), up 一律吞掉
        # down 边沿去抖: 脉冲连发/系统 auto-repeat 只算一次
        with self.lock:
            if now - self._last_fire.get(key_id, 0.0) < 0.25:
                return True
            self._last_fire[key_id] = now
        return self._edge_action(key_id, action)

    def _hold_action(self, key_id: str, action: str, is_down: bool) -> bool:
        flag_down, flag_up = (LEFTDOWN, LEFTUP) if action == "left_hold" else (RIGHTDOWN, RIGHTUP)
        with self.lock:
            if is_down:
                if key_id in self._down_seen:
                    return True  # 脉冲连发的重复 down
                self._down_seen.add(key_id)
                self.left_down = (action == "left_hold")
            else:
                if key_id not in self._down_seen:
                    return True
                self._down_seen.discard(key_id)
                if action == "left_hold":
                    self.left_down = False
        # mouse_event 放锁外: syscall 快, 但绝不持业务锁
        user32.mouse_event(flag_down if is_down else flag_up, 0, 0, 0, INJECTED_TAG)
        return True

    def _edge_action(self, key_id: str, action: str) -> bool:
        if action == "block":
            # 右键锁定中按任意拦截键 -> 顺带解锁 (对齐 test_airmouse_click 的返回键语义)
            with self.lock:
                if self.right_locked:
                    self.right_locked = False
                    need_up = True
                else:
                    need_up = False
            if need_up:
                user32.mouse_event(RIGHTUP, 0, 0, 0, INJECTED_TAG)
            return True
        if action == "left_click":
            user32.mouse_event(LEFTDOWN, 0, 0, 0, INJECTED_TAG)
            user32.mouse_event(LEFTUP, 0, 0, 0, INJECTED_TAG)
            return True
        if action == "right_click":
            user32.mouse_event(RIGHTDOWN, 0, 0, 0, INJECTED_TAG)
            user32.mouse_event(RIGHTUP, 0, 0, 0, INJECTED_TAG)
            return True
        if action == "right_toggle":
            with self.lock:
                self.right_locked = not self.right_locked
                locked = self.right_locked
            user32.mouse_event(RIGHTDOWN if locked else RIGHTUP, 0, 0, 0, INJECTED_TAG)
            logger.info(f"  🖱️ [KeyMapper] 右键{'锁定 🔒 (挥腕平移)' if locked else '释放 🔓'}")
            return True
        if action == "wheel_up":
            user32.mouse_event(WHEEL, 0, 0, WHEEL_DELTA, INJECTED_TAG)
            return True
        if action == "wheel_down":
            user32.mouse_event(WHEEL, 0, 0, -WHEEL_DELTA, INJECTED_TAG)
            return True
        return True

    # ---------------- 收尾卫生 ----------------

    def release_all(self):
        """退出/异常时复位本引擎维持的鼠标状态。"""
        with self.lock:
            need_right_up = self.right_locked
            need_left_up = self.left_down
            self.right_locked = False
            self.left_down = False
            self._down_seen.clear()
        if need_right_up:
            user32.mouse_event(RIGHTUP, 0, 0, 0, INJECTED_TAG)
        if need_left_up:
            user32.mouse_event(LEFTUP, 0, 0, 0, INJECTED_TAG)
