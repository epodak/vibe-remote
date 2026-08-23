"""按键映射页 (view_mapping.py) — 真机热点图 + 真实映射配置。

视觉 (ui-skills 规则): 预设方案为分段控件 / 卡片投影 / VK 码等宽 /
同心圆角 (卡 14 - 内边距 6 = 控件 8) / 无 emoji 图标。
"""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget
)

from core.key_mapper import ACTIONS, KEYS, PRESETS
from ui.panel_isolation import IsolationBanner
from ui.remote_mapping_canvas import BUTTONS_FRONT, RemoteMappingCanvas
from ui.style_theme import T, MONO, setup_combo_box
from ui.widgets import attach_shadow


class KeyRow(QWidget):
    """单键映射行: 图标 | 键名 + VK码 | 动作下拉"""

    def __init__(self, key_id: str, mapper, parent=None):
        super().__init__(parent)
        self.key_id = key_id
        self.mapper = mapper
        info = KEYS[key_id]

        h = QHBoxLayout(self)
        h.setContentsMargins(12, 6, 10, 6)
        h.setSpacing(10)

        self.lbl_icon = QLabel(info["icon"])
        self.lbl_icon.setFixedSize(34, 26)
        self.lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_icon.setStyleSheet(
            f"background: {T.BG_CHIP}; border: 1px solid {T.BORDER_SOFT}; border-radius: 8px; "
            f"font-size: 11px; font-weight: bold; color: {T.TEXT_SECONDARY};")
        h.addWidget(self.lbl_icon)

        name_v = QVBoxLayout()
        name_v.setSpacing(0)
        lbl_name = QLabel(info["name"])
        lbl_name.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {T.TEXT_PRIMARY}; background: transparent;")
        lbl_vk = QLabel(f"VK 0x{info['vk']:02X}")
        lbl_vk.setStyleSheet(
            f"font-size: 10px; color: {T.TEXT_MUTED}; background: transparent; font-family: {MONO};")
        name_v.addWidget(lbl_name)
        name_v.addWidget(lbl_vk)
        h.addLayout(name_v)
        h.addStretch(1)

        self.cmb_action = QComboBox()
        setup_combo_box(self.cmb_action)
        for aid, a in ACTIONS.items():
            self.cmb_action.addItem(a["name"], aid)
        cur = self._current_action()
        self.cmb_action.setCurrentIndex(self.cmb_action.findData(cur))
        self.cmb_action.setFixedWidth(188)
        self.cmb_action.currentIndexChanged.connect(self._on_changed)
        h.addWidget(self.cmb_action)

        self.setFixedHeight(46)

    def _current_action(self) -> str:
        if self.mapper:
            return self.mapper.snapshot_maps()["maps"].get(self.key_id, "passthrough")
        return "passthrough"

    def _on_changed(self, idx: int):
        if not self.mapper:
            return
        self.mapper.set_key_action(self.key_id, self.cmb_action.itemData(idx))

    def sync_from_mapper(self):
        """预设切换后回填下拉框"""
        cur = self._current_action()
        self.cmb_action.setCurrentIndex(self.cmb_action.findData(cur))

    def set_pressed(self, pressed: bool):
        if pressed:
            self.lbl_icon.setStyleSheet(
                f"background: {T.COLOR_RED}; border: 1px solid {T.COLOR_RED}; "
                "border-radius: 8px; font-size: 11px; font-weight: bold; color: #FFF;")
        else:
            self.lbl_icon.setStyleSheet(
                f"background: {T.BG_CHIP}; border: 1px solid {T.BORDER_SOFT}; border-radius: 8px; "
                f"font-size: 11px; font-weight: bold; color: {T.TEXT_SECONDARY};")


