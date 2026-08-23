"""输入源隔离面板 (panel_isolation.py) —— 让 Raw Input 设备仲裁可见、可控。

对应 core/device_source.py。之所以要专门给它一块 UI:

  隔离是一条"沉默生效"的机制 —— 工作正常时用户什么也感觉不到, 一旦绑定失败
  就会退回旧行为 (原生键盘可能被吞)。不可见的降级最危险, 因此这里把三件事
  摊在明面上: **绑定了谁 / 当前这一下按键来自谁 / 替你豁免和补救了多少次**。

两种形态:
  · IsolationBanner —— 一行状态条, 放在按键映射页顶部 (映射是风险来源, 就近告警)
  · IsolationCard   —— 完整面板, 放在全能检测工作台 (设备清单 + 计数器 + 操作)
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
)

from ui import icons
from ui.style_theme import MONO, T
from ui.widgets import attach_shadow


def _arbiter(coord):
    return getattr(coord, "device_arbiter", None)


class IsolationBanner(QFrame):
    """按键映射页顶部状态条: 三态 (生效 / 未绑定告警 / 拦截暂停)。"""

    def __init__(self, coordinator=None, parent=None):
        super().__init__(parent)
        self.coord = coordinator
        self.setObjectName("banner_ok")
        self._state = None

        h = QHBoxLayout(self)
        h.setContentsMargins(14, 9, 12, 9)
        h.setSpacing(10)

        self.icon = QLabel()
        self.icon.setStyleSheet("background: transparent;")
        h.addWidget(self.icon)

        self.text = QLabel("输入源隔离检测中…")
        self.text.setWordWrap(True)
        self.text.setStyleSheet(f"font-size: 12px; color: {T.TEXT_PRIMARY}; background: transparent;")
        h.addWidget(self.text, stretch=1)

        self.btn = QPushButton("立即学习设备")
        self.btn.setObjectName("secondary_btn")
        self.btn.setFixedHeight(28)
        self.btn.clicked.connect(self._learn)
        self.btn.hide()
        h.addWidget(self.btn)

    def _learn(self):
        arb = _arbiter(self.coord)
        if arb:
            arb.start_learning()

    def refresh(self, snapshot: dict):
        iso = snapshot.get("isolation") or {}
        intercept = snapshot.get("intercept_enabled", True)

        if not intercept:
            state, obj, icon, color = "paused", "banner_warn", "pause", T.COLOR_RED
            msg = "全局拦截已暂停 —— 所有按键原样透传给系统, 映射暂不生效。按 Ctrl+Alt+F12 恢复。"
            show_btn = False
        elif iso.get("learning"):
            state, obj, icon, color = "learning", "banner_warn", "alert", T.COLOR_WARN_TEXT
            msg = "学习模式已开启 —— 现在按一下遥控器上的任意键, 即可把它绑定为受控设备。"
            show_btn = False
        elif not iso.get("running"):
            state, obj, icon, color = "off", "banner_warn", "alert", T.COLOR_WARN_TEXT
            msg = ("设备源仲裁未运行 —— 全局钩子无法区分遥控器与你的物理键盘, "
                   "映射键 (Enter / Backspace / Esc…) 可能被一并拦截。")
            show_btn = False
        elif not iso.get("bound"):
            state, obj, icon, color = "unbound", "banner_warn", "alert", T.COLOR_WARN_TEXT
            msg = ("尚未识别 X6 接收器 —— 为避免映射彻底失灵, 当前**退回旧行为**"
                   "(对所有键盘生效)。按一下遥控器任意键即可自动绑定。")
            show_btn = True
        else:
            state, obj, icon, color = "ok", "banner_ok", "shield", T.COLOR_GREEN_TEXT
            msg = (f"输入源隔离已生效 · 受控设备 {iso.get('bound_name') or '—'} "
                   f"({iso.get('bound_id') or '—'}) —— 你的物理键盘已豁免 "
                   f"{iso.get('native_exempt', 0)} 次按键"
                   + (f", 误吞补偿 {iso['replayed']} 次" if iso.get("replayed") else ""))
            show_btn = False

        if state != self._state:
            self._state = state
            self.setObjectName(obj)
            self.style().unpolish(self)
            self.style().polish(self)
            self.icon.setPixmap(icons.icon_pixmap(icon, color, 18))
            self.btn.setVisible(show_btn)
            self.text.setStyleSheet(
                f"font-size: 12px; color: {color if state != 'ok' else T.TEXT_PRIMARY}; "
                "background: transparent;")
        self.text.setText(msg)


class _Counter(QWidget):
    """一个大号计数器 (数值等宽 + 说明小字)"""

    def __init__(self, label: str, color: str, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(1)
        self.value = QLabel("0")
        self.value.setStyleSheet(
            f"font-size: 19px; font-weight: bold; color: {color}; font-family: {MONO}; "
            "background: transparent;")
        cap = QLabel(label)
        cap.setStyleSheet(f"font-size: 11px; color: {T.TEXT_MUTED}; background: transparent;")
        v.addWidget(self.value)
        v.addWidget(cap)

    def set(self, n):
        self.value.setText(f"{n:,}")


class IsolationCard(QFrame):
    """全能检测工作台的完整面板: 绑定 / 实时来源 / 计数器 / 设备清单 / 操作。"""

    MAX_DEVICE_ROWS = 5

    def __init__(self, coordinator=None, parent=None):
        super().__init__(parent)
        self.coord = coordinator
        self.setObjectName("card")
        attach_shadow(self)
        self._dev_rows = []
        self._last_sig = None

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(9)

        head = QHBoxLayout()
        head.setSpacing(8)
        ic = QLabel()
        ic.setPixmap(icons.icon_pixmap("shield", T.PRIMARY, 18))
        ic.setStyleSheet("background: transparent;")
        head.addWidget(ic)
        head.addWidget(QLabel("输入源隔离 (Raw Input 设备仲裁)", objectName="card_title"))
        head.addStretch(1)
        self.badge = QLabel("检测中")
        self.badge.setObjectName("badge_warn")
        head.addWidget(self.badge)
        v.addLayout(head)

        self.lbl_bound = QLabel("—")
        self.lbl_bound.setWordWrap(True)
        self.lbl_bound.setStyleSheet(f"font-size: 11px; color: {T.TEXT_MUTED};")
        v.addWidget(self.lbl_bound)

        # 计数器行 —— 隔离的"疗效"就靠这三个数字自证
        counters = QHBoxLayout()
        counters.setSpacing(22)
        self.cnt_remote = _Counter("遥控器按键", T.PRIMARY)
        self.cnt_native = _Counter("原生键盘豁免", T.COLOR_GREEN_TEXT)
        self.cnt_replay = _Counter("误吞补偿重放", T.ACCENT)
        for c in (self.cnt_remote, self.cnt_native, self.cnt_replay):
            counters.addWidget(c)
        counters.addStretch(1)
        v.addLayout(counters)

        self.lbl_live = QLabel("当前输入源: —")
        self.lbl_live.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {T.TEXT_MUTED};")
        v.addWidget(self.lbl_live)

        # 设备清单
        self.dev_grid = QGridLayout()
        self.dev_grid.setSpacing(3)
        self.dev_grid.setColumnStretch(1, 1)
        v.addLayout(self.dev_grid)
        v.addStretch(1)

        ops = QHBoxLayout()
        ops.setSpacing(8)
        self.btn_learn = QPushButton("重新学习设备")
        self.btn_learn.setObjectName("secondary_btn")
        self.btn_learn.clicked.connect(self._learn)
        ops.addWidget(self.btn_learn)
        self.btn_unbind = QPushButton("解除绑定")
        self.btn_unbind.setObjectName("secondary_btn")
        self.btn_unbind.clicked.connect(self._unbind)
        ops.addWidget(self.btn_unbind)
        ops.addStretch(1)
        v.addLayout(ops)

    # ---------------- 操作 ----------------

    def _learn(self):
        arb = _arbiter(self.coord)
        if arb:
            arb.start_learning()

    def _unbind(self):
        arb = _arbiter(self.coord)
        if arb:
            arb.unbind()

    # ---------------- 刷新 ----------------

    def refresh(self, snapshot: dict):
        iso = snapshot.get("isolation") or {}
        if not iso:
            self.badge.setText("不可用")
            self.lbl_bound.setText("此构建未启用设备源仲裁。")
            return

        if not iso.get("running"):
            badge_text, badge_obj = "未运行", "badge_warn"
        elif iso.get("learning"):
            badge_text, badge_obj = "学习中", "badge_warn"
        elif iso.get("active"):
            badge_text, badge_obj = "已生效", "badge_online"
        else:
            badge_text, badge_obj = "待绑定", "badge_warn"
        if self.badge.objectName() != badge_obj:
            self.badge.setObjectName(badge_obj)
            self.badge.style().unpolish(self.badge)
            self.badge.style().polish(self.badge)
        self.badge.setText(badge_text)

        if iso.get("bound"):
            self.lbl_bound.setText(
                f"受控设备: {iso.get('bound_name')} · {iso.get('bound_id')} —— "
                "只有来自该设备的按键会被映射与拦截, 其余键盘逐事件透传。")
        else:
            self.lbl_bound.setText(
                "尚未绑定遥控器 —— 按一下遥控器任意键 (或点下方「重新学习设备」) 即可完成绑定。"
                "未绑定期间隔离不生效, 映射对所有键盘一视同仁。")

        self.cnt_remote.set(iso.get("remote_events", 0))
        self.cnt_native.set(iso.get("native_exempt", 0))
        self.cnt_replay.set(iso.get("replayed", 0))

        src = iso.get("last_source")
        if src == "remote":
            self.lbl_live.setText("当前输入源: ● 遥控器 (映射生效中)")
            self.lbl_live.setStyleSheet(
                f"font-size: 11px; font-weight: bold; color: {T.PRIMARY};")
        elif src == "native":
            self.lbl_live.setText("当前输入源: ● 物理键盘 (已豁免, 按键原样透传)")
            self.lbl_live.setStyleSheet(
                f"font-size: 11px; font-weight: bold; color: {T.COLOR_GREEN_TEXT};")
        else:
            self.lbl_live.setText("当前输入源: — (还没有按键经过)")
            self.lbl_live.setStyleSheet(
                f"font-size: 11px; font-weight: bold; color: {T.TEXT_MUTED};")

        self._render_devices(iso.get("devices") or [])

    def _render_devices(self, devices: list):
        devices = devices[:self.MAX_DEVICE_ROWS]
        # 只有内容真的变了才重建行 (100ms 轮询下无脑重建会让整页闪烁)
        sig = tuple((d["friendly"], d["remote"], d["hits"], d["active"]) for d in devices)
        if sig == self._last_sig:
            return
        self._last_sig = sig

        while self.dev_grid.count():
            item = self.dev_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        for r, d in enumerate(devices):
            dot = QLabel("●")
            dot_color = (T.PRIMARY if d["remote"] else
                         (T.COLOR_GREEN_DOT if d["active"] else T.TEXT_LIGHT))
            dot.setFixedWidth(12)
            dot.setStyleSheet(f"color: {dot_color}; font-size: 9px; background: transparent;")

            name = QLabel(d["friendly"])
            name.setStyleSheet(
                f"font-size: 11px; background: transparent; "
                f"color: {T.TEXT_PRIMARY if d['remote'] else T.TEXT_MUTED};")

            ident = d.get("mac") or (f"{d['vid']}:{d['pid']}" if d.get("vid") else "—")
            lbl_id = QLabel(ident)
            lbl_id.setStyleSheet(
                f"font-size: 10px; color: {T.TEXT_LIGHT}; font-family: {MONO}; background: transparent;")

            role = QLabel("遥控器" if d["remote"] else "已豁免")
            role.setStyleSheet(
                f"font-size: 10px; font-weight: bold; background: transparent; "
                f"color: {T.PRIMARY if d['remote'] else T.COLOR_GREEN_TEXT};")

            hits = QLabel(f"{d['hits']:,}")
            hits.setAlignment(Qt.AlignmentFlag.AlignRight)
            hits.setStyleSheet(
                f"font-size: 10px; color: {T.TEXT_MUTED}; font-family: {MONO}; background: transparent;")

            for col, w in enumerate((dot, name, lbl_id, role, hits)):
                self.dev_grid.addWidget(w, r, col)
