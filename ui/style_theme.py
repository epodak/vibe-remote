"""vRemote-Win 设计系统 v3 —— "Instrument Panel" 双主题版。

v3 (2026-08-23) 变更: 颜色 token 从模块常量升级为**运行时可切换的调色板**。

  · 旧版 `from ui.style_theme import PRIMARY` 是值拷贝, 主题一换就失联;
    新版统一走 `from ui.style_theme import T` + `T.PRIMARY` —— T 是稳定的
    对象引用, 属性在**使用时**才解析, 换肤只需重建窗口即可全量生效。
  · 补齐了此前散落在各视图里的硬编码色 (chip 底色 / 终端底色 / 描边),
    它们正是深色模式下会"漏白"的地方。

设计决策来源 (frontend-design/better-ui/interface-design):
- 主色深青 TEAL (硬件仪表气质), 琥珀 AMBER 辅助, 红/绿只留给语义状态;
- 阴影表海拔、边框表结构; 同心圆角 (卡片 14px = 控件 8px + 6px 内边距);
- 数字用等宽字体; 间距全部 4px 网格。
"""

import os

# ---------------- 调色板 ----------------

_LIGHT = {
    # 底层表面
    "BG_APP": "#F3F5F8",            # 冷纸灰, 衬托白卡与阴影
    "BG_SIDEBAR": "#FFFFFF",
    "BG_CARD": "#FFFFFF",
    "BG_CARD_HOVER": "#FAFBFC",
    "BG_CARD_SELECTED": "#F0FDFA",
    "BG_CHIP": "#F1F5F9",           # 键位 chip / 图标底座
    "BG_SUBTLE": "#F8FAFC",         # 画布网格底 / 悬停底
    "BG_INPUT": "#FFFFFF",
    "BG_TERMINAL": "#0B1220",       # 事件流终端 (两个主题都用深底)
    "TEXT_TERMINAL": "#99F6E4",
    "TEXT_TERMINAL_HERO": "#5EEAD4",

    # 描边
    "BORDER_CARD": "rgba(15, 23, 42, 0.07)",
    "BORDER_CARD_HOVER": "rgba(13, 148, 136, 0.35)",
    "BORDER_SOFT": "#E2E8F0",
    "BORDER_INPUT": "rgba(15, 23, 42, 0.12)",
    "SHADOW_RGB": "15, 23, 42",

    # 主色: 深青 (仪器面板)
    "PRIMARY": "#0F766E",           # teal-700
    "PRIMARY_HOVER": "#115E59",     # teal-800
    "PRIMARY_PRESSED": "#134E4A",   # teal-900
    "PRIMARY_LIGHT": "#CCFBF1",     # teal-100
    "PRIMARY_FAINT": "#F0FDFA",     # teal-50

    # 辅助: 琥珀
    "ACCENT": "#B45309",
    "ACCENT_LIGHT": "#FEF3C7",

    # 语义
    "COLOR_RED": "#DC2626",
    "COLOR_RED_LIGHT": "#FEF2F2",
    "COLOR_GREEN_BG": "#ECFDF5",
    "COLOR_GREEN_TEXT": "#047857",
    "COLOR_GREEN_DOT": "#10B981",
    "COLOR_WARN_BG": "#FFFBEB",
    "COLOR_WARN_TEXT": "#B45309",

    # 文字
    "TEXT_PRIMARY": "#0F172A",
    "TEXT_SECONDARY": "#334155",
    "TEXT_MUTED": "#64748B",
    "TEXT_LIGHT": "#94A3B8",
    "TEXT_ON_PRIMARY": "#FFFFFF",
}

