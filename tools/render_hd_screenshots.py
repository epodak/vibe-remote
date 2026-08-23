"""
High-Definition UI Renderer for vibe-remote (render_hd_screenshots.py)
生成 2x 超高清、抗锯齿、字体和矢量图锐利的真实 UI 截图。
"""

import os
import sys
import tempfile
import time

# 启用高 DPI 渲染
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPainter, QPixmap
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
    mic_level_db = -60.0


class MockBle:
    is_connected = True


class MockArbiter:
    enabled = True
    is_running = True

    def snapshot(self):
        return {
            "enabled": True, "running": True, "active": True, "learning": False,
            "bound": True, "bound_name": "HID Keyboard Device",
            "bound_id": "MAC B0:EF:D7:8B:56:AC",
            "last_source": "native", "gate_open": False,
            "remote_events": 0, "native_exempt": 21,
            "replayed": 0, "authoritative": 987,
            "devices": [
                {"friendly": "HID Keyboard Device", "vid": "1C4F", "pid": "0002",
                 "mac": None, "hits": 9, "remote": False, "active": False},
                {"friendly": "\\\\?\\Microsoft Keyboard RID\\0", "vid": None, "pid": None,
                 "mac": None, "hits": 4, "remote": False, "active": False},
                {"friendly": "Standard PS/2 Keyboard", "vid": None, "pid": None,
                 "mac": None, "hits": 0, "remote": False, "active": True},
                {"friendly": "HID Keyboard Device", "vid": None, "pid": None,
                 "mac": None, "hits": 0, "remote": False, "active": False},
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
    trigger_mode = "hold"
    text_delivery = "vokie"
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
            "ble": True, "hid": True, "session": False, "packets": 0,
            "delivery": "vokie", "trigger_mode": "hold", "hotkey_target": "vokie",
            "max_session_s": 60,
            "mic_level_db": -60.0, "x6_level_db": -60.0,
            "output_device": "扬声器 (ToDesk Virtual Audio)",
            "output_fanouts": [
                "扬声器 (ToDesk Virtual Audio)",
                "扬声器 (ToDesk Virtual Audio)",
                "扬声器 (ToDesk Virtual Audio)"
            ],
            "mix_mic": True, "mix_x6": True,
            "keymap": self.key_mapper.snapshot_maps(),
            "key_events": [],
            "intercept_enabled": True,
            "isolation": self.device_arbiter.snapshot(),
        }


def _seed_transcripts(transcripts_file):
    lines = [
        '{"ts": 1787500211, "time_str": "2026-08-23 12:50:11", "text": "Hello. How are you?Hello.", "duration_ms": 782, "source": "voice"}\n',
        '{"ts": 1787495046, "time_str": "2026-08-23 11:24:06", "text": "Hello. How are you?", "duration_ms": 604, "source": "voice"}\n',
        '{"ts": 1787495027, "time_str": "2026-08-23 11:23:47", "text": "Hello, hello, how are you?Hello, hello, how are you?", "duration_ms": 752, "source": "voice"}\n',
        '{"ts": 1787495014, "time_str": "2026-08-23 11:23:34", "text": "Hello.How are you?What\'s going on here?", "duration_ms": 812, "source": "voice"}\n',
        '{"ts": 1787493967, "time_str": "2026-08-23 11:06:07", "text": "电瓶，麦克风电瓶，麦克风电瓶，麦克风电瓶。", "duration_ms": 736, "source": "voice"}\n',
        '{"ts": 1787493854, "time_str": "2026-08-23 11:04:14", "text": "Hello, what\'s y\'all here?", "duration_ms": 1040, "source": "voice"}\n'
    ]
    with open(transcripts_file, "w", encoding="utf-8") as f:
        f.writelines(lines)


def render_hd_capture():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    
    from ui import style_theme
    style_theme.setup_app_font(app)
    style_theme.apply_theme("light")
    
    from ui.main_hub_window import MainHubWindow
    
    # 模拟真实 transcripts
    temp_trans = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "transcripts.jsonl"))
    _seed_transcripts(temp_trans)
    
    coord = MockCoordinator()
    win = MainHubWindow(coord)
    win.resize(1160, 820)
    win.show()
    
    out_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "assets", "screenshots"))
    os.makedirs(out_dir, exist_ok=True)
    
    # 强制预热与稳定布局
    for _ in range(5):
        win._on_refresh_tick()
        win.layout().activate()
        app.processEvents()
        time.sleep(0.02)
        
    pages = [
        (1, "01_keymap.png"),          # 按键映射
        (0, "02_hardware_audio.png"),   # 硬件与语音链路
        (2, "03_workbench.png"),        # 全能检测工作台
        (3, "04_transcripts.png"),      # 语音回眸
        (4, "05_settings.png"),         # 偏好设置
    ]
    
    scale_factor = 2.0  # 2x 超采样渲染 (2320 x 1640)
    
    for idx, fname in pages:
        win._on_nav_changed(idx)
        for _ in range(3):
            win._on_refresh_tick()
            win.layout().activate()
            app.processEvents()
            time.sleep(0.02)
            
        target_size = win.size() * int(scale_factor)
        pix = QPixmap(target_size)
        pix.setDevicePixelRatio(scale_factor)
        pix.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        win.render(painter)
        painter.end()
        
        save_path = os.path.join(out_dir, fname)
        img = pix.toImage()
        img.save(save_path, "PNG")
        
        # 使用 PIL 进一步压缩优化体积（保持 2320x1640 2K 绝对清晰度）
        try:
            from PIL import Image
            with Image.open(save_path) as im:
                im_rgb = im.convert("RGB")
                im_rgb.save(save_path, "PNG", optimize=True)
        except Exception:
            pass
            
        size_kb = os.path.getsize(save_path) / 1024
        print(f"✅ Rendered 2K HD: {save_path} ({pix.width()}x{pix.height()}, {size_kb:.1f} KB)")
        
    win.shutdown()
    win.close()
    print("🎉 All 5 HD screenshots successfully rendered!")


if __name__ == "__main__":
    render_hd_capture()
    sys.exit(0)
