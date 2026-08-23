"""HUD 悬浮胶囊提示 (Heads-Up Display Capsule) — 2026-08-23 v2。

v2 变更:
  1. GUI 模式桥接: 主线程已有 QApplication (gui.py) 时, 胶囊挂到主线程事件循环
     (Qt 信号跨线程自动排队) —— 修复旧版在后台线程自起 QApplication 导致的
     HUD 静默消失; 控制台模式 (main.py) 仍走独立 HUD 守护线程。
  2. 视觉重构 (Instrument Panel 语言): 深海军蓝 #0B1220 + teal 状态点 +
     状态色 (teal/red/green/amber) + 120ms 淡入 + 350ms 淡出。
保留特性:
  - 鼠标拖拽 + hud_pos.json 位置持久化 + 多屏越界保护;
  - 悬停/拖拽暂停淡出, 松开恢复;
  - WA_ShowWithoutActivating 绝不抢焦点;
  - 线程安全 (任意线程可调 show_hud)。
"""
import atexit
import json
import os
import queue
import sys
import threading
from typing import Optional, Tuple

from .log import logger

_POS_CONFIG_FILE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hud_pos.json"))

# 状态色 (Instrument Panel)
ACCENTS = {
    "teal": "#5EEAD4",    # 进行中/中性
    "red": "#F87171",     # 录音中/失败
    "green": "#4ADE80",   # 完成
    "amber": "#FBBF24",   # 提醒/无语音
}

_hud_queue: queue.Queue = queue.Queue()
_gui_thread_started = False
_gui_lock = threading.Lock()
_bridge = None          # GUI 模式主线程桥
_bridge_lock = threading.Lock()


_pos_cache: Optional[Tuple[int, int]] = None
_pos_cache_valid = False


def _load_saved_pos() -> Optional[Tuple[int, int]]:
    """读取记忆位置 (进程内缓存 —— 转写心跳每 300ms 刷新一次胶囊,
    旧版每次都读盘, 一次会话能打出几百次无谓 IO)。"""
    global _pos_cache, _pos_cache_valid
    if _pos_cache_valid:
        return _pos_cache
    _pos_cache_valid = True
    _pos_cache = None
    try:
        if os.path.exists(_POS_CONFIG_FILE):
            with open(_POS_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            x, y = data.get("x"), data.get("y")
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                _pos_cache = (int(x), int(y))
    except Exception as e:
        logger.debug(f"读取 HUD 位置配置失败: {e!r}")
    return _pos_cache


def _save_pos(x: int, y: int):
    global _pos_cache, _pos_cache_valid
    _pos_cache, _pos_cache_valid = (int(x), int(y)), True
    try:
        with open(_POS_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"x": int(x), "y": int(y)}, f, indent=2)
        logger.info(f"📌 HUD 位置已记忆: ({x}, {y})")
    except Exception as e:
        logger.warning(f"保存 HUD 位置配置失败: {e!r}")


# ================= 胶囊窗口 (PyQt6, 懒加载) =================

_capsule_cls = None