class MappingView(QWidget):
    """按键映射视图: 真机热点图 (左) + 映射配置面板 (右)"""

    def __init__(self, coordinator=None, parent=None):
        super().__init__(parent)
        self.coord = coordinator
        self.mapper = coordinator.key_mapper if coordinator else None
        self._rows = {}
        self._pressed_now = set()
        self._init_ui()

    # ---------------- UI ----------------

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 20)
        root.setSpacing(14)

        head = QHBoxLayout()
        title_v = QVBoxLayout()
        title_v.setSpacing(2)
        lbl_title = QLabel("按键映射")
        lbl_title.setObjectName("page_title")
        lbl_sub = QLabel("把 X6 实体键映射成鼠标动作 (菜单键 → 右键锁定平移, OK → 左键拖拽…), 改完即时生效并持久化")
        lbl_sub.setObjectName("page_subtitle")
        lbl_sub.setWordWrap(True)
        title_v.addWidget(lbl_title)
        title_v.addWidget(lbl_sub)
        head.addLayout(title_v, stretch=1)
        root.addLayout(head)

        # 设备源隔离状态条 —— 映射正是"误伤原生键盘"的风险来源, 告警就近放置
        self.banner = IsolationBanner(self.coord, self)
        root.addWidget(self.banner)

        stage = QHBoxLayout()
        stage.setSpacing(16)

        # 左: 真机热点画布
        canvas_card = QFrame()
        canvas_card.setObjectName("card")
        attach_shadow(canvas_card, blur=26, dy=5, alpha=52)
        cv = QVBoxLayout(canvas_card)
        cv.setContentsMargins(12, 12, 12, 12)
        self.canvas = RemoteMappingCanvas(canvas_card)
        self.canvas.action_provider = self._action_label
        self.canvas.button_selected.connect(self._on_hotspot_selected)
        cv.addWidget(self.canvas)

        canvas_foot = QHBoxLayout()
        self.btn_flip = QPushButton("翻转 (背面全键盘)")
        self.btn_flip.setObjectName("secondary_btn")
        self.btn_flip.clicked.connect(self._toggle_flip)
        canvas_foot.addWidget(self.btn_flip)
        canvas_foot.addStretch(1)
        hint = QLabel("热点悬停查看说明 · 点击选中联动下表 · 实体按下实时红脉冲")
        hint.setStyleSheet(f"font-size: 11px; color: {T.TEXT_MUTED};")
        canvas_foot.addWidget(hint)
        cv.addLayout(canvas_foot)

        stage.addWidget(canvas_card, stretch=5)

        # 右: 配置面板
        panel = QVBoxLayout()
        panel.setSpacing(14)

        # 预设方案卡 (分段控件)
        preset_card = QFrame()
        preset_card.setObjectName("card")
        attach_shadow(preset_card)
        pv = QVBoxLayout(preset_card)
        pv.setContentsMargins(18, 14, 18, 14)
        pv.setSpacing(8)

        pv.addWidget(QLabel("预设方案", objectName="card_title"))
        self.lbl_profile_desc = QLabel("")
        self.lbl_profile_desc.setWordWrap(True)
        self.lbl_profile_desc.setStyleSheet(f"font-size: 11px; color: {T.TEXT_MUTED};")
        pv.addWidget(self.lbl_profile_desc)

        seg_row = QHBoxLayout()
        seg_row.setSpacing(6)
        self.preset_buttons = {}
        for pid, p in PRESETS.items():
            btn = QPushButton(p["name"])
            btn.setObjectName("segment_btn")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, pid=pid: self._apply_preset(pid))
            self.preset_buttons[pid] = btn   # 旧版漏了这一行, 分段控件选中态全程不亮
            seg_row.addWidget(btn)
        seg_row.addStretch(1)
        pv.addLayout(seg_row)

        self.lbl_right_state = QLabel()
        self.lbl_right_state.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {T.COLOR_GREEN_TEXT};")
        pv.addWidget(self.lbl_right_state)

        panel.addWidget(preset_card)

        # 键位映射表卡
        table_card = QFrame()
        table_card.setObjectName("card")
        attach_shadow(table_card)
        tv = QVBoxLayout(table_card)
        tv.setContentsMargins(8, 12, 8, 8)
        tv.setSpacing(0)

        table_head = QHBoxLayout()
        table_head.setContentsMargins(12, 2, 12, 6)
        t1 = QLabel("键位映射表")
        t1.setObjectName("card_title")
        table_head.addWidget(t1)
        table_head.addStretch(1)
        t2 = QLabel("语音键由转写状态机专用, 不参与映射")
        t2.setStyleSheet(f"font-size: 11px; color: {T.TEXT_MUTED};")
        table_head.addWidget(t2)
        tv.addLayout(table_head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumWidth(430)
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(2)

        for key_id in KEYS:
            row = KeyRow(key_id, self.mapper, inner)
            self._rows[key_id] = row
            il.addWidget(row)
        il.addStretch(1)
        scroll.setWidget(inner)
        tv.addWidget(scroll, stretch=1)

        panel.addWidget(table_card, stretch=1)
        stage.addLayout(panel, stretch=6)

        root.addLayout(stage, stretch=1)
        self._sync_profile_ui()

    # ---------------- 交互 ----------------

    def _action_label(self, key_id: str) -> str:
        if not self.mapper:
            return ""
        info = BUTTONS_FRONT.get(key_id)
        if info and "vk" not in info:
            return info.get("desc", "")  # 电源/飞鼠/语音: 设备专用说明
        km = self.mapper.snapshot_maps()["maps"]
        aid = km.get(key_id)
        return ACTIONS[aid]["name"] + " (已映射)" if aid else "系统默认透传"

    def _apply_preset(self, pid: str):
        if not self.mapper:
            return
        self.mapper.apply_preset(pid)
        for row in self._rows.values():
            row.sync_from_mapper()
        self._sync_profile_ui()

    def _toggle_flip(self):
        self.canvas.toggle_side()
        self.btn_flip.setText("翻转 (背面全键盘)" if not self.canvas.show_backside
                              else "翻转回正面")

    def _on_hotspot_selected(self, key_id: str):
        # 联动: 对应行闪一下, 与画布选中热点形成视觉呼应
        row = self._rows.get(key_id)
        if not row:
            return
        row.set_pressed(True)

        def _restore(r=row):
            if key_id not in self._pressed_now:
                r.set_pressed(False)
        QTimer.singleShot(350, _restore)

    def _sync_profile_ui(self):
        if not self.mapper:
            self.lbl_profile_desc.setText("预览模式 (无协调器)")
            return
        s = self.mapper.snapshot_maps()
        active = s["profile"]
        p = PRESETS.get(active)
        desc = p["desc"] if p else "你在预设基础上手动调整过的映射组合"
        self.lbl_profile_desc.setText(f"当前: {s['profile_name']} — {desc}")
        for pid, btn in self.preset_buttons.items():
            btn.setChecked(pid == active)
        if active not in PRESETS:
            self.lbl_profile_desc.setText(
                f"当前: {s['profile_name']} — 你在预设基础上手动调整过的映射组合 "
                f"({len(s['maps'])} 个键已改写)")

    # ---------------- 实体按键事件 (主窗口轮询分发) ----------------

    def sync_key_events(self, events: list):
        """events: [(key_id, is_down, ts), ...] — 更新画布红脉冲与行高亮"""
        for key_id, is_down, _ts in events:
            if key_id not in self._rows:
                continue
            if is_down:
                self._pressed_now.add(key_id)
            else:
                self._pressed_now.discard(key_id)
            self.canvas.set_key_active(key_id, is_down)
            row = self._rows.get(key_id)
            if row:
                row.set_pressed(is_down or key_id in self._pressed_now)

    def refresh(self, snapshot: dict):
        self.banner.refresh(snapshot)
        km = snapshot.get("keymap") or {}
        locked = km.get("right_locked")
        if locked:
            self.lbl_right_state.setText("右键锁定平移中 — 挥动手腕即可平移, 再按锁定键解锁")
            self.lbl_right_state.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {T.COLOR_RED};")
        else:
            self.lbl_right_state.setText("右键: 未锁定")
            self.lbl_right_state.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {T.COLOR_GREEN_TEXT};")
        if km.get("profile") and self.mapper:
            self._sync_profile_ui()
