"""vRemote-Win 共享 UI 小部件: LED 电平表 / 状态行 / 卡片阴影 / 拨杆开关。

设计规则 (ui-skills.com/better-ui):
- 阴影表海拔: 卡片柔和投影 (0,3) blur 20, 边框只表结构;
- 高频微交互动画 ≤150ms: 拨杆开关 140ms 缓动。
"""

from PyQt6.QtCore import (
    QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation
)
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
)
from PyQt6.QtWidgets import QGraphicsDropShadowEffect

from ui.style_theme import T



def shadow_color(alpha: int = 42) -> QColor:
    """当前主题的投影色 (浅色=石板蓝烟, 深色=纯黑, 否则深底上的蓝烟会发灰)。"""
    r, g, b = (int(x) for x in T.SHADOW_RGB.split(","))
    return QColor(r, g, b, alpha)


def attach_shadow(widget: QWidget, blur: int = 20, dy: int = 3, alpha: int = 42):
    """卡片柔和投影 —— 阴影表海拔。"""
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    eff.setColor(shadow_color(alpha))
    widget.setGraphicsEffect(eff)
    return eff


class Meter(QWidget):
    """12 段 LED 电平表 (dBFS, -60dB 底, 与 macOS MeterView 同刻度)"""

    def __init__(self, color=None, count=12, parent=None):
        super().__init__(parent)
        # color=None: 每次绘制时读当前主题主色 (换肤后无需重建也能跟上)
        self._color = color
        self.count = count
        self.level = 0.0
        self.setFixedSize(count * 6 + 4, 18)

    def set_db(self, db: float):
        self.level = max(0.0, min(1.0, (db + 60.0) / 60.0))
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        active = int(self.level * self.count)
        for i in range(self.count):
            base = self._color or T.COLOR_GREEN_DOT
            c = QColor(base) if i < active else QColor(T.BORDER_SOFT)
            if i >= self.count - 2 and i < active:  # 顶端两段偏红
                c = QColor(T.COLOR_RED)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(2 + i * 6, 2, 4, 14, 2, 2)


class StatusRow(QWidget):
    """标题 · 圆点 · 值 的状态指示行。

    尺寸是这里的老缺陷 ("已握手"被裁成"已"): QLabel 的 minimumSizeHint 允许它被
    压到远小于文本宽度, 窄卡片里布局就拿值文本开刀。修法是两条同时生效 ——
      · 值: 每次 setText 后按真实字宽显式抬高 minimumWidth, 布局再挤也不能低于它;
      · 标题: 保留可压缩性, 但按剩余空间自行加省略号, 而不是被硬裁。
    """

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self._title_text = title
        self.title = QLabel(title)
        self.title.setStyleSheet(f"font-size: 12px; color: {T.TEXT_MUTED};")
        self.title.setMinimumWidth(0)
        self.dot = QLabel("●")
        self.dot.setFixedWidth(12)
        self.value = QLabel("—")
        self.value.setStyleSheet("font-size: 12px; font-weight: bold;")
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(self.title, stretch=1)
        h.addWidget(self.dot)
        h.addWidget(self.value)

    def _elide_title(self):
        avail = self.width() - self.value.minimumWidth() - self.dot.width() - 14
        fm = self.title.fontMetrics()
        self.title.setText(fm.elidedText(self._title_text, Qt.TextElideMode.ElideRight,
                                         max(avail, 16)))

    def resizeEvent(self, e):
        self._elide_title()
        super().resizeEvent(e)

    def set(self, text: str, color: str):
        self.value.setText(text)
        # 值绝不让步: 用加粗 12px 的真实字宽锁住下限 (+8 给样式表内边距留余量)
        font = self.value.font()
        font.setBold(True)
        self.value.setMinimumWidth(QFontMetrics(font).horizontalAdvance(text) + 8)
        self.dot.setStyleSheet(f"color: {color}; font-size: 10px;")
        self.value.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {color};")
        self._elide_title()


class ToggleSwitch(QWidget):
    """拨杆开关 (140ms OutCubic 动画) —— 替代 QCheckBox 的微交互"""

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setFixedSize(38, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checked = checked
        self._pos = 1.0 if checked else 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, on: bool):
        if on == self._checked:
            return
        self._checked = on
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)

    def _on_anim(self, v):
        self._pos = float(v)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QColor(T.PRIMARY) if self._checked else QColor(T.BORDER_SOFT)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, 38, 22), 11, 11)
        # 滑块: 15..23 (边缘各留 3.5)
        x = 3.5 + self._pos * (38 - 22)
        p.setBrush(QColor(T.BG_CARD))
        p.setPen(QPen(QColor(T.BORDER_SOFT), 1))
        p.drawEllipse(QPointF(x + 7.5, 11), 7.5, 7.5)
