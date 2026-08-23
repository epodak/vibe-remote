"""全能检测工作台 (view_hardware_workbench.py) — 2026-08-23 重构。

旧版: 假报文流 / 假回报率 / 假延迟 —— 已废除。
新版 (全部真实):
1. 实时按键显像仪 — LL 钩子捕获的真实 VK/扫描事件 (含未知键码)
2. 键位打卡矩阵 — key_mapper.KEYS 16 键, 物理按下即点亮
3. 输入源隔离面板 — Raw Input 设备仲裁的绑定/来源/豁免与补偿计数
   (隔离生效后事件流只收录遥控器按键 —— 物理键盘的击键根本不进映射引擎,
    顺带消除了旧版"把用户每一次敲击都记进事件流"的隐私问题)
4. X6 声学电平 (dBFS 实时, 带峰值保持) + 链路统计 + 真实事件流

2026-08-23: 「鼠标轨迹预览」卡撤下 —— 它演示的是本机鼠标而非遥控器飞鼠,
对排障没有信息量; 位置让给真正能定位问题的输入源仲裁面板。
"""

import time

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QLinearGradient, QPainter
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget
)

from core.key_mapper import KEYS
from ui import icons
from ui.panel_isolation import IsolationCard
from ui.style_theme import T, MONO
from ui.widgets import StatusRow, attach_shadow


