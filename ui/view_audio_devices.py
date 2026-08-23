"""硬件与语音链路页 (view_audio_devices.py) — 全部真实数据。

视觉 (ui-skills 规则): 卡片投影表海拔 / 手绘线性图标 / 拨杆开关微交互 /
数字等宽字体 / 真机图 1px 描边圆角。

音频架构 (2026-08-23 扇出):
- clipboard 直投模式: 只显示「录音与转写增益」(增益真实作用于送转写的 WAV);
- vokie 原生听写模式: 显示扇出状态 (全部虚拟声卡并行推流, vokie 任选一个
  配对输入即可听到) + 链路自检 (播放测试音并实测各输入端能否听到)。
"""

import math
import os
import time

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton,
    QSlider, QVBoxLayout, QWidget
)

from ui import icons
from ui.style_theme import T, MONO
from ui.widgets import Meter, StatusRow, ToggleSwitch, attach_shadow, shadow_color



class X6PhotoWidget(QWidget):
    """X6 真机渲染立绘 (1px 低透明度描边 + 圆角)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(100, 206)
        path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "assets", "x6_front.png"))
        self.pixmap = QPixmap(path) if os.path.exists(path) else None

    def paintEvent(self, event):
        if not (self.pixmap and not self.pixmap.isNull()):
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        scaled = self.pixmap.scaled(w - 8, h - 8, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
        x, y = (w - scaled.width()) / 2, (h - scaled.height()) / 2
        clip = QPainterPath()
        m = 10
        clip.addRoundedRect(x - m, y - m, scaled.width() + 2 * m, scaled.height() + 2 * m, 14, 14)
        p.save()
        p.setClipPath(clip)
        p.drawPixmap(int(x), int(y), scaled)
        p.restore()
        p.setPen(QPen(shadow_color(30), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(clip)


class AsrHealthThread(QThread):
    """vokie 健康检查后台轮询 (真实 HTTP)。

    轮询间隔用"分片睡眠"而非 sleep(5): QThread 若在析构时仍在运行, Qt 会直接
    abort 整个进程 (实测: 关闭窗口/退出时的静默崩溃)。分片让 requestInterruption
    最迟 0.5s 就能生效, stop() 于是能在窗口销毁前干净收尾。
    """
    stateChanged = pyqtSignal(str, str, str)  # text, color, latency_ms_str

    POLL_S = 5.0
    SLICE_S = 0.5

    def run(self):
        from core import asr_client
        while not self.isInterruptionRequested():
            try:
                t0 = time.time()
                h = asr_client.health()
                ms = int((time.time() - t0) * 1000)
                self.stateChanged.emit(f"在线 · v{h.get('version', '?')}", T.COLOR_GREEN_TEXT, f"{ms} ms")
            except Exception as e:
                self.stateChanged.emit(f"离线 — {e}", T.COLOR_RED, "—")
            waited = 0.0
            while waited < self.POLL_S and not self.isInterruptionRequested():
                self.msleep(int(self.SLICE_S * 1000))
                waited += self.SLICE_S

    def stop(self, timeout_ms: int = 2000):
        self.requestInterruption()
        self.wait(timeout_ms)


def _card(title: str, icon_name: str | None = None) -> tuple[QFrame, QVBoxLayout]:
    """标准卡片: 投影 + 标题行(可选线性图标)"""
    card = QFrame()
    card.setObjectName("card")
    attach_shadow(card)
    v = QVBoxLayout(card)
    v.setContentsMargins(20, 16, 20, 16)
    v.setSpacing(10)
    head = QHBoxLayout()
    head.setSpacing(8)
    if icon_name:
        ic = QLabel()
        ic.setPixmap(icons.icon_pixmap(icon_name, T.PRIMARY, 18))
        ic.setStyleSheet("background: transparent;")
        head.addWidget(ic)
    t = QLabel(title)
    t.setObjectName("card_title")
    head.addWidget(t)
    head.addStretch(1)
    v.addLayout(head)
    return card, v


class AudioDevicesView(QWidget):
    """硬件与语音链路主视图 (真实数据)"""

    selftestDone = pyqtSignal(list)   # 工作线程 -> GUI 线程回传自检结果

    def __init__(self, coordinator=None, parent=None):
        super().__init__(parent)
        self.coord = coordinator
        self._last_delivery = None
        self.selftestDone.connect(self._on_selftest_done)
        self._init_ui()

    # ---------------- UI ----------------

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(16)

        head = QHBoxLayout()
        title_v = QVBoxLayout()
        title_v.setSpacing(2)
        lbl_title = QLabel("硬件与语音链路")
        lbl_title.setObjectName("page_title")
        lbl_sub = QLabel("X6 蓝牙握手 · 音频管道 · vokie 转写服务 —— 全部实时真实状态")
        lbl_sub.setObjectName("page_subtitle")
        title_v.addWidget(lbl_title)
        title_v.addWidget(lbl_sub)
        head.addLayout(title_v)
        head.addStretch(1)
        root.addLayout(head)

        main_h = QHBoxLayout()
        main_h.setSpacing(16)

        # ======== 左: X6 硬件卡 ========
        left_card = QFrame()
        left_card.setObjectName("card")
        attach_shadow(left_card, blur=26, dy=5, alpha=52)
        left_card.setFixedWidth(272)
        lv = QVBoxLayout(left_card)
        lv.setContentsMargins(18, 18, 18, 18)
        lv.setSpacing(10)

        dev_title = QLabel("X6 双面空中飞鼠")
        dev_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dev_title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {T.TEXT_PRIMARY};")
        lv.addWidget(dev_title)

        self.badge_conn = QLabel("● 检测中…")
        self.badge_conn.setObjectName("badge_online")
        self.badge_conn.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lv.addWidget(self.badge_conn)

        photo_row = QHBoxLayout()
        photo_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        photo_row.addWidget(X6PhotoWidget())
        lv.addLayout(photo_row)

        self.row_ble = StatusRow("蓝牙 ATVV")
        self.row_hid = StatusRow("HID 拦截钩子")
        self.row_session = StatusRow("语音会话")
        self.row_output = StatusRow("混音输出")
        for r in (self.row_ble, self.row_hid, self.row_session, self.row_output):
            lv.addWidget(r)

        lv.addSpacing(4)
        for label_text, attr in (("X6 电平", "x6"), ("麦克风电平", "mic")):
            lbl = QLabel(label_text)
            lbl.setStyleSheet(f"font-size: 11px; color: {T.TEXT_MUTED};")
            lv.addWidget(lbl)
            meter = Meter(f"{T.COLOR_GREEN_DOT}")
            setattr(self, f"meter_{attr}", meter)
            lv.addWidget(meter)

        lv.addStretch(1)
        self.btn_reconnect = QPushButton("重新连接蓝牙")
        self.btn_reconnect.setObjectName("primary_blue_btn")
        self.btn_reconnect.setFixedHeight(34)
        self.btn_reconnect.clicked.connect(self._reconnect)
        lv.addWidget(self.btn_reconnect)

        main_h.addWidget(left_card)

        # ======== 右侧 ========
        right_v = QVBoxLayout()
        right_v.setSpacing(16)

        # 卡1: 按投递模式变形 (clipboard=增益卡 / vokie=扇出+自检卡)
        card_mix, cv = _card("录音与转写增益", "mic")

        def _wrap_row(layout) -> QWidget:
            w = QWidget()
            w.setStyleSheet("background: transparent;")
            w.setLayout(layout)
            cv.addWidget(w)
            return w

        # --- clipboard 模式行 ---
        self.lbl_gain_x6_title = QLabel("遥控器增益 (作用于转写音频)")
        self.lbl_gain_x6_title.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {T.TEXT_PRIMARY};")

        def gain_row(title_lbl, attr):
            row = QHBoxLayout()
            row.addWidget(title_lbl)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(-12, 30)
            db = int(round(20 * math.log10(max(getattr(self._ap(), attr) if self._ap() else 1.0, 1e-3))))
            slider.setValue(db)
            lbl = QLabel(f"{db:+d} dB")
            lbl.setFixedWidth(56)
            lbl.setStyleSheet(f"color: {T.PRIMARY}; font-weight: bold; font-family: {MONO}; font-size: 12px;")
            slider.valueChanged.connect(lambda v, a=attr, l=lbl: self._on_gain(a, v, l))
            row.addWidget(slider, stretch=1)
            row.addWidget(lbl)
            return row, slider

        row_x6, self.slider_x6 = gain_row(self.lbl_gain_x6_title, "x6_gain")
        _wrap_row(row_x6)   # 常显行

        # --- vokie 模式行 ---
        self.lbl_gain_mic_title = QLabel("系统麦克风增益 (仅混音监听)")
        self.lbl_gain_mic_title.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {T.TEXT_PRIMARY};")
        row_mic, self.slider_mic = gain_row(self.lbl_gain_mic_title, "mic_gain")
        self.w_row_mic = _wrap_row(row_mic)

        fanout_row = QHBoxLayout()
        lbl_fo = QLabel("虚拟声卡扇出")
        lbl_fo.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {T.TEXT_PRIMARY};")
        fanout_row.addWidget(lbl_fo)
        fanout_row.addStretch(1)
        self.lbl_fanout = QLabel("—")
        self.lbl_fanout.setStyleSheet(f"font-size: 11px; color: {T.TEXT_MUTED}; font-family: {MONO};")
        fanout_row.addWidget(self.lbl_fanout)
        self.w_row_fanout = _wrap_row(fanout_row)

        test_row = QHBoxLayout()
        self.btn_selftest = QPushButton("链路自检 (播放 2s 测试音)")
        self.btn_selftest.setObjectName("secondary_btn")
        self.btn_selftest.clicked.connect(self._run_selftest)
        test_row.addWidget(self.btn_selftest)
        test_row.addStretch(1)
        self.w_row_selftest = _wrap_row(test_row)

        self.lbl_selftest = QLabel("")
        self.lbl_selftest.setWordWrap(True)
        self.lbl_selftest.setStyleSheet(f"font-size: 11px; color: {T.TEXT_MUTED};")
        st_row = QHBoxLayout()
        st_row.addWidget(self.lbl_selftest)
        self.w_row_st_result = _wrap_row(st_row)

        # 混入开关 (vokie 模式)
        mix_row = QHBoxLayout()
        mix_row.setSpacing(20)

        def mix_toggle(title, attr, checked):
            box = QHBoxLayout()
            box.setSpacing(8)
            sw = ToggleSwitch(checked)
            lbl = QLabel(title)
            lbl.setStyleSheet(f"font-size: 12px; color: {T.TEXT_PRIMARY};")

            def _click(e, s=sw, a=attr):
                s.setChecked(not s.isChecked())
                ap = self._ap()
                if ap:
                    setattr(ap, a, s.isChecked())
            sw.mousePressEvent = _click
            box.addWidget(sw)
            box.addWidget(lbl)
            return box

        ap = self._ap()
        mix_row.addLayout(mix_toggle("混入 X6 音频", "mix_x6", bool(ap and ap.mix_x6)))
        mix_row.addLayout(mix_toggle("混入系统麦克风", "mix_system_mic", bool(ap and ap.mix_system_mic)))
        mix_row.addStretch(1)
        self.w_row_mix = _wrap_row(mix_row)

        # 模式说明
        self.lbl_mode_note_clipboard = QLabel(
            "clipboard 直投模式: 音频走 BLE → 本地解码 → vokie HTTP 转写 (裸 ASR), 无需虚拟声卡。"
            "上面的增益直接作用于送转写的录音。要享受 vokie 原生云端 2-Pass + LLM 表达力场润色, "
            "到「偏好设置」切为 vokie 原生听写模式。")
        self.lbl_mode_note_clipboard.setWordWrap(True)
        self.lbl_mode_note_clipboard.setStyleSheet(f"font-size: 11px; color: {T.TEXT_MUTED};")
        cv.addWidget(self.lbl_mode_note_clipboard)
        self.lbl_mode_note_vokie = QLabel(
            "vokie 原生听写: 音频同时推入上面全部虚拟声卡, vokie 设置里任选一个配对输入 (麦克风) 即可听到遥控器。"
            "链路自检会实测各输入端能否听到测试音; 若 vokie 用的是物理麦克风则听不到, 需在 vokie 内改选虚拟麦克风。")
        self.lbl_mode_note_vokie.setWordWrap(True)
        self.lbl_mode_note_vokie.setStyleSheet(f"font-size: 11px; color: {T.TEXT_MUTED};")
        cv.addWidget(self.lbl_mode_note_vokie)

        right_v.addWidget(card_mix)
        self.card_mix_title = card_mix.findChild(QLabel, "card_title")

        # 卡2: vokie 转写服务
        card_asr, av = _card("vokie 本地语音转写引擎", "bluetooth")

        asr_head = QHBoxLayout()
        self.lbl_asr = QLabel("检查中…")
        self.lbl_asr.setStyleSheet(f"font-size: 11px; color: {T.TEXT_MUTED}; font-weight: bold;")
        asr_head.addStretch(1)
        asr_head.addWidget(self.lbl_asr)
        av.addLayout(asr_head)

        self.lbl_asr_lat = QLabel("健康检查延迟: —")
        self.lbl_asr_lat.setStyleSheet(f"font-size: 11px; color: {T.TEXT_MUTED}; font-family: {MONO};")
        av.addWidget(self.lbl_asr_lat)

        btn_row = QHBoxLayout()
        btn_test = QPushButton("测试转写链路 (取最近一条录音)")
        btn_test.setObjectName("secondary_btn")
        btn_test.clicked.connect(self._test_asr)
        btn_row.addWidget(btn_test)
        btn_row.addStretch(1)
        av.addLayout(btn_row)

        self.lbl_test_result = QLabel("")
        self.lbl_test_result.setWordWrap(True)
        self.lbl_test_result.setStyleSheet(f"font-size: 11px; color: {T.TEXT_MUTED};")
        av.addWidget(self.lbl_test_result)

        right_v.addWidget(card_asr)
        right_v.addStretch(1)
        main_h.addLayout(right_v, stretch=1)
        root.addLayout(main_h)

        self._asr_thread = AsrHealthThread(self)
        self._asr_thread.stateChanged.connect(self._on_asr_state)
        self._asr_thread.start()

        # 构造时立即按当前投递模式初始化卡片 (不等首个快照)
        self._apply_delivery_mode(
            getattr(self.coord, "text_delivery", "clipboard") if self.coord else "clipboard")

    def _ap(self):
        return self.coord.audio_pipe if self.coord else None

    def shutdown(self):
        """窗口销毁前必须调用: 停掉健康检查线程 (否则 QThread 析构会 abort 进程)。"""
        th = getattr(self, "_asr_thread", None)
        if th is not None and th.isRunning():
            th.stop()

    def closeEvent(self, e):
        self.shutdown()
        super().closeEvent(e)

    # ---------------- 动作 ----------------

    def _reconnect(self):
        import asyncio
        if self.coord and self.coord.loop and not self.coord.loop.is_closed():
            asyncio.run_coroutine_threadsafe(self.coord.restart_ble(), self.coord.loop)

    def _on_gain(self, attr, db, lbl):
        lbl.setText(f"{db:+d} dB")
        ap = self._ap()
        if ap:
            setattr(ap, attr, 10 ** (db / 20.0))

    def _run_selftest(self):
        """真实链路自检: 向全部扇出播 2s 测试音, 实测各虚拟输入端能否听到。"""
        import threading
        ap = self._ap()
        if not ap:
            return
        # PortAudio 延迟加载铁律: 蓝牙未就绪时加载 DLL 会死锁 WinRT GATT 握手
        if not (self.coord and self.coord.ble_bridge.is_connected):
            self.lbl_selftest.setText("蓝牙未就绪 — 音频库暂不加载 (防死锁 GATT), 连接后重试")
            return
        self.lbl_selftest.setText("自检中: 正在播放 440Hz 测试音并录制各虚拟输入… (约 3 秒)")
        self.btn_selftest.setEnabled(False)

        def work():
            try:
                results = ap.self_test(duration_s=2.0)
            except Exception as e:
                results = [{"error": str(e)}]
            self.selftestDone.emit(results)  # 信号跨线程自动排队回 GUI 线程

        threading.Thread(target=work, daemon=True).start()

    def _on_selftest_done(self, results: list):
        self.btn_selftest.setEnabled(True)
        if results and "error" in results[0]:
            self.lbl_selftest.setText(f"自检失败: {results[0]['error']}")
            return
        if not results:
            self.lbl_selftest.setText("未发现虚拟声卡 (输入或输出端缺失) — 安装 VB-CABLE / ToDesk 虚拟声卡后重试")
            return
        parts, heard_any = [], False
        for r in results:
            mark = "听到" if r["heard"] else "无信号"
            parts.append(f"{r['name']}: {mark} ({r['db']:.0f} dB)")
            heard_any |= r["heard"]
        summary = " | ".join(parts)
        guide = ("\n结论: 在 vokie 输入设备里选上面「听到」的任意一个即可。" if heard_any
                 else "\n结论: 均无信号 — 检查虚拟声卡是否被禁用, 或被其他应用独占。")
        self.lbl_selftest.setText(summary + guide)

    def _on_asr_state(self, text, color, latency):
        self.lbl_asr.setText(f"● {text}")
        self.lbl_asr.setStyleSheet(f"font-size: 11px; color: {color}; font-weight: bold;")
        self.lbl_asr_lat.setText(f"健康检查延迟: {latency}")

    def _test_asr(self):
        """真实链路测试: 取最近归档 WAV 调 vokie 转写 (无录音则提示先录一条)"""
        import threading
        self.lbl_test_result.setText("转写测试中…")
        rec_dir = getattr(self.coord, "recordings_dir", None) if self.coord else None

        def work():
            from core import asr_client
            try:
                wav = None
                if rec_dir and os.path.isdir(rec_dir):
                    wavs = sorted(f for f in os.listdir(rec_dir) if f.endswith(".wav"))
                    if wavs:
                        wav = os.path.join(rec_dir, wavs[-1])
                if not wav:
                    self.lbl_test_result.setText("还没有归档录音 — 按语音键录一句话再测")
                    return
                t0 = time.time()
                text = asr_client.transcribe(wav, locale=self.coord.asr_locale if self.coord else "zh")
                ms = int((time.time() - t0) * 1000)
                show = text[:60] + ("…" if len(text) > 60 else "")
                self.lbl_test_result.setText(
                    f"链路通 ({ms} ms): “{show}”" if text else f"链路通 ({ms} ms), 该录音无语音内容")
            except Exception as e:
                self.lbl_test_result.setText(f"失败: {e}")

        threading.Thread(target=work, daemon=True).start()

    # ---------------- 快照刷新 ----------------

    def update_snapshot(self, s: dict):
        ble, hid = s.get("ble"), s.get("hid")
        if ble and hid:
            self.badge_conn.setText("● 链路已连接 (BLE + HID)")
            self.badge_conn.setObjectName("badge_online")
        else:
            self.badge_conn.setText("● 蓝牙重试握手中… (按遥控器任意键唤醒)")
            self.badge_conn.setObjectName("badge_warn")
        self.badge_conn.style().unpolish(self.badge_conn)
        self.badge_conn.style().polish(self.badge_conn)

        self.row_ble.set("已握手" if ble else "未连接", T.COLOR_GREEN_TEXT if ble else T.COLOR_RED)
        self.row_hid.set("拦截中" if hid else "未运行", T.COLOR_GREEN_TEXT if hid else T.ACCENT)
        if s.get("session"):
            dur = int(time.time() - getattr(self.coord, "session_start_time", time.time())) if self.coord else 0
            self.row_session.set(f"● 录音中 {dur}s · 包#{s.get('packets', 0)}", T.COLOR_GREEN_TEXT)
        else:
            self.row_session.set("空闲", T.ACCENT)

        # 按投递模式切换卡片内容: clipboard 直投 = 只关心 X6 增益
        self._apply_delivery_mode(s.get("delivery", "clipboard"))
        fanouts = s.get("output_fanouts") or []
        if fanouts:
            self.lbl_fanout.setText(f"{len(fanouts)} 路 · " + " | ".join(fanouts))
        else:
            out = s.get("output_device")
            self.lbl_fanout.setText(out or "未发现虚拟声卡")

        if s.get("delivery") == "vokie":
            self.row_output.set(f"扇出 {len(fanouts)} 路" if fanouts else "未绑定虚拟声卡",
                                T.COLOR_GREEN_TEXT if fanouts else T.ACCENT)
        else:
            self.row_output.set("无需 (直投模式)", T.TEXT_MUTED)

        self.meter_x6.set_db(s.get("x6_level_db", -60))
        self.meter_mic.set_db(s.get("mic_level_db", -60))

    def _apply_delivery_mode(self, delivery: str):
        """clipboard: 隐藏扇出/增益(麦)/混音行, 只留 X6 增益; vokie: 全量显示。"""
        vokie_mode = (delivery == "vokie")
        if self._last_delivery == delivery:
            return
        self._last_delivery = delivery
        for w in (self.w_row_fanout, self.w_row_selftest, self.w_row_st_result,
                  self.w_row_mic, self.w_row_mix):
            w.setVisible(vokie_mode)
        self.lbl_mode_note_clipboard.setVisible(not vokie_mode)
        self.lbl_mode_note_vokie.setVisible(vokie_mode)
        self.lbl_gain_x6_title.setText(
            "遥控器增益 (作用于转写音频)" if not vokie_mode else "X6 遥控器增益")
        if self.card_mix_title is not None:
            self.card_mix_title.setText(
                "录音与转写增益" if not vokie_mode else "音频扇出与混音管道")
