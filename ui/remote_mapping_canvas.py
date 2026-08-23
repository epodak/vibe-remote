"""X6 真机拟态热点画布 (RemoteMappingCanvas).

设计原则 (2026-08-23 重构): 一张真机渲染图 + 可交互热点, 不画连线 ——
旧版两侧卡片墙 + 贝塞尔引线无交互价值且视觉混乱, 已整体废除。
- hover 热点: 蓝色光环 + 就近弹出键名/当前动作气泡
- 实体按键按下: 红色脉冲 (由 UI 轮询钩子事件驱动)
- 点击热点: 选中 (蓝环常亮), 联动右侧映射表定位
- 翻转: 查看背面 QWERTY 全键盘
"""

import math
import os

from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient, QBrush
from PyQt6.QtWidgets import QWidget

from ui.style_theme import T
from ui.widgets import shadow_color

# 正面热点 (rel 为相对机身矩形的比例坐标, 与真机渲染图对位)
BUTTONS_FRONT = {
    "power":     {"rel": (0.34, 0.10), "name": "电源键", "icon": "PWR",
                  "desc": "遥控器息屏 / 唤醒 (设备自身处理)"},
    "mute":      {"rel": (0.66, 0.10), "name": "静音键", "icon": "MUT",
                  "vk": 0xAD, "desc": "系统静音切换"},
    "air_mouse": {"rel": (0.34, 0.18), "name": "飞鼠启停", "icon": "↖",
                  "desc": "空中飞鼠光标开/关 (设备自身处理)"},
    "del":       {"rel": (0.66, 0.18), "name": "Del 删除键", "icon": "Del",
                  "vk": 0x2E, "desc": "退格删除 / 可映射"},
    "up":        {"rel": (0.50, 0.31), "name": "方向: 上", "icon": "▲",
                  "vk": 0x26, "desc": "光标上移 / 滚轮上"},
    "left":      {"rel": (0.32, 0.38), "name": "方向: 左", "icon": "◀",
                  "vk": 0x25, "desc": "光标左移"},
    "ok":        {"rel": (0.50, 0.38), "name": "OK / 确认键", "icon": "OK",
                  "vk": 0x0D, "desc": "回车 / 可映射为左键拖拽"},
    "right":     {"rel": (0.68, 0.38), "name": "方向: 右", "icon": "▶",
                  "vk": 0x27, "desc": "光标右移"},
    "down":      {"rel": (0.50, 0.45), "name": "方向: 下", "icon": "▼",
                  "vk": 0x28, "desc": "光标下移 / 滚轮下"},
    "voice":     {"rel": (0.50, 0.55), "name": "语音麦克风", "icon": "MIC",
                  "desc": "专用: 按一下录音/再按上屏 (不可映射)"},
    "pg_up":     {"rel": (0.32, 0.51), "name": "翻页 +", "icon": "Pg+",
                  "vk": 0x21, "desc": "向上翻页 / 可映射为滚轮缩放"},
    "pg_down":   {"rel": (0.32, 0.60), "name": "翻页 −", "icon": "Pg-",
                  "vk": 0x22, "desc": "向下翻页 / 可映射为滚轮缩放"},
    "vol_up":    {"rel": (0.68, 0.51), "name": "音量 ＋", "icon": "V+",
                  "vk": 0xAF, "desc": "系统音量增加"},
    "vol_down":  {"rel": (0.68, 0.60), "name": "音量 −", "icon": "V-",
                  "vk": 0xAE, "desc": "系统音量减少"},
}


