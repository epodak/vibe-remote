"""QPainter 手绘线性图标 —— lucide 风格: 1.8px 圆头笔画、无填充、24 单位逻辑空间。

设计规则 (ui-skills.com/frontend-design + better-ui):
- 禁用 emoji 当图标 (通用 AI 审美), 图标笔画粗细与正文文字字重匹配;
- 全套图标同一笔画语言 (圆帽/圆角连接), 颜色由调用方注入。
"""

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

STROKE = 1.8
_LOGICAL = 24.0


def _pen(color):
    pen = QPen(QColor(color), STROKE)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _link(p):  # 硬件链路: 信号波
    for r in (4.5, 8.0, 11.5):
        p.drawArc(QRectF(12 - r, 17.5 - r, 2 * r, 2 * r), -60 * 16, 120 * 16)
    p.drawPoint(QPointF(12, 17.5))


def _gamepad(p):  # 按键映射: 手柄
    p.drawRoundedRect(QRectF(2.5, 7.0, 19.0, 10.5), 5.0, 5.0)
    p.drawLine(QPointF(9.0, 9.9), QPointF(9.0, 14.6))
    p.drawLine(QPointF(6.65, 12.25), QPointF(11.35, 12.25))
    p.drawPoint(QPointF(15.6, 11.0))
    p.drawPoint(QPointF(17.9, 13.3))


def _gauge(p):  # 全能检测: 仪表
    p.drawArc(QRectF(4.0, 5.0, 16.0, 16.0), 30 * 16, 120 * 16)
    p.drawLine(QPointF(12.0, 13.0), QPointF(16.6, 8.4))
    p.drawPoint(QPointF(12.0, 13.0))


def _chat(p):  # 语音回眸: 气泡
    p.drawRoundedRect(QRectF(3.5, 4.5, 17.0, 11.5), 4.0, 4.0)
    p.drawLine(QPointF(8.0, 16.0), QPointF(8.0, 19.5))
    p.drawLine(QPointF(8.0, 19.5), QPointF(11.8, 16.0))


def _gear(p):  # 偏好设置: 齿轮
    import math
    for i in range(8):
        a = math.radians(i * 45.0)
        p.drawLine(QPointF(12 + 7.4 * math.cos(a), 12 + 7.4 * math.sin(a)),
                   QPointF(12 + 9.7 * math.cos(a), 12 + 9.7 * math.sin(a)))
    p.drawEllipse(QPointF(12, 12), 4.6, 4.6)


def _mic(p):  # 麦克风
    p.drawRoundedRect(QRectF(9.0, 3.0, 6.0, 11.0), 3.0, 3.0)
    p.drawArc(QRectF(7.0, 9.0, 10.0, 10.0), 0, 180 * 16)
    p.drawLine(QPointF(12, 19.0), QPointF(12, 21.2))
    p.drawLine(QPointF(8.6, 21.2), QPointF(15.4, 21.2))


def _bluetooth(p):
    p.drawLine(QPointF(7.0, 7.3), QPointF(17.0, 16.6))
    p.drawLine(QPointF(17.0, 16.6), QPointF(12.0, 20.9))
    p.drawLine(QPointF(12.0, 20.9), QPointF(12.0, 3.1))
    p.drawLine(QPointF(12.0, 3.1), QPointF(17.0, 7.4))
    p.drawLine(QPointF(17.0, 7.4), QPointF(7.0, 16.7))


def _speaker(p):
    p.drawLine(QPointF(4.0, 9.5), QPointF(8.0, 9.5))
    p.drawLine(QPointF(8.0, 9.5), QPointF(13.0, 5.5))
    p.drawLine(QPointF(13.0, 5.5), QPointF(13.0, 18.5))
    p.drawLine(QPointF(13.0, 18.5), QPointF(8.0, 14.5))
    p.drawLine(QPointF(8.0, 14.5), QPointF(4.0, 14.5))
    p.drawLine(QPointF(4.0, 14.5), QPointF(4.0, 9.5))
    p.drawArc(QRectF(15.5, 8.5, 5.5, 7.0), -50 * 16, 100 * 16)


def _activity(p):  # 心跳/电平
    p.drawLine(QPointF(3.0, 12.0), QPointF(7.5, 12.0))
    p.drawLine(QPointF(7.5, 12.0), QPointF(10.2, 6.2))
    p.drawLine(QPointF(10.2, 6.2), QPointF(13.8, 17.8))
    p.drawLine(QPointF(13.8, 17.8), QPointF(16.4, 12.0))
    p.drawLine(QPointF(16.4, 12.0), QPointF(21.0, 12.0))


def _keyboard(p):
    p.drawRoundedRect(QRectF(3.0, 6.5, 18.0, 11.0), 2.5, 2.5)
    for x in (6.5, 9.5, 12.5, 15.5):
        p.drawPoint(QPointF(x, 10.0))
    p.drawLine(QPointF(8.5, 14.6), QPointF(15.5, 14.6))


def _chevron_right(p):
    p.drawLine(QPointF(9.5, 6.5), QPointF(15.0, 12.0))
    p.drawLine(QPointF(15.0, 12.0), QPointF(9.5, 17.5))


def _chevron_down(p):
    p.drawLine(QPointF(6.5, 9.5), QPointF(12.0, 15.0))
    p.drawLine(QPointF(12.0, 15.0), QPointF(17.5, 9.5))




