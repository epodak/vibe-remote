"""语音回眸页 (view_transcripts.py) — 2026-08-23 v3。

v1 加载 3 条硬编码假数据 —— 已废除。
v2 读真实 transcripts.jsonl, 但**每次搜索按键都全量重建卡片**: 攒到几百条以后
   输入框会明显卡顿, 且没有任何回收手段, 文件只增不减。
v3 (本版):
  · 渲染上限 + 搜索防抖 —— 只渲染最近 RENDER_LIMIT 条命中, 超出部分给出计数提示;
  · 增量判定改用 (文件大小, mtime) 指纹, 比旧版"只比行数"更可靠;
  · 补上导出 (Markdown) 与清空 —— 这是一份会一直长大的个人语音档案, 得能管理。
"""

import json
import os
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget
)

from ui import icons
from ui.style_theme import MONO, T


class TranscriptCard(QFrame):
    """单条语音转写记录卡片"""

    def __init__(self, record: dict, parent=None):
        super().__init__(parent)
        self.text = record.get("text", "")
        self.setObjectName("card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(8)

        top = QHBoxLayout()
        lbl_time = QLabel(record.get("ts", ""))
        lbl_time.setStyleSheet(f"font-size: 11px; color: {T.TEXT_MUTED}; font-family: {MONO};")
        top.addWidget(lbl_time)
        badge = QLabel("语音输入")
        badge.setStyleSheet(
            f"background-color: {T.PRIMARY_LIGHT}; color: {T.PRIMARY}; "
            f"border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: normal;")
        top.addWidget(badge)
        top.addStretch(1)
        perf = f"{record.get('chars', len(self.text))} 字"
        if record.get("asr_ms"):
            perf += f" · 转写 {record['asr_ms']} ms"
        lbl_perf = QLabel(perf)
        lbl_perf.setStyleSheet(f"font-size: 11px; color: {T.TEXT_MUTED}; font-family: {MONO};")
        top.addWidget(lbl_perf)
        layout.addLayout(top)

        lbl_content = QLabel(self.text)
        lbl_content.setWordWrap(True)
        lbl_content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lbl_content.setStyleSheet(f"font-size: 13px; color: {T.TEXT_PRIMARY}; line-height: 1.45;")
        layout.addWidget(lbl_content)

        actions = QHBoxLayout()
        actions.addStretch(1)
        btn_copy = QPushButton("复制")
        btn_copy.setObjectName("secondary_btn")
        btn_copy.setFixedHeight(26)
        btn_copy.clicked.connect(self._copy)
        actions.addWidget(btn_copy)
        layout.addLayout(actions)

    def _copy(self):
        cb = QApplication.clipboard()
        if cb:
            cb.setText(self.text)


class TranscriptsView(QWidget):
    """语音回眸视图 (真实 transcripts.jsonl)"""

    RENDER_LIMIT = 200      # 单次最多渲染的卡片数 (再多就是滚动条里的僵尸控件)
    SEARCH_DEBOUNCE_MS = 220

    def __init__(self, parent=None):
        super().__init__(parent)
        self.records = []
        self._fingerprint = None
        self.path = os.path.normpath(os.path.join(
            os.path.dirname(__file__), "..", "..", "transcripts.jsonl"))

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(self.SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self._render)

        self._init_ui()
        self._reload()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._reload)
        self.timer.start(2000)

    def shutdown(self):
        self.timer.stop()
        self._search_timer.stop()

    # ---------------- UI ----------------

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(12)

        head = QHBoxLayout()
        title_v = QVBoxLayout()
        title_v.setSpacing(2)
        t = QLabel("语音回眸")
        t.setObjectName("page_title")
        s = QLabel("每一次语音转写的完整存档 — 来自 transcripts.jsonl 实时增量加载")
        s.setObjectName("page_subtitle")
        title_v.addWidget(t)
        title_v.addWidget(s)
        head.addLayout(title_v, stretch=1)
        self.lbl_count = QLabel("0 条")
        self.lbl_count.setStyleSheet(
            f"font-size: 12px; color: {T.COLOR_GREEN_TEXT}; font-weight: bold; font-family: {MONO};")
        head.addWidget(self.lbl_count)
        root.addLayout(head)

        tool_bar = QHBoxLayout()
        tool_bar.setSpacing(8)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索历史语音识别文本…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setFixedHeight(34)
        self.search_input.textChanged.connect(lambda _: self._search_timer.start())
        tool_bar.addWidget(self.search_input, stretch=1)

        self.btn_export = QPushButton("  导出 Markdown")
        self.btn_export.setObjectName("secondary_btn")
        self.btn_export.setIcon(icons.icon("download", T.TEXT_SECONDARY, 15))
        self.btn_export.setFixedHeight(34)
        self.btn_export.clicked.connect(self._export)
        tool_bar.addWidget(self.btn_export)

        self.btn_clear = QPushButton("  清空存档")
        self.btn_clear.setObjectName("danger_btn")
        self.btn_clear.setIcon(icons.icon("trash", T.COLOR_RED, 15))
        self.btn_clear.setFixedHeight(34)
        self.btn_clear.clicked.connect(self._clear)
        tool_bar.addWidget(self.btn_clear)
        root.addLayout(tool_bar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("background: transparent; border: none;")
        self.list_container = QWidget()
        self.list_container.setStyleSheet("background: transparent;")
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 4, 0, 4)
        self.list_layout.setSpacing(10)
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.list_container)
        root.addWidget(self.scroll, stretch=1)

    # ---------------- 数据 ----------------

    def _reload(self):
        try:
            st = os.stat(self.path)
            fingerprint = (st.st_size, int(st.st_mtime))
        except OSError:
            fingerprint = None
            if self._fingerprint is None and self.records:
                return
        if fingerprint is not None and fingerprint == self._fingerprint:
            return
        self._fingerprint = fingerprint

        records = []
        try:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except ValueError:
                        continue
        except FileNotFoundError:
            records = []
        except OSError:
            return
        self.records = records
        self._render()

    def _render(self):
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        kw = self.search_input.text().strip().lower()
        total_chars = sum(r.get("chars", len(r.get("text", ""))) for r in self.records)
        matched = [r for r in reversed(self.records)
                   if not kw or kw in r.get("text", "").lower()]

        for rec in matched[:self.RENDER_LIMIT]:
            self.list_layout.addWidget(TranscriptCard(rec, self.list_container))

        if len(matched) > self.RENDER_LIMIT:
            more = QLabel(f"仅显示最近 {self.RENDER_LIMIT} 条 (共 {len(matched)} 条命中) —— "
                          "用搜索缩小范围, 或导出 Markdown 全量查看")
            more.setAlignment(Qt.AlignmentFlag.AlignCenter)
            more.setStyleSheet(f"color: {T.TEXT_MUTED}; font-size: 12px; padding: 14px;")
            self.list_layout.addWidget(more)

        self.lbl_count.setText(
            f"{len(self.records)} 条 · 共 {total_chars} 字"
            + (f" · 筛选 {len(matched)} 条" if kw else ""))

        if not self.records:
            empty = QLabel("还没有转写记录 — 按遥控器语音键说一句话试试")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color: {T.TEXT_MUTED}; font-size: 13px; padding: 40px;")
            self.list_layout.addWidget(empty)
        elif not matched:
            empty = QLabel(f"没有包含「{self.search_input.text().strip()}」的记录")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color: {T.TEXT_MUTED}; font-size: 13px; padding: 40px;")
            self.list_layout.addWidget(empty)

    # ---------------- 归档管理 ----------------

    def _export(self):
        if not self.records:
            return
        default = os.path.join(
            os.path.expanduser("~"), f"vremote_transcripts_{time.strftime('%Y%m%d')}.md")
        path, _ = QFileDialog.getSaveFileName(self, "导出语音存档", default, "Markdown (*.md)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("# vRemote 语音转写存档\n\n")
                f.write(f"导出时间: {time.strftime('%Y-%m-%d %H:%M:%S')} · "
                        f"共 {len(self.records)} 条\n\n")
                for rec in self.records:
                    f.write(f"## {rec.get('ts', '')}\n\n{rec.get('text', '')}\n\n")
        except OSError as e:
            QMessageBox.warning(self, "导出失败", str(e))
            return
        QMessageBox.information(self, "导出完成", f"已写入:\n{path}")

    def _clear(self):
        if not self.records:
            return
        ok = QMessageBox.question(
            self, "清空语音存档",
            f"将删除全部 {len(self.records)} 条转写记录 (transcripts.jsonl)。\n"
            "captured_audio/ 下的原始录音不受影响。此操作不可撤销, 确定吗?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if ok != QMessageBox.StandardButton.Yes:
            return
        try:
            os.remove(self.path)
        except OSError as e:
            QMessageBox.warning(self, "清空失败", str(e))
            return
        self.records = []
        self._fingerprint = None
        self._render()
