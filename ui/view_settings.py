"""偏好设置页 (view_settings.py) — 2026-08-23 v3。

演进轨迹:
  v1 下拉/数字框是纯摆设, 改了不生效 —— 已废除;
  v2 控件接上协调器, 改动即时生效, 但**重启即丢**;
  v3 (本版) 每一项都同时写回运行时对象与 user_settings.json, 活过重启;
     并补上此前只能改代码的三件事: 输入源隔离开关 / 自动粘贴行为 / 外观主题。

分区原则: 一屏之内按"改它会影响什么"分组, 而不是按控件类型堆砌 ——
语音交互 → 文本投递 → 输入源隔离 → 外观 → 诊断与维护。
"""

import os
import time

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget
)

from core import user_settings
from ui import icons
from ui.style_theme import MONO, T, current_theme, setup_combo_box
from ui.widgets import ToggleSwitch


class SettingRow(QFrame):
    """单条设置卡片行"""

    def __init__(self, title: str, description: str, control: QWidget, parent=None):
        super().__init__(parent)
        self.setObjectName("card")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 13, 20, 13)
        layout.setSpacing(16)

        info_v = QVBoxLayout()
        info_v.setSpacing(3)
        lbl_t = QLabel(title)
        lbl_t.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {T.TEXT_PRIMARY};")
        info_v.addWidget(lbl_t)
        if description:
            lbl_d = QLabel(description)
            lbl_d.setWordWrap(True)
            lbl_d.setStyleSheet(f"font-size: 12px; color: {T.TEXT_MUTED};")
            info_v.addWidget(lbl_d)

        layout.addLayout(info_v, stretch=1)
        layout.addWidget(control, alignment=Qt.AlignmentFlag.AlignVCenter)


def _section(title: str, icon_name: str) -> QWidget:
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    h = QHBoxLayout(w)
    h.setContentsMargins(4, 8, 0, 0)
    h.setSpacing(8)
    ic = QLabel()
    ic.setPixmap(icons.icon_pixmap(icon_name, T.TEXT_MUTED, 15))
    ic.setStyleSheet("background: transparent;")
    h.addWidget(ic)
    lbl = QLabel(title)
    lbl.setStyleSheet(
        f"font-size: 11px; font-weight: bold; color: {T.TEXT_MUTED}; "
        "letter-spacing: 1px; background: transparent;")
    h.addWidget(lbl)
    h.addStretch(1)
    return w