def _capsule_class():
    global _capsule_cls
    if _capsule_cls is not None:
        return _capsule_cls
    from PyQt6.QtCore import (
        QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer
    )
    from PyQt6.QtGui import QColor, QFont
    from PyQt6.QtWidgets import (
        QApplication, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
        QVBoxLayout, QWidget
    )

    class CapsuleWindow(QWidget):
        """可拖拽、位置记忆的深色玻璃胶囊 (Instrument Panel 视觉)"""

        def __init__(self):
            super().__init__()
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.WindowStaysOnTopHint |
                Qt.WindowType.Tool |
                Qt.WindowType.WindowDoesNotAcceptFocus)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

            self._dragging = False
            self._drag_start_pos = QPoint()
            self._current_duration_ms = 1600
            self._visible_now = False

            root = QVBoxLayout(self)
            root.setContentsMargins(0, 0, 0, 0)
            self.container = QWidget(self)
            self.container.setCursor(Qt.CursorShape.SizeAllCursor)
            self.container.setStyleSheet(f"""
                QWidget {{
                    background-color: rgba(11, 18, 32, 0.96);
                    border: 1px solid {ACCENTS['teal']}44;
                    border-radius: 12px;
                }}
            """)
            row = QHBoxLayout(self.container)
            row.setContentsMargins(18, 11, 20, 11)
            row.setSpacing(10)

            # 状态点 (呼吸感来源: 状态色 10px 圆点)
            self.dot = QLabel(self.container)
            self.dot.setFixedSize(10, 10)
            self.dot.setStyleSheet(
                f"background: {ACCENTS['teal']}; border-radius: 5px; border: none;")
            row.addWidget(self.dot, alignment=Qt.AlignmentFlag.AlignVCenter)

            texts = QVBoxLayout()
            texts.setSpacing(1)
            self.title_label = QLabel(self.container)
            f_title = QFont("Segoe UI Variable Text")
            f_title.setPointSizeF(10.5)
            f_title.setWeight(QFont.Weight.DemiBold)
            self.title_label.setFont(f_title)
            self.title_label.setStyleSheet("color: #F8FAFC; background: transparent; border: none;")
            texts.addWidget(self.title_label)

            self.preview_label = QLabel(self.container)
            f_prev = QFont("Segoe UI Variable Text")
            f_prev.setPointSizeF(9.5)
            self.preview_label.setFont(f_prev)
            self.preview_label.setStyleSheet("color: rgba(248, 250, 252, 0.72); background: transparent; border: none;")
            self.preview_label.hide()
            texts.addWidget(self.preview_label)
            row.addLayout(texts)

            root.addWidget(self.container)

            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(28)
            shadow.setColor(QColor(11, 18, 32, 170))
            shadow.setOffset(0, 6)
            self.container.setGraphicsEffect(shadow)

            self.anim = None
            self.hide_timer = QTimer(self)
            self.hide_timer.setSingleShot(True)
            self.hide_timer.timeout.connect(self._fade_out)

        # ---------- 拖拽与悬停 ----------

        def mousePressEvent(self, event):
            if event.button() == Qt.MouseButton.LeftButton:
                self._dragging = True
                self._drag_start_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                self._pause_hide()
                event.accept()

        def mouseMoveEvent(self, event):
            if self._dragging and event.buttons() == Qt.MouseButton.LeftButton:
                self.move(event.globalPosition().toPoint() - self._drag_start_pos)
                event.accept()

        def mouseReleaseEvent(self, event):
            if event.button() == Qt.MouseButton.LeftButton and self._dragging:
                self._dragging = False
                cur = self.pos()
                _save_pos(cur.x(), cur.y())
                self._resume_hide()
                event.accept()

        def enterEvent(self, event):
            self._pause_hide()
            super().enterEvent(event)

        def leaveEvent(self, event):
            if not self._dragging:
                self._resume_hide()
            super().leaveEvent(event)

        def _pause_hide(self):
            if self.anim and self.anim.state() == QPropertyAnimation.State.Running:
                self.anim.stop()
            self.setWindowOpacity(1.0)
            self.hide_timer.stop()

        def _resume_hide(self):
            self.setWindowOpacity(1.0)
            self.hide_timer.start(self._current_duration_ms)

        # ---------- 显示 ----------

        def show_message(self, title: str, preview: Optional[str] = None,
                         duration_ms: int = 1600, accent: str = "teal"):
            color = ACCENTS.get(accent, ACCENTS["teal"])
            # 最短停留铁律: 任何消息至少活 2s, 防止连锁消息造成"闪一下就没"
            duration_ms = max(int(duration_ms), 2000)
            self._current_duration_ms = duration_ms
            self.dot.setStyleSheet(
                f"background: {color}; border-radius: 5px; border: none;")
            self.container.setStyleSheet(f"""
                QWidget {{
                    background-color: rgba(11, 18, 32, 0.96);
                    border: 1px solid {color}44;
                    border-radius: 12px;
                }}
            """)
            self.title_label.setText(title)
            if preview and preview.strip():
                disp = preview.strip()
                if len(disp) > 40:
                    disp = disp[:40] + "…"
                self.preview_label.setText(f"“{disp}”")
                self.preview_label.show()
            else:
                self.preview_label.hide()

            self.adjustSize()
            self._apply_position()

            was_hidden = not self._visible_now
            self._pause_hide()
            if was_hidden:
                # 首次出现: 120ms 淡入 (高频刷新时直接全量显示)
                self.setWindowOpacity(0.0)
                self.show()
                fin = QPropertyAnimation(self, b"windowOpacity")
                fin.setDuration(120)
                fin.setStartValue(0.0)
                fin.setEndValue(1.0)
                fin.setEasingCurve(QEasingCurve.Type.OutCubic)
                fin.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
            else:
                self.show()
            self._visible_now = True
            self.hide_timer.start(duration_ms)

        def _apply_position(self):
            saved = _load_saved_pos()
            screen = QApplication.primaryScreen().availableGeometry()
            if saved:
                x, y = saved
                min_x = screen.left() - self.width() + 40
                max_x = screen.right() - 40
                min_y, max_y = screen.top(), screen.bottom() - 30
                if min_x <= x <= max_x and min_y <= y <= max_y:
                    self.move(x, y)
                    return
            self.move(screen.left() + (screen.width() - self.width()) // 2,
                      screen.top() + 52)

        def _fade_out(self):
            if self._dragging:
                return
            self._visible_now = False
            self.anim = QPropertyAnimation(self, b"windowOpacity")
            self.anim.setDuration(350)
            self.anim.setStartValue(1.0)
            self.anim.setEndValue(0.0)
            self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.anim.finished.connect(self.hide)
            self.anim.start()

        def closeEvent(self, event):
            self._visible_now = False
            super().closeEvent(event)

    _capsule_cls = CapsuleWindow
    return _capsule_cls


