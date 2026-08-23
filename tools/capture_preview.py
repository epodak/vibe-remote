"""vRemote-Win 多页面预览截图工具 (capture_preview.py) — Mock 协调器, 不碰蓝牙/钩子。

用法:
    python vRemote_win/tools/capture_preview.py            # 浅色主题
    python vRemote_win/tools/capture_preview.py dark       # 深色主题
    python vRemote_win/tools/capture_preview.py both       # 两套都出

2026-08-23 修正: 旧版 show() 后直接 grab(), 布局尚未收敛就截图 —— 状态行的值
被拍成"已"/"拦"这类半截字, 让人误以为是真实缺陷。现在每次截图前显式跑一轮
快照分发 + 两次事件循环 + 强制 layout activate, 拍到的才是稳定态。
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from PyQt6.QtWidgets import QApplication

from core.key_mapper import KeyMapper


class MockAudioPipe:
    device_idx = 6
    device_info = {"name": "扬声器 (ToDesk Virtual Audio)", "default_samplerate": 48000}
    mix_system_mic = True
    mix_x6 = True
    x6_gain = 1.0
    mic_gain = 1.0
    is_running = False
    mic_level_db = -22.5


class MockBle:
    is_connected = True


class MockArbiter:
    """预览用的设备源仲裁替身 (数字取自一次真实使用后的量级)。"""

    enabled = True
    is_running = True

    def snapshot(self):
        return {
            "enabled": True, "running": True, "active": True, "learning": False,
            "bound": True, "bound_name": "HID Keyboard Device",
            "bound_id": "MAC B0:EF:D7:8B:56:AC",
            "last_source": "native", "gate_open": False,
            "remote_events": 1204, "native_exempt": 8932,
            "replayed": 3, "authoritative": 987,
            "devices": [
                {"friendly": "HID Keyboard Device", "vid": None, "pid": None,
                 "mac": "B0EFD78B56AC", "hits": 1204, "remote": True, "active": False},
                {"friendly": "Standard PS/2 Keyboard", "vid": None, "pid": None,
                 "mac": None, "hits": 8210, "remote": False, "active": True},
                {"friendly": "HID Keyboard Device", "vid": "1C4F", "pid": "0002",
                 "mac": None, "hits": 722, "remote": False, "active": False},
            ],
        }

    def start_learning(self):
        pass

    def unbind(self):
        pass


class MockSuppressor:
    intercept_enabled = True


class MockCoordinator:
    mac_address = "B0:EF:D7:8B:56:AC"
    ble_bridge = MockBle()
    audio_pipe = MockAudioPipe()
    search_suppressor = MockSuppressor()
    trigger_mode = "click"
    text_delivery = "clipboard"
    asr_locale = "zh"
    hotkey_target = "vokie"
    max_session_s = 60
    click_debounce_s = 0.4
    recordings_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "captured_audio"))
    session_start_time = 0

    def __init__(self):
        self.key_mapper = KeyMapper(keymap_path=tempfile.mktemp(suffix=".json"))
        self.key_mapper.apply_preset("viewer3d")
        self.device_arbiter = MockArbiter()

    def ui_snapshot(self):
        return {
            "ble": True, "hid": True, "session": False, "packets": 42,
            "delivery": "clipboard", "trigger_mode": "click", "hotkey_target": "vokie",
            "max_session_s": 60,
            "mic_level_db": -22.5, "x6_level_db": -18.2,
            "output_device": "扬声器 (ToDesk Virtual Audio)",
            "output_fanouts": [],
            "mix_mic": True, "mix_x6": True,
            "keymap": self.key_mapper.snapshot_maps(),
            "key_events": [],
            "intercept_enabled": True,
            "isolation": self.device_arbiter.snapshot(),
        }


def _settle(app, win, rounds: int = 3):
    """把布局跑到稳定态再截图 —— 快照分发会改文本, 改文本会触发重新布局。"""
    for _ in range(rounds):
        win._on_refresh_tick()
        win.layout().activate()
        app.processEvents()


def _shoot(app, win, out_dir, name):
    _settle(app, win)
    win.grab().save(os.path.join(out_dir, name), "PNG")


def capture(app, theme: str) -> str:
    from ui import style_theme
    style_theme.apply_theme(theme)
    from ui.main_hub_window import MainHubWindow

    coord = MockCoordinator()
    win = MainHubWindow(coord)
    win.show()

    suffix = "" if theme == "light" else f"_{theme}"
    out_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "assets", "preview"))
    os.makedirs(out_dir, exist_ok=True)

    pages = [
        (0, f"preview_audio{suffix}.png", None),
        (1, f"preview_mapping{suffix}.png",
         lambda: win.page_mapping.sync_key_events([("menu", True, 0), ("ok", True, 0)])),
        (2, f"preview_workbench{suffix}.png", lambda: _seed_workbench(win)),
        (3, f"preview_transcripts{suffix}.png", None),
        (4, f"preview_settings{suffix}.png", None),
    ]
    for idx, fname, prep in pages:
        win._on_nav_changed(idx)
        if prep:
            prep()
        app.processEvents()
        _shoot(app, win, out_dir, fname)

    # 背面全键盘
    win._on_nav_changed(1)
    win.page_mapping.sync_key_events([("menu", False, 0), ("ok", False, 0)])
    win.page_mapping._toggle_flip()
    _shoot(app, win, out_dir, f"preview_backside{suffix}.png")
    win.page_mapping._toggle_flip()
    # 必须显式收尾: win 一出作用域就被回收, 若页面里还有运行中的 QThread,
    # Qt 会以 "Destroyed while thread is still running" 直接 abort 掉整个进程
    win.shutdown()
    win.close()
    return out_dir


def _seed_workbench(win):
    now = time.time()
    win.page_workbench.sync_key_events([
        ("menu", True, now - 3), ("menu", False, now - 2.8),
        ("ok", True, now - 2), ("ok", False, now - 1.2),
        ("pg_up", True, now - 0.5), ("pg_up", False, now - 0.4),
        ("voice", True, now - 0.1),
    ])


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    from ui.style_theme import setup_app_font
    setup_app_font(app)

    arg = (sys.argv[1] if len(sys.argv) > 1 else "light").lower()
    themes = ["light", "dark"] if arg == "both" else [arg]
    for theme in themes:
        out = capture(app, theme)
        print(f"[OK] {theme} previews -> {out}")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