_DARK = {
    "BG_APP": "#0A101C",            # 深海军 —— 仪表面板熄灯态
    "BG_SIDEBAR": "#0E1626",
    "BG_CARD": "#16223A",
    "BG_CARD_HOVER": "#1D2C49",
    "BG_CARD_SELECTED": "#0F2E2B",
    "BG_CHIP": "#1B2740",
    "BG_SUBTLE": "#111A2B",
    "BG_INPUT": "#182541",
    "BG_TERMINAL": "#060B14",
    "TEXT_TERMINAL": "#5EEAD4",
    "TEXT_TERMINAL_HERO": "#7DF5E4",

    "BORDER_CARD": "rgba(148, 163, 184, 0.20)",
    "BORDER_CARD_HOVER": "rgba(45, 212, 191, 0.45)",
    "BORDER_SOFT": "#25344F",
    "BORDER_INPUT": "rgba(148, 163, 184, 0.22)",
    "SHADOW_RGB": "0, 0, 0",

    "PRIMARY": "#2DD4BF",           # teal-400: 深底上需要更亮的主色
    "PRIMARY_HOVER": "#5EEAD4",
    "PRIMARY_PRESSED": "#14B8A6",
    "PRIMARY_LIGHT": "#134E4A",     # 深色下 "light" 语义反转为低饱和深底
    "PRIMARY_FAINT": "#0F2E2B",

    "ACCENT": "#FBBF24",
    "ACCENT_LIGHT": "#3A2E12",

    "COLOR_RED": "#F87171",
    "COLOR_RED_LIGHT": "#3A1A1A",
    "COLOR_GREEN_BG": "#0E2A22",
    "COLOR_GREEN_TEXT": "#4ADE80",
    "COLOR_GREEN_DOT": "#34D399",
    "COLOR_WARN_BG": "#2E2410",
    "COLOR_WARN_TEXT": "#FBBF24",

    "TEXT_PRIMARY": "#E8EDF5",
    "TEXT_SECONDARY": "#CBD5E1",
    "TEXT_MUTED": "#94A3B8",
    "TEXT_LIGHT": "#64748B",
    "TEXT_ON_PRIMARY": "#062925",
}

_PALETTES = {"light": _LIGHT, "dark": _DARK}
_current = "light"


class _Tokens:
    """稳定引用的调色板视图 —— `T.PRIMARY` 在使用时才解析当前主题。"""

    __slots__ = ()

    def __getattr__(self, name):
        try:
            return _PALETTES[_current][name]
        except KeyError:
            raise AttributeError(f"未知设计 token: {name}") from None

    @property
    def name(self) -> str:
        return _current

    @property
    def is_dark(self) -> bool:
        return _current == "dark"


T = _Tokens()


def current_theme() -> str:
    return _current


def apply_theme(name: str) -> bool:
    """切换主题。返回是否发生变化 (变化后需重建窗口才能全量生效)。"""
    global _current, _style_cache
    if name not in _PALETTES or name == _current:
        return False
    _current = name
    _style_cache = None
    return True


# ---------------- 字体 ----------------

# 字体规范: 锁定纯净 'Microsoft YaHei UI' (UI专版，基线和字高经过界面优化)
FONT_STACK = "'Microsoft YaHei UI'"
FONT_STACK_DISPLAY = "'Microsoft YaHei UI'"
MONO = "'Consolas'"


def setup_app_font(app):
    """全局注入高质量中文字体配置与抗锯齿渲染策略:
    1. 锁定纯净 'Microsoft YaHei UI' 作为首选界面字体;
    2. 启用 PreferAntialias 子像素抗锯齿;
    3. 消除中西文回退断层与算法描粗毛刺。
    """
    from PyQt6.QtGui import QFont
    font = QFont("Microsoft YaHei UI", 9)  # 9pt 对应标准桌面 12-13px
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.PreferQuality)
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(font)


def _gen_combo_arrow() -> str:
    """生成下拉箭头 PNG (QSS ::down-arrow 只认图片文件), 返回 url 可用路径。

    必须在 QApplication 存在后调用 (QPixmap 前置条件), 故由 global_style() 惰性触发。
    箭头颜色随主题走, 因此文件名带主题名, 换肤时不会串用旧图。
    """
    import tempfile
    try:
        from ui import icons
    except ImportError:
        try:
            from . import icons
        except ImportError:
            import icons  # type: ignore
    out = os.path.join(tempfile.gettempdir(), f"vremote_combo_arrow_{_current}.png")
    icons.icon_pixmap("chevron_down", T.TEXT_MUTED, 16).save(out, "PNG")
    return out.replace("\\", "/")


# ---------------- 下拉框现代委托与辅助器 ----------------

from PyQt6.QtCore import QModelIndex, QSize, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter
from PyQt6.QtWidgets import QComboBox, QListView, QStyle, QStyledItemDelegate, QStyleOptionViewItem