class RemoteMappingCanvas(QWidget):
    """真机图 + 热点交互画布 (无连线)"""

    button_hovered = pyqtSignal(str)      # key_id or ""
    button_selected = pyqtSignal(str)     # key_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.active_keys = set()          # 实体按下中的键 (红脉冲)
        self.hovered_key = None
        self.selected_key = None
        self.show_backside = False
        self.pulse_phase = 0.0
        self.action_provider = None       # fn(key_id) -> 动作名 (供气泡显示)

        assets_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "assets"))
        front_p = os.path.join(assets_dir, "x6_front.png")
        back_p = os.path.join(assets_dir, "x6_back.png")
        self.pix_front = QPixmap(front_p) if os.path.exists(front_p) else None
        self.pix_back = QPixmap(back_p) if os.path.exists(back_p) else None

        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self._on_anim_tick)
        self.anim_timer.start(30)

    # ---------- 对外接口 ----------

    def toggle_side(self):
        self.show_backside = not self.show_backside
        self.update()

    def set_key_active(self, key_id: str, is_active: bool):
        if is_active:
            self.active_keys.add(key_id)
        else:
            self.active_keys.discard(key_id)
        self.update()

    def set_selected(self, key_id: str | None):
        self.selected_key = key_id
        self.update()

    def key_pos(self, key_id: str) -> QPointF | None:
        info = BUTTONS_FRONT.get(key_id)
        if not info:
            return None
        r = self._body_rect()
        return QPointF(r.x() + r.width() * info["rel"][0],
                       r.y() + r.height() * info["rel"][1])

    # ---------- 内部 ----------

    def _on_anim_tick(self):
        self.pulse_phase = (self.pulse_phase + 0.08) % (2 * math.pi)
        if self.active_keys:
            self.update()

    def _body_rect(self) -> QRectF:
        rem_h = min(self.height() - 24, 620.0)
        rem_w = rem_h * (158.0 / 490.0)
        return QRectF(self.width() / 2 - rem_w / 2, self.height() / 2 - rem_h / 2, rem_w, rem_h)

    def _hit_test(self, pos: QPointF) -> str | None:
        r = self._body_rect()
        for btn_id, info in BUTTONS_FRONT.items():
            bx = r.x() + r.width() * info["rel"][0]
            by = r.y() + r.height() * info["rel"][1]
            if math.hypot(pos.x() - bx, pos.y() - by) <= 18:
                return btn_id
        return None

    # ---------- 绘制 ----------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        rect = self._body_rect()
        target_pix = self.pix_back if self.show_backside else self.pix_front

        # 机身投影 (阴影表海拔) + 1px 轮廓线 (图像需要描边)
        shadow = QPainterPath()
        shadow.addRoundedRect(rect.adjusted(3, 8, -3, 10), 30, 30)
        p.fillPath(shadow, shadow_color(30))
        outline = QPainterPath()
        outline.addRoundedRect(rect, 30, 30)
        p.setPen(QPen(shadow_color(38), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(outline)

        if target_pix and not target_pix.isNull():
            scaled = target_pix.scaled(
                int(rect.width()), int(rect.height()),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            px = rect.center().x() - scaled.width() / 2
            py = rect.center().y() - scaled.height() / 2
            p.drawPixmap(int(px), int(py), scaled)
        else:
            body = QPainterPath()
            body.addRoundedRect(rect, 28, 28)
            p.fillPath(body, QColor(T.BG_TERMINAL))

        if not self.show_backside:
            self._draw_hotspots(p, rect)

    def _draw_hotspots(self, p: QPainter, rect: QRectF):
        rx, ry, rw, rh = rect.x(), rect.y(), rect.width(), rect.height()
        font = QFont(self.font())
        font.setPointSizeF(8.5)
        font.setBold(True)

        for btn_id, info in BUTTONS_FRONT.items():
            bx = rx + rw * info["rel"][0]
            by = ry + rh * info["rel"][1]
            is_active = btn_id in self.active_keys
            is_hover = btn_id == self.hovered_key
            is_selected = btn_id == self.selected_key

            # 1. 底层常显小点 (可发现性)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 200) if not is_active else QColor(T.COLOR_RED))
            p.drawEllipse(QPointF(bx, by), 2.6, 2.6)

            # 2. 交互光环
            if is_active or is_hover or is_selected:
                base = QColor(T.COLOR_RED) if is_active else QColor(T.PRIMARY)
                alpha = 150 if is_active else 80
                radius = 20 + 3 * math.sin(self.pulse_phase) if is_active else 16
                grad = QRadialGradient(QPointF(bx, by), radius)
                grad.setColorAt(0.0, QColor(base.red(), base.green(), base.blue(), alpha))
                grad.setColorAt(1.0, QColor(base.red(), base.green(), base.blue(), 0))
                p.setBrush(QBrush(grad))
                p.drawEllipse(QPointF(bx, by), radius, radius)
                # 描边环
                ring_pen = QPen(base, is_selected and not is_hover and 2.2 or 1.6)
                p.setPen(ring_pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(bx, by), 11, 11)

            # 3. hover / 按下: 就近气泡 (键名 + 动作)
            if is_hover or is_active:
                action = ""
                if self.action_provider:
                    action = self.action_provider(btn_id) or ""
                lines = [info["name"]] + ([action] if action else [])
                self._draw_bubble(p, QPointF(bx, by), lines, is_active)

    def _draw_bubble(self, p: QPainter, anchor: QPointF, lines: list[str], warn: bool):
        font = QFont(self.font())
        font.setPointSizeF(9)
        font.setBold(False)
        p.setFont(font)
        fm = p.fontMetrics()
        text_w = max(fm.horizontalAdvance(t) for t in lines) if lines else 40
        bh = 8 + len(lines) * (fm.height() + 2)
        bw = text_w + 20
        # 气泡默认放热点右侧, 放不下放左侧
        bx = anchor.x() + 18
        if bx + bw > self.width() - 4:
            bx = anchor.x() - 18 - bw
        by = anchor.y() - bh / 2

        path = QPainterPath()
        path.addRoundedRect(QRectF(bx, by, bw, bh), 8, 8)
        p.setPen(QPen(QColor(T.COLOR_RED) if warn else QColor(T.PRIMARY), 1.2))
        bubble = QColor(T.BG_CARD); bubble.setAlpha(244)
        p.setBrush(bubble)
        p.drawPath(path)

        p.setPen(QColor(f"{T.TEXT_PRIMARY}"))
        bold = QFont(font)
        bold.setBold(True)
        p.setFont(bold)
        p.drawText(QRectF(bx + 10, by + 4, bw - 20, fm.height() + 2),
                   Qt.AlignmentFlag.AlignVCenter, lines[0])
        if len(lines) > 1:
            p.setFont(font)
            p.setPen(QColor(f"{T.TEXT_MUTED}"))
            p.drawText(QRectF(bx + 10, by + 6 + fm.height(), bw - 20, fm.height() + 2),
                       Qt.AlignmentFlag.AlignVCenter, lines[1])

    # ---------- 鼠标 ----------

    def mouseMoveEvent(self, event):
        if self.show_backside:
            if self.hovered_key:
                self.hovered_key = None
                self.button_hovered.emit("")
                self.update()
            return
        hit = self._hit_test(event.position())
        if hit != self.hovered_key:
            self.hovered_key = hit
            self.button_hovered.emit(hit or "")
            self.update()

    def leaveEvent(self, event):
        if self.hovered_key:
            self.hovered_key = None
            self.button_hovered.emit("")
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.hovered_key:
            self.selected_key = self.hovered_key
            self.button_selected.emit(self.hovered_key)
            self.update()
