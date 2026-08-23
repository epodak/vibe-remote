"""用户偏好持久化 (user_settings.json) —— 让 GUI 里改的设置活过重启。

分层原则:
  config.py          静态默认 + 安全边界 (去抖窗口、状态机时序等, 改动需评估)
  user_settings.json 用户在 GUI 里能改的那部分, 覆盖 config 默认值
  运行时对象属性      协调器/音频管线的即时状态 (由 GUI 直接回写, 同时落盘)

写入采用"改一项存一次"的小文件全量覆盖 —— 配置只有十几个键, 无需增量。
读失败一律回退默认, 绝不因为配置损坏而拒绝启动。
"""

import json
import os
import threading

from .log import logger

_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "user_settings.json"))

# 允许持久化的键 -> 校验器 (未列出的键一律丢弃, 防止配置文件被写脏)
_SCHEMA = {
    "trigger_mode":     lambda v: v in ("click", "hold"),
    "text_delivery":    lambda v: v in ("clipboard", "vokie"),
    "asr_locale":       lambda v: v in ("zh", "en"),
    "max_session_s":    lambda v: isinstance(v, (int, float)) and 10 <= v <= 300,
    "isolation_enabled": lambda v: isinstance(v, bool),
    "auto_paste":       lambda v: isinstance(v, bool),
    "restore_clipboard": lambda v: isinstance(v, bool),
    "theme":            lambda v: v in ("light", "dark"),
    "x6_gain":          lambda v: isinstance(v, (int, float)) and 0.05 <= v <= 40,
    "mic_gain":         lambda v: isinstance(v, (int, float)) and 0.05 <= v <= 40,
    "start_minimized":  lambda v: isinstance(v, bool),
}

DEFAULTS = {
    "trigger_mode": "hold",
    "isolation_enabled": True,
    "auto_paste": True,
    "restore_clipboard": False,
    "theme": "light",
    "start_minimized": False,
}

_lock = threading.Lock()
_cache = None


def load() -> dict:
    """读取全部有效设置 (带进程内缓存)。"""
    global _cache
    with _lock:
        if _cache is not None:
            return dict(_cache)
        data = dict(DEFAULTS)
        try:
            with open(_PATH, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                for k, v in raw.items():
                    check = _SCHEMA.get(k)
                    if check:
                        try:
                            if check(v):
                                data[k] = v
                        except Exception:
                            pass
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"  ⚠️ [Settings] user_settings.json 解析失败, 使用默认值: {e}")
        _cache = data
        return dict(data)


def get(key: str, default=None):
    return load().get(key, DEFAULTS.get(key, default))


def set_value(key: str, value) -> bool:
    """写入一项 (键不在白名单或校验失败则忽略)。返回是否真正写入。"""
    check = _SCHEMA.get(key)
    if not check:
        return False
    try:
        if not check(value):
            return False
    except Exception:
        return False
    load()  # 确保缓存已建立
    with _lock:
        if _cache.get(key) == value:
            return True
        _cache[key] = value
        snapshot = dict(_cache)
    try:
        tmp = _PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, _PATH)   # 原子替换: 断电/崩溃不会留下半个配置
    except OSError as e:
        logger.warning(f"  ⚠️ [Settings] 保存失败: {e}")
        return False
    return True


def apply_to_coordinator(coord) -> list:
    """把已保存的偏好应用到协调器 (启动时调用)。返回生效项描述列表。"""
    data = load()
    applied = []
    for attr, key in (("trigger_mode", "trigger_mode"),
                      ("text_delivery", "text_delivery"),
                      ("asr_locale", "asr_locale")):
        if key in data:
            setattr(coord, attr, data[key])
            applied.append(f"{key}={data[key]}")
    if "max_session_s" in data:
        coord.max_session_s = float(data["max_session_s"])
        applied.append(f"max_session_s={data['max_session_s']}")
    ap = getattr(coord, "audio_pipe", None)
    if ap is not None:
        for attr in ("x6_gain", "mic_gain"):
            if attr in data:
                setattr(ap, attr, float(data[attr]))
                applied.append(f"{attr}={data[attr]:.2f}")
    arb = getattr(coord, "device_arbiter", None)
    if arb is not None:
        arb.enabled = bool(data.get("isolation_enabled", True))
        applied.append(f"isolation={'on' if arb.enabled else 'off'}")
    if applied:
        logger.info(f"  ⚙️ [Settings] 已应用用户偏好: {', '.join(applied)}")
    return applied