class ComboItemDelegate(QStyledItemDelegate):
    """现代极简下拉列表项代理:
    1. 锁定高度 32px，行距舒适均匀；
    2. 消除悬浮药丸感，采用通透贴合微圆角 (5px) 与同心边距；
    3. 状态分明：选中态为极浅青底 + 加粗主色字 + 右侧勾选符 (✓)；悬停态为清爽淡底；
    4. 彻底消除双层盒子割裂感。
    """

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(option.rect.width(), 32)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 贴合边距：上下微留 1px 间隙，左右微留 2px
        rect = option.rect.adjusted(2, 1, -2, -1)
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hover = bool(option.state & QStyle.StateFlag.State_MouseOver)

        # 1. 柔和背景 (选中: 主色极浅底 / 悬停: 中性淡底)
        if is_selected:
            painter.setBrush(QBrush(QColor(T.PRIMARY_FAINT)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 5, 5)
        elif is_hover:
            painter.setBrush(QBrush(QColor(T.BG_SUBTLE)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 5, 5)

        # 2. 文字与勾选标记
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if text:
            if is_selected:
                painter.setPen(QColor(T.PRIMARY))
                font = painter.font()
                font.setBold(True)
                painter.setFont(font)
            elif is_hover:
                painter.setPen(QColor(T.TEXT_PRIMARY))
            else:
                painter.setPen(QColor(T.TEXT_SECONDARY))

            # 主文本区域 (右侧预留 28px 给勾选标记)
            text_rect = rect.adjusted(10, 0, -28, 0)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)

            # 选中状态在右侧绘制精美勾选标记 ✓
            if is_selected:
                check_rect = rect.adjusted(rect.width() - 24, 0, -6, 0)
                painter.setPen(QColor(T.PRIMARY))
                painter.drawText(check_rect, Qt.AlignmentFlag.AlignCenter, "✓")

        painter.restore()


def setup_combo_box(combo: QComboBox):
    """为 QComboBox 注入现代化列表与委托体系:
    - 挂载 QListView 替换原生系统菜单;
    - 彻底剥离 Qt 原生 QComboBoxPrivateContainer 的 StyledPanel 矩形边框束缚;
    - 挂载 ComboItemDelegate 自绘项 (消除 ▲/▼ 滚动三角与悬空药丸感);
    - 设置鼠标悬停手型光标 (PointingHandCursor);
    - 优化滚动条策略与无边框嵌套。
    """
    combo.setCursor(Qt.CursorShape.PointingHandCursor)
    combo.setMaxVisibleItems(10)
    view = QListView(combo)
    view.setObjectName("styled_combo_view")
    view.setItemDelegate(ComboItemDelegate(view))
    view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    view.setAutoScroll(False)
    view.setSpacing(1)
    view.setFrameShape(QListView.Shape.NoFrame)
    view.setLineWidth(0)
    combo.setView(view)

    # 彻底拿掉 Qt 原生容器的 StyledPanel 外层硬框与系统边框
    container = view.parentWidget()
    if container is not None:
        from PyQt6.QtWidgets import QFrame
        if isinstance(container, QFrame):
            container.setFrameShape(QFrame.Shape.NoFrame)
            container.setLineWidth(0)
            container.setMidLineWidth(0)
        container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        if container.layout() is not None:
            container.layout().setContentsMargins(0, 0, 0, 0)
            container.layout().setSpacing(0)


# ---------------- 全局样式 ----------------

def _build_qss(_arrow: str) -> str:
    return f"""
QWidget {{
    background-color: {T.BG_APP};
    color: {T.TEXT_PRIMARY};
    font-family: {FONT_STACK};
    font-size: 13px;
}}

/* ---------- 侧边栏 ---------- */
#sidebar_panel {{
    background-color: {T.BG_SIDEBAR};
    border-right: 1px solid {T.BORDER_CARD};
}}
#sidebar_nav_btn {{
    background-color: transparent;
    border: none;
    border-radius: 10px;
    padding: 8px 6px;
    color: {T.TEXT_MUTED};
    font-weight: normal;
    font-size: 11px;
}}
#sidebar_nav_btn:hover {{
    background-color: {T.BG_CARD_HOVER};
    color: {T.TEXT_PRIMARY};
}}
#sidebar_nav_btn:checked {{
    background-color: {T.PRIMARY_LIGHT};
    color: {T.PRIMARY};
    font-weight: bold;
}}
#live_chip {{
    border-radius: 9px;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: normal;
}}

/* ---------- 卡片: 阴影表海拔, 边框表结构 ---------- */
QFrame#card {{
    background-color: {T.BG_CARD};
    border: 1px solid {T.BORDER_CARD};
    border-radius: 14px;
}}
QFrame#card:hover {{
    border: 1px solid {T.BORDER_CARD_HOVER};
}}
QFrame#card_flat {{
    background-color: {T.BG_CARD};
    border: 1px solid {T.BORDER_CARD};
    border-radius: 14px;
}}
QFrame#banner_warn {{
    background-color: {T.COLOR_WARN_BG};
    border: 1px solid {T.COLOR_WARN_TEXT};
    border-radius: 12px;
}}
QFrame#banner_ok {{
    background-color: {T.COLOR_GREEN_BG};
    border: 1px solid {T.COLOR_GREEN_DOT};
    border-radius: 12px;
}}

/* ---------- 徽章 (药丸) ---------- */
QLabel#badge_online {{
    background-color: {T.COLOR_GREEN_BG};
    color: {T.COLOR_GREEN_TEXT};
    border: 1px solid {T.COLOR_GREEN_DOT};
    border-radius: 10px;
    padding: 3px 12px;
    font-size: 11px;
    font-weight: normal;
}}
QLabel#badge_warn {{
    background-color: {T.COLOR_WARN_BG};
    color: {T.COLOR_WARN_TEXT};
    border: 1px solid {T.COLOR_WARN_TEXT};
    border-radius: 10px;
    padding: 3px 12px;
    font-size: 11px;
    font-weight: normal;
}}

/* ---------- 排版 ---------- */
QLabel {{
    background: transparent;
}}
QLabel#page_title {{
    font-size: 20px;
    font-weight: bold;
    color: {T.TEXT_PRIMARY};
    font-family: {FONT_STACK_DISPLAY};
}}
QLabel#page_subtitle {{
    font-size: 12px;
    color: {T.TEXT_MUTED};
}}
QLabel#card_title {{
    font-size: 14px;
    font-weight: bold;
    color: {T.TEXT_PRIMARY};
}}
QLabel#caption {{
    font-size: 12px;
    color: {T.TEXT_MUTED};
}}

/* ---------- 按钮: 完整 hover/pressed 态 ---------- */
QPushButton {{
    background-color: {T.BG_CARD};
    color: {T.TEXT_SECONDARY};
    font-weight: normal;
    font-size: 12px;
    border: 1px solid {T.BORDER_INPUT};
    border-radius: 8px;
    padding: 6px 16px;
}}
QPushButton:hover {{
    border-color: {T.BORDER_CARD_HOVER};
    color: {T.PRIMARY};
}}
QPushButton:pressed {{
    background-color: {T.BG_CARD_HOVER};
}}
QPushButton:disabled {{
    color: {T.TEXT_LIGHT};
    border-color: {T.BORDER_CARD};
}}

QPushButton#primary_blue_btn {{
    background-color: {T.PRIMARY};
    color: {T.TEXT_ON_PRIMARY};
    font-weight: bold;
    font-size: 12px;
    border: none;
    border-radius: 8px;
    padding: 7px 18px;
}}
QPushButton#primary_blue_btn:hover {{
    background-color: {T.PRIMARY_HOVER};
}}
QPushButton#primary_blue_btn:pressed {{
    background-color: {T.PRIMARY_PRESSED};
}}
QPushButton#danger_btn {{
    background-color: transparent;
    color: {T.COLOR_RED};
    font-size: 12px;
    border: 1px solid {T.COLOR_RED};
    border-radius: 8px;
    padding: 6px 14px;
}}
QPushButton#danger_btn:hover {{
    background-color: {T.COLOR_RED_LIGHT};
}}
QPushButton#secondary_btn {{
    background-color: {T.BG_CARD};
    color: {T.TEXT_SECONDARY};
    font-weight: normal;
    font-size: 12px;
    border: 1px solid {T.BORDER_INPUT};
    border-radius: 8px;
    padding: 6px 14px;
}}
QPushButton#secondary_btn:hover {{
    background-color: {T.PRIMARY_FAINT};
    border-color: {T.BORDER_CARD_HOVER};
    color: {T.PRIMARY};
}}
QPushButton#secondary_btn:pressed {{
    background-color: {T.PRIMARY_LIGHT};
}}

/* 分段控件 (预设方案切换) */
QPushButton#segment_btn {{
    background-color: transparent;
    color: {T.TEXT_MUTED};
    border: none;
    border-radius: 8px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: normal;
}}
QPushButton#segment_btn:hover {{
    color: {T.TEXT_PRIMARY};
    background-color: {T.BG_CHIP};
}}
QPushButton#segment_btn:checked {{
    background-color: {T.PRIMARY};
    color: {T.TEXT_ON_PRIMARY};
    font-weight: bold;
}}

/* ---------- 输入控件: 下拉框 ---------- */
QComboBox {{
    background-color: {T.BG_INPUT};
    border: 1px solid {T.BORDER_INPUT};
    border-radius: 8px;
    padding: 6px 36px 6px 12px;
    color: {T.TEXT_PRIMARY};
    font-size: 12px;
    min-height: 20px;
}}
QComboBox:hover {{
    border-color: {T.BORDER_CARD_HOVER};
    background-color: {T.BG_CARD_HOVER};
}}
QComboBox:focus {{
    border: 2px solid {T.PRIMARY};
    padding: 5px 35px 5px 11px;
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 30px;
    border-left: 1px solid {T.BORDER_CARD};
    background: transparent;
}}
QComboBox::drop-down:hover {{
    background: {T.PRIMARY_FAINT};
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
}}
QComboBox::down-arrow {{
    width: 14px;
    height: 14px;
    {_arrow}
}}
QComboBoxPrivateContainer {{
    background: transparent;
    border: none;
    padding: 0px;
    margin: 0px;
}}
QComboBox QAbstractItemView {{
    background-color: {T.BG_CARD};
    border: none;
    border-radius: 8px;
    padding: 3px;
    outline: none;
    selection-background-color: transparent;
}}
QSpinBox, QLineEdit {{
    background-color: {T.BG_INPUT};
    border: 1px solid {T.BORDER_INPUT};
    border-radius: 8px;
    padding: 6px 12px;
    color: {T.TEXT_PRIMARY};
    font-size: 12px;
    min-height: 20px;
}}
QSpinBox:hover, QLineEdit:hover {{
    border-color: {T.BORDER_CARD_HOVER};
}}
QSpinBox:focus, QLineEdit:focus {{
    border: 2px solid {T.PRIMARY};
    padding: 5px 11px;
}}
QSpinBox::up-button, QSpinBox::down-button {{
    background: transparent;
    border: none;
    width: 18px;
}}

/* ---------- 滑块 ---------- */
QSlider::groove:horizontal {{
    height: 5px;
    background: {T.BORDER_SOFT};
    border-radius: 2.5px;
}}
QSlider::sub-page:horizontal {{
    background: {T.PRIMARY};
    border-radius: 2.5px;
}}
QSlider::handle:horizontal {{
    background: {T.BG_CARD};
    border: 1.5px solid {T.BORDER_INPUT};
    width: 16px;
    height: 16px;
    margin-top: -6px;
    margin-bottom: -6px;
    border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{
    border-color: {T.PRIMARY};
}}

/* ---------- 滚动条 ---------- */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {T.BORDER_SOFT};
    border-radius: 5px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: {T.TEXT_LIGHT};
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- 提示 ---------- */
QToolTip {{
    background-color: {T.BG_CARD};
    color: {T.TEXT_PRIMARY};
    border: 1px solid {T.BORDER_INPUT};
    border-radius: 6px;
    padding: 5px 8px;
    font-size: 11px;
}}
"""


_style_cache: str | None = None


def global_style() -> str:
    """当前主题的全局样式 (惰性: 首次调用时生成下拉箭头资源 —— QPixmap 需 QApplication 先行)。"""
    global _style_cache
    if _style_cache is not None:
        return _style_cache

    arrow = ""
    try:
        url = _gen_combo_arrow()
        if url and os.path.exists(url):
            arrow = f"image: url({url});"
    except Exception:
        pass

    qss = _build_qss(arrow)
    if arrow:
        _style_cache = qss
    return qss