# ================= GUI 模式: 主线程桥 =================

def _create_bridge():
    """在主线程创建桥与胶囊窗口 (只能在 QApplication 所在线程调用)。"""
    from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

    class HudBridge(QObject):
        message = pyqtSignal(str, object, int, str)

        def __init__(self):
            super().__init__()
            self._win = None
            self.message.connect(self._on_message)  # 跨线程自动排队到主线程

        @pyqtSlot(str, object, int, str)
        def _on_message(self, title, preview, duration_ms, accent):
            try:
                if self._win is None:
                    self._win = _capsule_class()()
                self._win.show_message(title, preview, duration_ms, accent)
            except Exception as e:
                logger.warning(f"HUD 主线程显示失败: {e!r}")

    bridge = HudBridge()
    # 预创建窗口, 避免首次按键时才初始化
    bridge._win = _capsule_class()()
    return bridge


def attach_to_app() -> bool:
    """GUI 入口在创建 QApplication 后调用 (主线程): 立即创建 HUD 桥与胶囊窗口。

    返回是否成功。必须在 QApplication 所在线程调用; 之后任意线程的
    show_hud 都会经 Qt 信号排队到主线程显示。
    """
    global _bridge
    from PyQt6.QtCore import QThread
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return False
    with _bridge_lock:
        if _bridge is not None:
            return True
        if QThread.currentThread() is not app.thread():
            logger.warning("attach_to_app 必须在主线程调用")
            return False
        try:
            _bridge = _create_bridge()
            logger.info("  💬 [HUD] 已挂载主线程桥 (GUI 模式)")
            return True
        except Exception as e:
            logger.warning(f"HUD 桥创建失败: {e!r}")
            return False


def _get_bridge():
    """GUI 模式返回主线程桥; 未挂载或控制台模式 (无 QApplication) 返回 None。"""
    global _bridge
    if _bridge is not None:
        return _bridge
    try:
        from PyQt6.QtWidgets import QApplication
    except Exception:
        return None
    if QApplication.instance() is None:
        return None
    # 主线程内可以直接补建 (如测试环境未显式 attach); 后台线程不允许碰 GUI 对象
    from PyQt6.QtCore import QThread
    app = QApplication.instance()
    if QThread.currentThread() is app.thread():
        with _bridge_lock:
            if _bridge is None:
                try:
                    _bridge = _create_bridge()
                except Exception as e:
                    logger.warning(f"HUD 桥创建失败: {e!r}")
    return _bridge


# ================= 控制台模式: 独立 HUD 守护线程 =================