class AudioVuMeter(QWidget):
    """X6 声学电平条 (dBFS 真实值)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.level_db = -60.0
        self.setFixedHeight(16)

    def set_level(self, db: float):
        self.level_db = max(-60.0, min(0.0, db))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(T.BORDER_SOFT))
        fill_w = int(w * (self.level_db + 60.0) / 60.0)
        if fill_w > 0:
            grad = QLinearGradient(0, 0, w, 0)
            grad.setColorAt(0.0, QColor(f"{T.COLOR_GREEN_DOT}"))
            grad.setColorAt(0.7, QColor(f"{T.ACCENT}"))
            grad.setColorAt(1.0, QColor(f"{T.COLOR_RED}"))
            p.fillRect(0, 0, fill_w, h, grad)


class HardwareWorkbenchView(QWidget):
    """智能飞鼠硬件检测工作台 (真实数据)"""

    # 不在 key_mapper.KEYS 内但会被记录的键 (语音键由抑制器专属处理)
    EXTRA_NAMES = {"voice": ("语音麦克风", 0xAA)}

    def __init__(self, coordinator=None, parent=None):
        super().__init__(parent)
        self.coord = coordinator
        self.tested_keys = set()
        self.key_chips = {}
        self._peak_db = -60.0
        self._peak_ts = 0.0
        self._init_ui()

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 20, 32, 20)
        root.setSpacing(14)

        head = QHBoxLayout()
        title_v = QVBoxLayout()
        title_v.setSpacing(2)
        lbl_title = QLabel("全能检测工作台")
        lbl_title.setObjectName("page_title")
        lbl_sub = QLabel("真实按键显像 · 键位打卡 · 输入源仲裁 · X6 声学电平 —— 按下遥控器任意键即可观察")
        lbl_sub.setObjectName("page_subtitle")
        title_v.addWidget(lbl_title)
        title_v.addWidget(lbl_sub)
        head.addLayout(title_v, stretch=1)
        btn_reset = QPushButton("重置打卡")
        btn_reset.setObjectName("secondary_btn")
        btn_reset.clicked.connect(self._reset_coverage)
        head.addWidget(btn_reset)
        root.addLayout(head)

        grid = QGridLayout()
        grid.setSpacing(14)

        # ==== 卡1: 按键显像仪 + 打卡矩阵 ====
        card_keys = QFrame()
        card_keys.setObjectName("card")
        attach_shadow(card_keys)
        ck = QVBoxLayout(card_keys)
        ck.setContentsMargins(18, 14, 18, 14)
        ck.setSpacing(10)

        ck_head = QHBoxLayout()
        ck_head.setSpacing(8)
        ic1 = QLabel(); ic1.setPixmap(icons.icon_pixmap("keyboard", T.PRIMARY, 18))
        ic1.setStyleSheet("background: transparent;")
        ck_head.addWidget(ic1)
        ck_head.addWidget(QLabel("实时按键显像仪 & 键位打卡", objectName="card_title"))
        ck_head.addStretch(1)
        self.lbl_coverage = QLabel("0 / 17 键已打卡")
        self.lbl_coverage.setStyleSheet(
            f"font-size: 11px; font-weight: bold; color: {T.COLOR_GREEN_TEXT}; font-family: {MONO};")
        ck_head.addWidget(self.lbl_coverage)
        ck.addLayout(ck_head)

        self.lbl_hero_key = QLabel("等待按键… (按一下遥控器上的任意键)")
        self.lbl_hero_key.setFixedHeight(42)
        self.lbl_hero_key.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_hero_key.setStyleSheet(
            f"background-color: {T.BG_TERMINAL}; color: {T.TEXT_TERMINAL_HERO}; font-size: 15px; "
            f"font-weight: bold; border-radius: 8px; font-family: {MONO};")
        ck.addWidget(self.lbl_hero_key)

        chip_wrap = QWidget()
        chip_grid = QGridLayout(chip_wrap)
        chip_grid.setContentsMargins(0, 0, 0, 0)
        chip_grid.setSpacing(4)
        for i, (kid, info) in enumerate(KEYS.items()):
            lbl = QLabel(info["icon"])
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFixedSize(46, 24)
            lbl.setToolTip(info["name"])
            lbl.setStyleSheet(
                f"background-color: {T.BG_CHIP}; color: {T.TEXT_MUTED}; border-radius: 8px; "
                f"font-size: 11px; font-weight: bold; border: 1px solid {T.BORDER_SOFT};")
            chip_grid.addWidget(lbl, i // 8, i % 8)
            self.key_chips[kid] = lbl
        # 第 17 格: 语音键 (不在映射表内, 由转写状态机专属处理)
        vlbl = QLabel("MIC")
        vlbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vlbl.setFixedSize(46, 24)
        vlbl.setToolTip("语音麦克风 (转写专用)")
        vlbl.setStyleSheet(
            f"background-color: {T.BG_CHIP}; color: {T.TEXT_MUTED}; border-radius: 8px; "
            f"font-size: 11px; font-weight: bold; border: 1px solid {T.BORDER_SOFT};")
        chip_grid.addWidget(vlbl, len(KEYS) // 8, len(KEYS) % 8)
        self.key_chips["voice"] = vlbl
        ck.addWidget(chip_wrap)
        grid.addWidget(card_keys, 0, 0)

        # ==== 卡2: 输入源隔离 (Raw Input 设备仲裁) ====
        self.card_isolation = IsolationCard(self.coord, self)
        grid.addWidget(self.card_isolation, 0, 1)

        # ==== 卡3: X6 声学电平 ====
        card_audio = QFrame()
        card_audio.setObjectName("card")
        attach_shadow(card_audio)
        ca = QVBoxLayout(card_audio)
        ca.setContentsMargins(18, 14, 18, 14)
        ca.setSpacing(8)
        ah = QHBoxLayout()
        ah.setSpacing(8)
        ic3 = QLabel(); ic3.setPixmap(icons.icon_pixmap("mic", T.PRIMARY, 18))
        ic3.setStyleSheet("background: transparent;")
        ah.addWidget(ic3)
        ah.addWidget(QLabel("X6 语音声学通道 (16kHz ADPCM)", objectName="card_title"))
        ca.addLayout(ah)
        cap2 = QLabel("按遥控器语音键录音, 观察真实 dBFS 电平跳动:")
        cap2.setStyleSheet(f"font-size: 11px; color: {T.TEXT_MUTED};")
        ca.addWidget(cap2)
        self.vu_meter = AudioVuMeter(card_audio)
        ca.addWidget(self.vu_meter)
        db_row = QHBoxLayout()
        self.lbl_db = QLabel("-60.0 dB")
        self.lbl_db.setStyleSheet(f"font-size: 11px; color: {T.PRIMARY}; font-weight: bold; font-family: {MONO};")
        db_row.addWidget(self.lbl_db)
        db_row.addStretch(1)
        self.lbl_peak = QLabel("峰值 -60.0 dB")
        self.lbl_peak.setStyleSheet(f"font-size: 11px; color: {T.ACCENT}; font-family: {MONO};")
        db_row.addWidget(self.lbl_peak)
        ca.addLayout(db_row)

        self.row_packets = StatusRow("ADPCM 语音包")
        self.row_delivery = StatusRow("文本投递通道")
        self.row_isolation = StatusRow("输入源隔离")
        for r in (self.row_packets, self.row_delivery, self.row_isolation):
            ca.addWidget(r)
        ca.addStretch(1)
        grid.addWidget(card_audio, 1, 0)

        # ==== 卡4: 链路统计 + 事件流 ====
        card_probe = QFrame()
        card_probe.setObjectName("card")
        attach_shadow(card_probe)
        cp = QVBoxLayout(card_probe)
        cp.setContentsMargins(18, 14, 18, 14)
        cp.setSpacing(6)
        ph = QHBoxLayout()
        ph.setSpacing(8)
        ic4 = QLabel(); ic4.setPixmap(icons.icon_pixmap("bluetooth", T.PRIMARY, 18))
        ic4.setStyleSheet("background: transparent;")
        ph.addWidget(ic4)
        ph.addWidget(QLabel("链路统计 & 真实按键事件流", objectName="card_title"))
        cp.addLayout(ph)

        self.row_ble = StatusRow("蓝牙 ATVV")
        self.row_hid = StatusRow("HID 钩子")
        self.row_session = StatusRow("语音会话")
        for r in (self.row_ble, self.row_hid, self.row_session):
            cp.addWidget(r)

        self.lbl_stream = QLabel("")
        self.lbl_stream.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_stream.setStyleSheet(
            f"background-color: {T.BG_TERMINAL}; color: {T.TEXT_TERMINAL}; font-family: {MONO}; "
            "font-size: 10px; border-radius: 8px; padding: 8px;")
        cp.addWidget(self.lbl_stream, stretch=1)
        grid.addWidget(card_probe, 1, 1)

        root.addLayout(grid, stretch=1)

    # ---------------- 事件接入 (主窗口轮询分发) ----------------

    def _reset_coverage(self):
        self.tested_keys.clear()
        for chip in self.key_chips.values():
            chip.setStyleSheet(
                f"background-color: {T.BG_CHIP}; color: {T.TEXT_MUTED}; border-radius: 8px; "
                f"font-size: 11px; font-weight: bold; border: 1px solid {T.BORDER_SOFT};")
        self.lbl_coverage.setText(f"0 / {len(self.key_chips)} 键已打卡")
        self.lbl_hero_key.setText("已重置打卡记录")

    def sync_key_events(self, events: list):
        """真实钩子事件: [(key_id|'0x??', is_down, ts)]"""
        lines = []
        for key_id, is_down, ts in events[-9:]:
            t_str = time.strftime("%H:%M:%S", time.localtime(ts)) + f".{int(ts % 1 * 1000):03d}"
            edge = "down" if is_down else "up  "
            if key_id in KEYS:
                label = KEYS[key_id]["name"]
            elif key_id in self.EXTRA_NAMES:
                label = self.EXTRA_NAMES[key_id][0]
            else:
                label = f"未知键 {key_id}"
            lines.append(f"{t_str}  {edge}  {label}")
        if lines:
            prev = self.lbl_stream.text().splitlines() if self.lbl_stream.text() else []
            merged = (lines + prev)[:9]
            self.lbl_stream.setText("\n".join(merged))

            key_id, is_down, _ = events[-1]
            if is_down:
                if key_id in KEYS:
                    name, vk_hex = KEYS[key_id]["name"], KEYS[key_id]["vk"]
                elif key_id in self.EXTRA_NAMES:
                    name, vk_hex = self.EXTRA_NAMES[key_id]
                else:
                    name, vk_hex = key_id, None
                self.lbl_hero_key.setText(
                    f"{name} · VK 0x{vk_hex:02X}" if vk_hex else name)
                if key_id in self.key_chips:
                    self.tested_keys.add(key_id)
                    self.key_chips[key_id].setStyleSheet(
                        f"background-color: {T.COLOR_GREEN_BG}; color: {T.COLOR_GREEN_TEXT}; border-radius: 8px; "
                        f"font-size: 11px; font-weight: bold; border: 1px solid {T.COLOR_GREEN_DOT};")
                    self.lbl_coverage.setText(
                        f"{len(self.tested_keys)} / {len(self.key_chips)} 键已打卡")

    def refresh(self, s: dict):
        GREEN, ORANGE, RED = T.COLOR_GREEN_TEXT, T.ACCENT, T.COLOR_RED
        self.row_ble.set("已握手" if s.get("ble") else "未连接", GREEN if s.get("ble") else RED)
        self.row_hid.set("拦截中" if s.get("hid") else "未运行", GREEN if s.get("hid") else ORANGE)
        if s.get("session"):
            self.row_session.set(f"录音中 · 包#{s.get('packets', 0)}", GREEN)
        else:
            self.row_session.set("空闲", ORANGE)
        db = s.get("x6_level_db", -60)
        self.vu_meter.set_level(db)
        self.lbl_db.setText(f"{db:.1f} dB")
        # 峰值保持: 会话期间只涨不跌, 空闲 3s 后缓慢回落 (示波器的经典读数方式)
        now = time.time()
        if db > self._peak_db:
            self._peak_db, self._peak_ts = db, now
        elif now - self._peak_ts > 3.0:
            self._peak_db = max(-60.0, self._peak_db - 0.6)
        self.lbl_peak.setText(f"峰值 {self._peak_db:.1f} dB")

        self.row_packets.set(f"{s.get('packets', 0)} 包", T.PRIMARY if s.get("session") else T.TEXT_MUTED)
        delivery = s.get("delivery", "—")
        self.row_delivery.set("剪贴板直投" if delivery == "clipboard" else "vokie 原生",
                              T.COLOR_GREEN_TEXT)
        iso = s.get("isolation") or {}
        if not s.get("intercept_enabled", True):
            self.row_isolation.set("拦截已暂停", T.COLOR_RED)
        elif iso.get("active"):
            self.row_isolation.set(f"已生效 · 豁免 {iso.get('native_exempt', 0)}", T.COLOR_GREEN_TEXT)
        elif iso.get("running"):
            self.row_isolation.set("待绑定设备", T.ACCENT)
        else:
            self.row_isolation.set("未运行", T.COLOR_RED)
        self.card_isolation.refresh(s)