class SettingsView(QWidget):
    """偏好设置视图 (真实生效 + 持久化)"""

    themeChangeRequested = pyqtSignal(str)

    def __init__(self, coordinator=None, parent=None):
        super().__init__(parent)
        self.coord = coordinator
        self._loading = True
        self._init_ui()
        self._init_values()
        self._loading = False

    # ---------------- 构建 ----------------

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        root = QVBoxLayout(inner)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(10)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        head = QVBoxLayout()
        head.setSpacing(2)
        t = QLabel("偏好设置")
        t.setObjectName("page_title")
        s = QLabel("语音交互 · 文本投递 · 输入源隔离 · 外观 —— 改动即时生效并写入 user_settings.json")
        s.setObjectName("page_subtitle")
        head.addWidget(t)
        head.addWidget(s)
        root.addLayout(head)

        # ============ 语音交互 ============
        root.addWidget(_section("语音交互", "mic"))

        self.cmb_trigger = QComboBox()
        setup_combo_box(self.cmb_trigger)
        self.cmb_trigger.addItem("click · 按一下开始 / 再按一下上屏 (推荐)", "click")
        self.cmb_trigger.addItem("hold · 按住说话 / 松开结束", "hold")
        self.cmb_trigger.setFixedWidth(320)
        self.cmb_trigger.currentIndexChanged.connect(
            lambda: self._apply("trigger_mode", self.cmb_trigger.currentData()))
        root.addWidget(SettingRow(
            "语音键触发逻辑",
            "X6 语音键 HID 为脉冲连发, click 只认边沿最鲁棒; hold 依赖 BLE MIC_CLOSE 信令",
            self.cmb_trigger))

        self.spin_max = QSpinBox()
        self.spin_max.setRange(10, 300)
        self.spin_max.setSuffix(" 秒")
        self.spin_max.setFixedWidth(120)
        self.spin_max.valueChanged.connect(lambda v: self._apply("max_session_s", v))
        root.addWidget(SettingRow(
            "单次录音保护上限",
            "click 模式下会话超过该时长由看门狗强制结束, 防按键误触挂死录音",
            self.spin_max))

        # ============ 文本投递 ============
        root.addWidget(_section("文本投递", "chat"))

        self.cmb_deliver = QComboBox()
        setup_combo_box(self.cmb_deliver)
        self.cmb_deliver.addItem("clipboard · 本地裸 ASR 直投 (快速, 免配置)", "clipboard")
        self.cmb_deliver.addItem("vokie · 原生听写 (云端 2-Pass + LLM 润色, 高质量)", "vokie")
        self.cmb_deliver.setFixedWidth(360)
        self.cmb_deliver.currentIndexChanged.connect(
            lambda: self._apply("text_delivery", self.cmb_deliver.currentData()))
        root.addWidget(SettingRow(
            "转写文本投递通道",
            "clipboard: 会话结束 → vokie HTTP 裸转写 → 剪贴板 + 自动粘贴 (跳过 LLM 润色, 文字偏口语)。"
            "vokie 原生: 右Alt 唤起 vokie 全套三级管线 (流式 ASR → 云端多模态 2-Pass → LLM 润色), "
            "需在 vokie 里把输入设备选成虚拟声卡麦克风 (硬件链路页有链路自检)",
            self.cmb_deliver))

        self.cmb_locale = QComboBox()
        setup_combo_box(self.cmb_locale)
        self.cmb_locale.addItem("中文 (zh)", "zh")
        self.cmb_locale.addItem("English (en)", "en")
        self.cmb_locale.setFixedWidth(170)
        self.cmb_locale.currentIndexChanged.connect(
            lambda: self._apply("asr_locale", self.cmb_locale.currentData()))
        root.addWidget(SettingRow("转写语言", "vokie 本地离线转写的识别语言", self.cmb_locale))

        self.sw_paste = ToggleSwitch()
        self.sw_paste.mousePressEvent = self._toggler(self.sw_paste, "auto_paste")
        root.addWidget(SettingRow(
            "转写完成后自动粘贴",
            "关掉后文本只进剪贴板不按 Ctrl+V —— 适合光标常不在输入框、或目标应用会把粘贴当快捷键的场景",
            self.sw_paste))

        self.sw_restore = ToggleSwitch()
        self.sw_restore.mousePressEvent = self._toggler(self.sw_restore, "restore_clipboard")
        root.addWidget(SettingRow(
            "粘贴后还原原剪贴板",
            "开启后转写文本只是「过路」: 粘贴完成 0.45s 后把你原来复制的内容放回剪贴板。"
            "代价是粘贴失败时文本不再留在剪贴板, 故默认关闭",
            self.sw_restore))

        # ============ 输入源隔离 ============
        root.addWidget(_section("输入源隔离", "shield"))

        self.sw_isolation = ToggleSwitch()
        self.sw_isolation.mousePressEvent = self._toggler(self.sw_isolation, "isolation_enabled")
        root.addWidget(SettingRow(
            "Raw Input 设备源隔离",
            "开启后只有 X6 遥控器的按键会被映射与拦截, 你的物理键盘逐事件豁免 "
            "(Enter / Backspace / Esc 不再被吞)。关闭则退回旧行为: 全局钩子对所有键盘一视同仁",
            self.sw_isolation))

        iso_ops = QWidget()
        iso_ops.setStyleSheet("background: transparent;")
        ops_h = QHBoxLayout(iso_ops)
        ops_h.setContentsMargins(0, 0, 0, 0)
        ops_h.setSpacing(8)
        btn_learn = QPushButton("学习遥控器设备")
        btn_learn.setObjectName("secondary_btn")
        btn_learn.clicked.connect(self._learn_device)
        ops_h.addWidget(btn_learn)
        btn_unbind = QPushButton("解除绑定")
        btn_unbind.setObjectName("secondary_btn")
        btn_unbind.clicked.connect(self._unbind_device)
        ops_h.addWidget(btn_unbind)
        root.addWidget(SettingRow(
            "受控设备绑定",
            "X6 走 BLE HID, 其设备路径内嵌遥控器 MAC, 正常情况下开机即自动绑定, 无需手动操作。"
            "只有换了遥控器 / 自动识别失败时才需要在这里手动学习",
            iso_ops))

        self.lbl_escape = QLabel("Ctrl + Alt + F12")
        self.lbl_escape.setStyleSheet(
            f"background: {T.BG_CHIP}; color: {T.TEXT_PRIMARY}; border: 1px solid {T.BORDER_SOFT}; "
            f"border-radius: 8px; padding: 6px 12px; font-family: {MONO}; font-size: 12px;")
        root.addWidget(SettingRow(
            "紧急逃生热键",
            "万一拦截出问题导致键盘不听使唤, 按这组键立刻暂停全局拦截 (所有按键原样透传), 再按一次恢复 —— 不必杀进程",
            self.lbl_escape))

        # ============ 外观 ============
        root.addWidget(_section("外观", "sun"))

        self.cmb_theme = QComboBox()
        setup_combo_box(self.cmb_theme)
        self.cmb_theme.addItem("浅色 · 冷纸灰仪表盘", "light")
        self.cmb_theme.addItem("深色 · 熄灯态仪表盘", "dark")
        self.cmb_theme.setFixedWidth(230)
        self.cmb_theme.currentIndexChanged.connect(self._on_theme_changed)
        root.addWidget(SettingRow(
            "界面主题",
            "切换后窗口会就地重建以套用新调色板 (运行中的蓝牙/录音会话不受影响)",
            self.cmb_theme))

        # ============ 诊断与维护 ============
        root.addWidget(_section("诊断与维护", "gauge"))

        diag = QWidget()
        diag.setStyleSheet("background: transparent;")
        dh = QHBoxLayout(diag)
        dh.setContentsMargins(0, 0, 0, 0)
        dh.setSpacing(8)
        btn_log = QPushButton("日志目录")
        btn_log.setObjectName("secondary_btn")
        btn_log.clicked.connect(self._open_logs)
        dh.addWidget(btn_log)
        btn_rec = QPushButton("录音目录")
        btn_rec.setObjectName("secondary_btn")
        btn_rec.clicked.connect(self._open_recordings)
        dh.addWidget(btn_rec)
        root.addWidget(SettingRow(
            "打开诊断目录",
            "loguru 全链路日志 (BLE GATT 握手 / ADPCM 解码 / ASR 响应 / 按键映射) 与录音归档",
            diag))

        clean = QWidget()
        clean.setStyleSheet("background: transparent;")
        ch = QHBoxLayout(clean)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(8)
        self.spin_keep = QSpinBox()
        self.spin_keep.setRange(1, 365)
        self.spin_keep.setValue(7)
        self.spin_keep.setSuffix(" 天前")
        self.spin_keep.setFixedWidth(110)
        ch.addWidget(self.spin_keep)
        btn_clean = QPushButton("清理")
        btn_clean.setObjectName("danger_btn")
        btn_clean.clicked.connect(self._clean_recordings)
        ch.addWidget(btn_clean)
        root.addWidget(SettingRow(
            "清理历史录音",
            "captured_audio/ 每次会话都会新增一个 WAV 且从不自动回收 —— 长期使用会悄悄吃掉数 GB 磁盘",
            clean))
        self.lbl_clean = QLabel("")
        self.lbl_clean.setStyleSheet(f"font-size: 11px; color: {T.TEXT_MUTED}; padding-left: 22px;")
        root.addWidget(self.lbl_clean)

        self.lbl_ro = QLabel("…")
        self.lbl_ro.setWordWrap(True)
        self.lbl_ro.setStyleSheet(f"font-size: 11px; color: {T.TEXT_MUTED}; font-family: {MONO};")
        self.lbl_ro.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(SettingRow(
            "只读运行参数",
            "状态机安全边界 (去抖窗口等), 改动需评估时序影响, 走 config.py",
            self.lbl_ro))

        root.addStretch(1)
        footer = QLabel("vRemote-Win · X6 语音飞鼠交互中枢 —— 静态默认在 config.py, 用户偏好在 user_settings.json")
        footer.setStyleSheet(f"font-size: 11px; color: {T.TEXT_LIGHT};")
        root.addWidget(footer)

    # ---------------- 初值回填 ----------------

    def _init_values(self):
        saved = user_settings.load()
        self.cmb_theme.setCurrentIndex(0 if current_theme() == "light" else 1)
        self.sw_paste.setChecked(bool(saved.get("auto_paste", True)))
        self.sw_restore.setChecked(bool(saved.get("restore_clipboard", False)))

        if not self.coord:
            self.lbl_ro.setText("(预览模式)")
            self.sw_isolation.setChecked(bool(saved.get("isolation_enabled", True)))
            return

        self.cmb_trigger.setCurrentIndex(0 if self.coord.trigger_mode == "click" else 1)
        self.cmb_deliver.setCurrentIndex(0 if self.coord.text_delivery == "clipboard" else 1)
        self.spin_max.setValue(int(self.coord.max_session_s))
        self.cmb_locale.setCurrentIndex(0 if self.coord.asr_locale == "zh" else 1)
        arb = getattr(self.coord, "device_arbiter", None)
        self.sw_isolation.setChecked(bool(getattr(arb, "enabled", True)) if arb else False)
        self.lbl_ro.setText(
            f"MAC {self.coord.mac_address} · 去抖 {int(self.coord.click_debounce_s * 1000)} ms · "
            f"热键 {self.coord.hotkey_target}\n录音归档 {self.coord.recordings_dir or '—'}")

    # ---------------- 应用与持久化 ----------------

    def _toggler(self, switch: ToggleSwitch, key: str):
        """把拨杆的点击接到"运行时生效 + 落盘"上 (ToggleSwitch 无信号, 直接换 handler)。"""
        def handler(_event, sw=switch, k=key):
            sw.setChecked(not sw.isChecked())
            self._apply(k, sw.isChecked())
        return handler

    def _apply(self, key, value):
        if self._loading or value is None:
            return
        user_settings.set_value(key, value)
        if not self.coord:
            return
        if key in ("trigger_mode", "text_delivery", "asr_locale"):
            setattr(self.coord, key, value)
        elif key == "max_session_s":
            self.coord.max_session_s = float(value)
        elif key == "isolation_enabled":
            arb = getattr(self.coord, "device_arbiter", None)
            if arb is not None:
                arb.enabled = bool(value)
        # auto_paste / restore_clipboard 由 core.text_delivery 在投递时按需读取

    def _on_theme_changed(self):
        if self._loading:
            return
        theme = self.cmb_theme.currentData()
        user_settings.set_value("theme", theme)
        self.themeChangeRequested.emit(theme)

    # ---------------- 动作 ----------------

    def _learn_device(self):
        arb = getattr(self.coord, "device_arbiter", None)
        if arb:
            arb.start_learning()

    def _unbind_device(self):
        arb = getattr(self.coord, "device_arbiter", None)
        if arb:
            arb.unbind()

    def _open_logs(self):
        logdir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "logs"))
        if os.path.exists(logdir):
            os.startfile(logdir)

    def _open_recordings(self):
        rec = getattr(self.coord, "recordings_dir", None) if self.coord else None
        if rec and os.path.isdir(rec):
            os.startfile(rec)

    def _clean_recordings(self):
        rec = getattr(self.coord, "recordings_dir", None) if self.coord else None
        if not (rec and os.path.isdir(rec)):
            self.lbl_clean.setText("没有可清理的录音目录。")
            return
        cutoff = time.time() - self.spin_keep.value() * 86400
        removed = freed = 0
        for name in os.listdir(rec):
            if not name.lower().endswith(".wav"):
                continue
            path = os.path.join(rec, name)
            try:
                st = os.stat(path)
                if st.st_mtime < cutoff:
                    os.remove(path)
                    removed += 1
                    freed += st.st_size
            except OSError:
                continue
        self.lbl_clean.setText(
            f"已清理 {removed} 个录音, 释放 {freed / 1048576:.1f} MB。" if removed
            else f"{self.spin_keep.value()} 天前没有可清理的录音。")
