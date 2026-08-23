"""vRemote-Win GUI 入口。

架构: asyncio 守护线程内跑 X6SessionCoordinator (与控制台版完全复用),
GUI 主线程 100ms 轮询 ui_snapshot() 刷新 —— GUI 不直接触碰 BLE/音频。
运行: python vRemote_win/gui.py  (勿与 main.py 同时运行, 单实例抢 GATT)

2026-08-23 v2:
  · 启动时套用 user_settings.json (主题 / 触发模式 / 投递通道 / 隔离开关 / 增益);
  · 托盘从"显示面板 + 退出"两项扩展为可用的控制面板: 实时状态、一键暂停全局
    拦截 (与 Ctrl+Alt+F12 同一开关)、直达日志目录 —— 面板关掉后仍然能操作;
  · 主题切换就地重建窗口 (调色板 token 在构造期解析, 重建才能全量换肤)。
"""

import asyncio
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from config import (REMOTE_MAC, VOICE_TRIGGER_HOTKEY, VOICE_TRIGGER_MODE,
                    CLICK_DEBOUNCE_MS, HOLD_RELEASE_TIMEOUT_MS, MAX_SESSION_MS,
                    AUDIO_OUTPUT_KEYWORDS, AUDIO_MIX_SYSTEM_MIC, AUDIO_MIX_X6,
                    AUDIO_X6_GAIN, AUDIO_MIC_GAIN, TEXT_DELIVERY, ASR_LOCALE,
                    RECORDINGS_DIR)
from core import user_settings
from core.log import logger
from core.session_coordinator import X6SessionCoordinator


# ================= 守护线程: asyncio + Coordinator =================

def _daemon_main(coord, ready: threading.Event):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    coord_task = loop.create_task(coord.start())
    _daemon_main.loop, _daemon_main.task = loop, coord_task
    ready.set()
    loop.run_until_complete(coord_task)


_daemon_main.loop = None
_daemon_main.task = None


# ================= 托盘 =================

def _tray_pixmap(accent: str) -> QPixmap:
    pm = QPixmap(32, 32)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(accent))
    p.drawEllipse(3, 3, 26, 26)
    p.setPen(QColor(16, 24, 40))
    p.setFont(QFont("Microsoft YaHei UI", 13, QFont.Weight.Bold))
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "V")
    p.end()
    return pm


class TrayController:
    """托盘图标 + 菜单 + 状态回显。

    面板可以被关掉, 托盘不会 —— 所以"暂停/恢复全局拦截"这类**救急操作**必须
    在这里也能点到, 而不是只藏在窗口里。
    """

    COLORS = {"recording": "#F87171", "ready": "#4ADE80",
              "paused": "#FBBF24", "offline": "#94A3B8"}

    def __init__(self, app, coord, show_window):
        self.app = app
        self.coord = coord
        self._state = None

        self.tray = QSystemTrayIcon(QIcon(_tray_pixmap(self.COLORS["offline"])), app)
        menu = QMenu()
        self.act_show = menu.addAction("显示控制面板")
        self.act_show.triggered.connect(show_window)
        menu.addSeparator()
        self.act_intercept = menu.addAction("暂停全局拦截 (Ctrl+Alt+F12)")
        self.act_intercept.triggered.connect(self._toggle_intercept)
        self.act_logs = menu.addAction("打开日志目录")
        self.act_logs.triggered.connect(self._open_logs)
        menu.addSeparator()
        menu.addAction("退出 vRemote").triggered.connect(app.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: show_window()
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.setToolTip("vRemote — X6 硬件控制中枢")
        self.tray.show()

        self.timer = QTimer(app)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(700)

    def _toggle_intercept(self):
        sup = getattr(self.coord, "search_suppressor", None)
        if sup:
            sup.set_intercept_enabled(not sup.intercept_enabled)

    @staticmethod
    def _open_logs():
        logdir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "logs"))
        if os.path.exists(logdir):
            os.startfile(logdir)

    def refresh(self):
        try:
            s = self.coord.ui_snapshot()
        except Exception:
            return
        intercept = s.get("intercept_enabled", True)
        if not intercept:
            state, tip = "paused", "全局拦截已暂停 — 按键原样透传"
        elif s.get("session"):
            state, tip = "recording", f"录音中 · 已收 {s.get('packets', 0)} 个语音包"
        elif s.get("ble"):
            iso = s.get("isolation") or {}
            tip = "X6 就绪"
            if iso.get("active"):
                tip += f" · 隔离生效 (已豁免物理键盘 {iso.get('native_exempt', 0)} 次)"
            elif iso.get("running"):
                tip += " · 隔离待绑定设备"
            state = "ready"
        else:
            state, tip = "offline", "蓝牙重连中 — 按遥控器任意键唤醒"

        self.act_intercept.setText(
            "恢复全局拦截 (Ctrl+Alt+F12)" if not intercept else "暂停全局拦截 (Ctrl+Alt+F12)")
        if state != self._state:
            self._state = state
            self.tray.setIcon(QIcon(_tray_pixmap(self.COLORS[state])))
        self.tray.setToolTip(f"vRemote — {tip}")


