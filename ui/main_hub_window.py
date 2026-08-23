"""vRemote-Win 主中枢窗口 (MainHubWindow)。

架构: GUI 主线程 100ms 轮询 coordinator.ui_snapshot() —— 每个周期只取一次快照,
统一分发给各视图 (含钩子事件流), 视图不得自行调用 ui_snapshot (事件流会被分食)。

视觉 (ui-skills 设计规则): 手绘线性图标导航、侧栏底部真实数据驱动的
会话脉冲灯 (标志性瞬间)、假装饰 (macOS 红绿灯点) 全部清除。
"""

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget
)

from ui import icons
from ui.style_theme import T, global_style
from ui.view_audio_devices import AudioDevicesView
from ui.view_hardware_workbench import HardwareWorkbenchView
from ui.view_mapping import MappingView
from ui.view_settings import SettingsView
from ui.view_transcripts import TranscriptsView


class NavIconButton(QPushButton):
    """线性图标 + 文字导航按钮 (图标笔画与文字字重匹配)"""

    def __init__(self, icon_name: str, text_str: str, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(88, 60)
        self.setObjectName("sidebar_nav_btn")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 7, 4, 7)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_icon = QLabel()
        self.lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_icon.setStyleSheet("background: transparent;")
        self.lbl_text = QLabel(text_str)
        self.lbl_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_text.setStyleSheet(
            f"font-size: 11px; font-weight: 600; color: {T.TEXT_MUTED}; background: transparent;")

        layout.addWidget(self.lbl_icon)
        layout.addWidget(self.lbl_text)
        self.setChecked(False)

    def setChecked(self, checked: bool):
        super().setChecked(checked)
        color = T.PRIMARY if checked else T.TEXT_MUTED
        weight = 700 if checked else 600
        self.lbl_icon.setPixmap(icons.icon_pixmap(self.icon_name, color, 20))
        self.lbl_text.setStyleSheet(
            f"font-size: 11px; font-weight: {weight}; color: {color}; background: transparent;")


class NavigationSidebar(QFrame):
    """侧边导航栏"""

    NAV = [
        ("link", "硬件链路", 0),
        ("gamepad", "按键映射", 1),
        ("gauge", "全能检测", 2),
        ("chat", "语音回眸", 3),
        ("gear", "偏好设置", 4),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar_panel")
        self.setFixedWidth(104)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 16, 10, 14)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # 品牌标: 圆角方块 + V 字 (真实标识, 不再放假 macOS 红绿灯)
        brand_row = QHBoxLayout()
        brand_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        brand_mark = QLabel("V")
        brand_mark.setFixedSize(26, 26)
        brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_mark.setStyleSheet(
            f"background: {T.PRIMARY}; color: {T.TEXT_ON_PRIMARY}; border-radius: 8px; "
            "font-size: 14px; font-weight: 800;")
        brand_row.addWidget(brand_mark)
        layout.addLayout(brand_row)
        layout.addSpacing(8)

        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)

        self.nav_buttons = []
        for icon_name, text_str, idx in self.NAV:
            btn = NavIconButton(icon_name, text_str, self)
            self.btn_group.addButton(btn, idx)
            layout.addWidget(btn)
            self.nav_buttons.append(btn)

        self.nav_buttons[0].setChecked(True)
        layout.addStretch(1)

        # 标志性瞬间: 真实会话状态脉冲灯 (主窗口快照驱动)
        self.live_chip = QLabel("● 启动中")
        self.live_chip.setObjectName("live_chip")
        self.live_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.live_chip)

        lbl_brand = QLabel("vRemote · X6")
        lbl_brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_brand.setStyleSheet(f"font-size: 10px; font-weight: 600; color: {T.TEXT_MUTED};")
        layout.addWidget(lbl_brand)

    def set_live_state(self, text: str, color: str):
        self.live_chip.setText(f"● {text}")
        self.live_chip.setStyleSheet(
            f"background: {color}14; color: {color}; border-radius: 9px; "
            "padding: 4px 10px; font-size: 10px; font-weight: 700;")


class MainHubWindow(QWidget):
    """主中枢视窗: 唯一快照分发点"""

    # 主题切换要重建整棵控件树才能全量换肤, 由 gui.py 持有窗口的一方来做
    themeChangeRequested = pyqtSignal(str)

    def __init__(self, coordinator=None, parent=None):
        super().__init__(parent)
        self.coord = coordinator
        self.setWindowTitle("vRemote — X6 硬件控制中枢")
        self.resize(1120, 760)
        self.setMinimumSize(1000, 680)
        self.setStyleSheet(global_style())

        root_h = QHBoxLayout(self)
        root_h.setContentsMargins(0, 0, 0, 0)
        root_h.setSpacing(0)

        self.sidebar = NavigationSidebar(self)
        self.sidebar.btn_group.idClicked.connect(self._on_nav_changed)
        root_h.addWidget(self.sidebar)

        self.stack = QStackedWidget(self)
        self.page_audio = AudioDevicesView(self.coord, self)
        self.page_mapping = MappingView(self.coord, self)
        self.page_workbench = HardwareWorkbenchView(self.coord, self)
        self.page_transcripts = TranscriptsView(self)
        self.page_settings = SettingsView(self.coord, self)
        self.page_settings.themeChangeRequested.connect(self.themeChangeRequested)

        self.stack.addWidget(self.page_audio)
        self.stack.addWidget(self.page_mapping)
        self.stack.addWidget(self.page_workbench)
        self.stack.addWidget(self.page_transcripts)
        self.stack.addWidget(self.page_settings)
        root_h.addWidget(self.stack, stretch=1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_refresh_tick)
        self.timer.start(100)

    def shutdown(self):
        """退出前收尾: 停轮询定时器与各页面的后台线程 (QThread 带着运行态析构会 abort)。"""
        self.timer.stop()
        for page in (self.page_audio, self.page_transcripts):
            fn = getattr(page, "shutdown", None)
            if fn:
                try:
                    fn()
                except Exception:
                    pass

    def closeEvent(self, e):
        self.shutdown()
        super().closeEvent(e)

    def _on_nav_changed(self, idx: int):
        self.stack.setCurrentIndex(idx)
        for i, btn in enumerate(self.sidebar.nav_buttons):
            btn.setChecked(i == idx)

    def _on_refresh_tick(self):
        if not self.coord:
            return
        s = self.coord.ui_snapshot()
        self.page_audio.update_snapshot(s)
        self.page_mapping.refresh(s)
        self.page_workbench.refresh(s)

        # 侧栏会话灯 (真实数据)
        if s.get("session"):
            self.sidebar.set_live_state("录音中", T.COLOR_RED)
        elif s.get("ble") and s.get("hid"):
            self.sidebar.set_live_state("X6 就绪", T.PRIMARY)
        elif s.get("ble"):
            self.sidebar.set_live_state("蓝牙在线", T.ACCENT)
        else:
            self.sidebar.set_live_state("重连中", T.ACCENT)

        events = s.get("key_events") or []
        if events:
            self.page_mapping.sync_key_events(events)
            self.page_workbench.sync_key_events(events)