def _shield(p):  # 设备源隔离: 盾牌
    p.drawLine(QPointF(12.0, 2.8), QPointF(4.2, 6.0))
    p.drawLine(QPointF(4.2, 6.0), QPointF(4.2, 12.0))
    p.drawArc(QRectF(4.2, 6.0, 15.6, 15.2), 180 * 16, 90 * 16)
    p.drawArc(QRectF(4.2, 6.0, 15.6, 15.2), 270 * 16, 90 * 16)
    p.drawLine(QPointF(12.0, 2.8), QPointF(19.8, 6.0))
    p.drawLine(QPointF(19.8, 6.0), QPointF(19.8, 12.0))
    p.drawLine(QPointF(9.2, 12.2), QPointF(11.3, 14.4))
    p.drawLine(QPointF(11.3, 14.4), QPointF(15.2, 10.0))


def _refresh(p):  # 重新学习 / 重连
    p.drawArc(QRectF(4.0, 4.0, 16.0, 16.0), 60 * 16, 240 * 16)
    p.drawLine(QPointF(20.0, 4.4), QPointF(20.0, 9.4))
    p.drawLine(QPointF(20.0, 9.4), QPointF(15.0, 9.4))


def _sun(p):  # 浅色主题
    import math
    p.drawEllipse(QPointF(12, 12), 4.4, 4.4)
    for i in range(8):
        a = math.radians(i * 45.0)
        p.drawLine(QPointF(12 + 7.0 * math.cos(a), 12 + 7.0 * math.sin(a)),
                   QPointF(12 + 9.6 * math.cos(a), 12 + 9.6 * math.sin(a)))


def _moon(p):  # 深色主题
    path = QPainterPath()
    path.moveTo(19.4, 14.6)
    path.arcTo(QRectF(2.6, 2.6, 18.8, 18.8), 30, 200)
    path.arcTo(QRectF(6.2, -1.4, 15.0, 16.0), 230, -140)
    p.drawPath(path)


def _trash(p):  # 删除
    p.drawLine(QPointF(4.4, 6.6), QPointF(19.6, 6.6))
    p.drawLine(QPointF(9.4, 6.6), QPointF(9.4, 3.6))
    p.drawLine(QPointF(9.4, 3.6), QPointF(14.6, 3.6))
    p.drawLine(QPointF(14.6, 3.6), QPointF(14.6, 6.6))
    p.drawLine(QPointF(6.4, 6.6), QPointF(7.4, 20.4))
    p.drawLine(QPointF(7.4, 20.4), QPointF(16.6, 20.4))
    p.drawLine(QPointF(16.6, 20.4), QPointF(17.6, 6.6))
    p.drawLine(QPointF(10.4, 10.0), QPointF(10.8, 17.0))
    p.drawLine(QPointF(13.6, 10.0), QPointF(13.2, 17.0))


def _download(p):  # 导出
    p.drawLine(QPointF(12.0, 3.4), QPointF(12.0, 14.6))
    p.drawLine(QPointF(7.6, 10.2), QPointF(12.0, 14.6))
    p.drawLine(QPointF(12.0, 14.6), QPointF(16.4, 10.2))
    p.drawLine(QPointF(4.4, 17.4), QPointF(4.4, 20.4))
    p.drawLine(QPointF(4.4, 20.4), QPointF(19.6, 20.4))
    p.drawLine(QPointF(19.6, 20.4), QPointF(19.6, 17.4))


def _alert(p):  # 告警
    p.drawEllipse(QPointF(12, 12), 8.8, 8.8)
    p.drawLine(QPointF(12.0, 7.2), QPointF(12.0, 13.0))
    p.drawPoint(QPointF(12.0, 16.4))


def _pause(p):  # 拦截暂停
    p.drawLine(QPointF(9.4, 5.6), QPointF(9.4, 18.4))
    p.drawLine(QPointF(14.6, 5.6), QPointF(14.6, 18.4))


def _remote(p):  # 遥控器本体
    p.drawRoundedRect(QRectF(7.5, 2.6, 9.0, 18.8), 4.4, 4.4)
    p.drawEllipse(QPointF(12, 8.0), 2.2, 2.2)
    p.drawLine(QPointF(9.8, 13.6), QPointF(14.2, 13.6))
    p.drawLine(QPointF(9.8, 17.0), QPointF(14.2, 17.0))


_ICONS = {
    "link": _link, "gamepad": _gamepad, "gauge": _gauge, "chat": _chat,
    "gear": _gear, "mic": _mic, "bluetooth": _bluetooth, "speaker": _speaker,
    "activity": _activity, "keyboard": _keyboard, "chevron_right": _chevron_right,
    "chevron_down": _chevron_down, "shield": _shield, "refresh": _refresh,
    "sun": _sun, "moon": _moon, "trash": _trash, "download": _download,
    "alert": _alert, "pause": _pause, "remote": _remote,
}


def icon_pixmap(name: str, color: str = "#475569", px: int = 24) -> QPixmap:
    """渲染单色线性图标位图。"""
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(px / _LOGICAL, px / _LOGICAL)
    p.setPen(_pen(color))
    p.setBrush(Qt.BrushStyle.NoBrush)
    _ICONS[name](p)
    p.end()
    return pm


def icon(name: str, color: str = "#475569", px: int = 24) -> QIcon:
    return QIcon(icon_pixmap(name, color, px))