def _start_gui_thread_if_needed():
    global _gui_thread_started
    with _gui_lock:
        if _gui_thread_started:
            return
        t = threading.Thread(target=_qt_gui_loop, name="HUD_Toast_Thread", daemon=True)
        t.start()
        _gui_thread_started = True


def _qt_gui_loop():
    try:
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if not app:
            app = QApplication(sys.argv)
            app.setQuitOnLastWindowClosed(False)

        win = _capsule_class()()

        def _check_queue():
            try:
                while True:
                    item = _hud_queue.get_nowait()
                    if item is None:
                        if win.anim and win.anim.state() == win.anim.State.Running:
                            win.anim.stop()
                        win.hide_timer.stop()
                        timer.stop()
                        win.close()
                        app.quit()
                        return
                    title, preview, duration_ms, accent = item
                    win.show_message(title, preview, duration_ms, accent)
            except queue.Empty:
                pass

        timer = QTimer()
        timer.timeout.connect(_check_queue)
        timer.start(20)
        app.exec()
    except Exception as e:
        logger.warning(f"PyQt6 HUD 初始化失败, 降级至轻量模式: {e!r}")
        _fallback_gui_loop()


def _fallback_gui_loop():
    """Tkinter 零依赖降级 (支持拖拽与记忆, 忽略状态色)。"""
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.92)
        root.configure(bg="#0B1220")

        label = tk.Label(root, text="", font=("Microsoft YaHei UI", 11, "bold"),
                         fg="#F8FAFC", bg="#0B1220", padx=20, pady=10, cursor="fleur")
        label.pack()

        hide_after_id = None
        drag_data = {"x": 0, "y": 0}

        def on_press(event):
            drag_data["x"], drag_data["y"] = event.x, event.y
            if hide_after_id:
                root.after_cancel(hide_after_id)

        def on_motion(event):
            root.geometry(f"+{root.winfo_x() + event.x - drag_data['x']}"
                          f"+{root.winfo_y() + event.y - drag_data['y']}")

        def on_release(event):
            _save_pos(root.winfo_x(), root.winfo_y())
            nonlocal hide_after_id
            hide_after_id = root.after(1600, _hide)

        label.bind("<ButtonPress-1>", on_press)
        label.bind("<B1-Motion>", on_motion)
        label.bind("<ButtonRelease-1>", on_release)

        def _hide():
            root.withdraw()

        def _check_queue():
            nonlocal hide_after_id
            try:
                while True:
                    item = _hud_queue.get_nowait()
                    if item is None:
                        if hide_after_id:
                            root.after_cancel(hide_after_id)
                        root.destroy()
                        return
                    title, preview, duration_ms, _accent = item
                    label.config(text=f"{title}\n{preview}" if preview else title)
                    root.update_idletasks()
                    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
                    saved = _load_saved_pos()
                    x, y = saved if saved else ((root.winfo_screenwidth() - w) // 2, 52)
                    root.geometry(f"{w}x{h}+{x}+{y}")
                    root.deiconify()
                    if hide_after_id:
                        root.after_cancel(hide_after_id)
                    hide_after_id = root.after(duration_ms, _hide)
            except queue.Empty:
                pass
            root.after(30, _check_queue)

        root.after(30, _check_queue)
        root.mainloop()
    except Exception as e:
        logger.error(f"Fallback HUD 启动失败: {e!r}")


# ================= 公共入口 =================

def show_hud(title: str, preview: Optional[str] = None,
             duration_ms: int = 1600, accent: str = "teal"):
    """跨线程调起 HUD 胶囊。accent: teal/red/green/amber。

    GUI 模式 (主线程已有 QApplication) 走主线程桥; 控制台模式走独立守护线程。
    """
    try:
        bridge = _get_bridge()
        if bridge is not None:
            bridge.message.emit(title, preview, duration_ms, accent)
            return
        _start_gui_thread_if_needed()
        _hud_queue.put((title, preview, duration_ms, accent))
    except Exception as e:
        logger.warning(f"触发 HUD 提示失败: {e!r}")


def _cleanup_qt():
    """解释器退出时通知 GUI 线程收尾 (仅控制台模式使用队列)。"""
    try:
        if _gui_thread_started:
            _hud_queue.put(None)
    except Exception:
        pass


atexit.register(_cleanup_qt)