# ================= 入口 =================

def main():
    from core import single_instance
    holder = single_instance.acquire()
    if holder:
        msg = (f"已有 vRemote 实例在运行 (PID {holder})。\n\n"
               "同时运行两个实例会互相抢占 X6 蓝牙 (GATT ProtocolError)。\n"
               f"请先结束旧实例: taskkill /F /PID {holder}")
        logger.error(msg.replace("\n", " "))
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, "vRemote 单实例保护", 0x10)  # MB_ICONERROR
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # QSS 跨机器一致渲染

    from ui import style_theme
    prefs = user_settings.load()
    style_theme.apply_theme(prefs.get("theme", "light"))
    style_theme.setup_app_font(app)  # 注入纯净雅黑、子像素抗锯齿与高质渲染策略
    app.setQuitOnLastWindowClosed(False)

    # HUD 胶囊挂载主线程桥 (必须在主线程、app 创建后立即调用)
    from core import hud_toast
    hud_toast.attach_to_app()

    coord = X6SessionCoordinator(
        mac_address=REMOTE_MAC, hotkey_target=VOICE_TRIGGER_HOTKEY,
        trigger_mode=VOICE_TRIGGER_MODE, click_debounce_ms=CLICK_DEBOUNCE_MS,
        hold_release_timeout_ms=HOLD_RELEASE_TIMEOUT_MS, max_session_ms=MAX_SESSION_MS,
        audio_output_keywords=AUDIO_OUTPUT_KEYWORDS, audio_mix_system_mic=AUDIO_MIX_SYSTEM_MIC,
        audio_mix_x6=AUDIO_MIX_X6, audio_x6_gain=AUDIO_X6_GAIN, audio_mic_gain=AUDIO_MIC_GAIN,
        text_delivery=TEXT_DELIVERY, asr_locale=ASR_LOCALE, recordings_dir=RECORDINGS_DIR)
    # config.py 是静态默认, 用户在 GUI 里的选择优先 —— 必须在协调器 start() 之前套用
    user_settings.apply_to_coordinator(coord)

    ready = threading.Event()
    th = threading.Thread(target=_daemon_main, args=(coord, ready), daemon=True)
    th.start()
    ready.wait(5)

    from ui.main_hub_window import MainHubWindow

    holder_win = {}

    def _build_window(show: bool = True):
        win = MainHubWindow(coord)
        win.themeChangeRequested.connect(_switch_theme)
        holder_win["win"] = win
        if show:
            win.show()
        return win

    def _show_window():
        win = holder_win.get("win")
        if win is None:
            win = _build_window()
        win.show()
        win.raise_()
        win.activateWindow()

    def _switch_theme(name: str):
        if not style_theme.apply_theme(name):
            return
        old = holder_win.get("win")
        was_visible = bool(old and old.isVisible())
        idx = old.stack.currentIndex() if old else 0
        if old is not None:
            old.shutdown()
            old.close()
            old.deleteLater()
        win = _build_window(show=was_visible)
        win._on_nav_changed(idx)   # 停在用户刚才那一页, 而不是弹回首页
        logger.info(f"  🎨 [GUI] 已切换主题: {name}")

    # ---------------- 优雅退出与信号处理 (单次 Ctrl+C 即刻退出) ----------------
    import signal

    def _sigint_handler(sig, frame):
        logger.info("\n⏹️ [GUI] 收到 Ctrl+C，正在退出...")
        # 立即停止钩子与仲裁器，切断系统级消息循环阻塞
        try:
            coord.search_suppressor.stop()
            coord.device_arbiter.stop()
        except Exception:
            pass
        app.quit()

    try:
        signal.signal(signal.SIGINT, _sigint_handler)
    except Exception:
        pass

    # Windows 下 PyQt 事件循环需要心跳唤醒 Python 解释器处理信号
    sig_timer = QTimer(app)
    sig_timer.timeout.connect(lambda: None)
    sig_timer.start(150)

    _build_window(show=not prefs.get("start_minimized", False))
    tray = TrayController(app, coord, _show_window)

    # 环境变量 VREMOTE_GUI_AUTOCLOSE=毫秒: 自动化冒烟用
    if os.environ.get("VREMOTE_GUI_AUTOCLOSE"):
        QTimer.singleShot(int(os.environ["VREMOTE_GUI_AUTOCLOSE"]), app.quit)

    ret = 0
    try:
        ret = app.exec()
    except KeyboardInterrupt:
        logger.info("\n⏹️ [GUI] 收到 Ctrl+C，正在退出...")
    finally:
        sig_timer.stop()
        tray.timer.stop()
        win = holder_win.get("win")
        if win is not None:
            win.shutdown()
        if _daemon_main.loop and _daemon_main.task:
            try:
                _daemon_main.loop.call_soon_threadsafe(_daemon_main.task.cancel)
            except Exception:
                pass
        th.join(timeout=0.6)
        single_instance.release()
        logger.info("  👋 [GUI] vRemote 已安全退出。")
    return ret


if __name__ == "__main__":
    sys.exit(main())
