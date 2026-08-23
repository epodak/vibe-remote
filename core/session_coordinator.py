import asyncio
import os
import threading
import time
import wave

import numpy as np

from . import key_injector
from .audio_pipe import AudioPipe
from .ble_bridge import BLEBridge
from .device_source import arbiter as device_arbiter
from .key_mapper import KeyMapper
from .search_suppressor import SearchSuppressor
from .log import logger

VK_CONTROL = 0x11
VK_LWIN = 0x5B
VK_RMENU = 0xA5  # 右 Alt (vokie 激活键)

CLICK = "click"
HOLD = "hold"


class X6SessionCoordinator:
    """统一会话中枢: 语音键状态机 + 热键注入 + 混音路由 + 录音归档。

    交互模式 (config.VOICE_TRIGGER_MODE):
      click —— 按一下语音键开始, 再按一下结束并上屏 (默认, 对齐 vokie 听写)
      hold  —— 按住说话, 松开结束 (BLE MIC_CLOSE 权威, HID 脉冲静止兜底)

    防挂死三保险 (修复"按下后无时无刻都在录音"):
      1. BLE MIC_CLOSE (0x08) 松开信令
      2. hold 模式: HID 脉冲静止超时判定松开 (脉冲连发只在按住时出现)
      3. click 模式: MAX_SESSION_MS 上限强制结束
    """

    def __init__(self, mac_address: str,
                 hotkey_target="vokie",
                 trigger_mode=CLICK,
                 click_debounce_ms=400,
                 hold_release_timeout_ms=700,
                 max_session_ms=60000,
                 audio_output_keywords=None,
                 audio_mix_system_mic=True,
                 audio_mix_x6=True,
                 audio_x6_gain=1.0,
                 audio_mic_gain=1.0,
                 recordings_dir=None,
                 text_delivery="vokie",
                 asr_locale="zh"):
        self.mac_address = mac_address
        self.hotkey_target = hotkey_target
        self.trigger_mode = trigger_mode
        self.text_delivery = text_delivery
        self.asr_locale = asr_locale
        self.click_debounce_s = click_debounce_ms / 1000.0
        self.hold_release_timeout_s = hold_release_timeout_ms / 1000.0
        self.max_session_s = max_session_ms / 1000.0
        self.recordings_dir = recordings_dir

        self.audio_pipe = AudioPipe(
            output_keywords=audio_output_keywords,
            mix_system_mic=audio_mix_system_mic,
            mix_x6=audio_mix_x6,
            x6_gain=audio_x6_gain,
            mic_gain=audio_mic_gain)
        self.ble_bridge = BLEBridge(
            mac_address=mac_address,
            on_pcm_decoded=self._on_pcm_received,
            on_control_event=self._on_ble_control_event)
        self.key_mapper = KeyMapper()
        # 设备源仲裁: 告知遥控器 MAC —— X6 走 BLE HID, 其 Raw Input 设备路径
        # 内嵌 MAC, 据此零配置精确绑定, 原生键盘从此逐事件豁免
        self.device_arbiter = device_arbiter
        self.device_arbiter.set_expected_mac(mac_address)
        # 门控猜错时 (吞了物理键盘的键) 除了补偿重放, 还要立刻松开可能被按住的鼠标键
        self.device_arbiter.on_mispredict = self._on_source_mispredict
        self.search_suppressor = SearchSuppressor(
            on_voice_down=self._on_hid_voice_down,
            on_voice_up=self._on_hid_voice_up,
            on_key_event=self.key_mapper.handle_hook_key,
            on_intercept_toggled=self._on_intercept_toggled)

        # 状态机
        self.is_session_active = False
        self.current_session_pcm = []
        self.packet_counter = 0
        self.session_start_time = 0.0
        self._last_edge_time = 0.0   # 上一次有效按键沿 (click 去抖基准)
        self._last_pulse_time = 0.0  # 最近一次 HID 脉冲 (hold 松开判定)
        self._session_stop_time = 0.0
        self._x6_level_db = -60.0  # GUI 电平表 (dBFS)
        self.loop = None
        self._watchdog_task = None

    def _on_source_mispredict(self):
        """设备源门控猜错的兜底: 复位映射引擎持有的鼠标按住/锁定状态。"""
        try:
            self.key_mapper.release_all()
        except Exception:
            pass

    def _on_intercept_toggled(self, enabled: bool):
        """紧急逃生热键 (Ctrl+Alt+F12) 回调: 暂停拦截时必须复位鼠标残留状态。"""
        from . import text_delivery
        if not enabled:
            try:
                self.key_mapper.release_all()
            except Exception:
                pass
            text_delivery.show_hud("全局拦截已暂停", "所有按键原样透传 · Ctrl+Alt+F12 恢复",
                                   duration_ms=3000, accent="amber")
        else:
            text_delivery.show_hud("全局拦截已恢复", "X6 映射重新生效",
                                   duration_ms=2200, accent="green")

    # ================= 热键注入 =================

    def _trigger_hotkey_async(self, fn):
        """注入走线程: HID LL 钩子回调必须尽快返回, 不能被 40ms 脉冲阻塞。"""
        threading.Thread(target=fn, daemon=True).start()

    def trigger_hotkey(self):
        """会话开始: 按投递模式注入起始键 (clipboard 模式不注入任何键)。"""
        if self.text_delivery == "clipboard":
            logger.info("  🚀 [投递] clipboard 模式: 结束后自动转写并送剪贴板")
            return
        if self.hotkey_target == "vokie":
            if self.trigger_mode == HOLD:
                logger.info("  🚀 [HotKey] 按住右 Alt (vokie 按住说话)")
                self._trigger_hotkey_async(lambda: key_injector.press([VK_RMENU]))
            else:
                logger.info("  🚀 [HotKey] 脉冲右 Alt (vokie 开始录音)")
                self._trigger_hotkey_async(lambda: key_injector.pulse([VK_RMENU]))
        elif self.hotkey_target == "wechat":
            logger.info("  🚀 [HotKey] 脉冲 Ctrl+Win (微信输入法)")
            self._trigger_hotkey_async(
                lambda: key_injector.pulse([VK_CONTROL, VK_LWIN]))

    def commit_hotkey(self):
        """会话结束: 让目标应用停止并上屏。"""
        try:
            if self.text_delivery == "clipboard":
                return  # 转写与投递由 _save_wav_archive 异步链路负责
            if self.hotkey_target == "vokie":
                if self.trigger_mode == HOLD:
                    logger.info("  🛑 [HotKey] 松开右 Alt")
                    key_injector.release([VK_RMENU])
                else:
                    logger.info("  🛑 [HotKey] 脉冲右 Alt (vokie 结束并上屏)")
                    key_injector.pulse([VK_RMENU])
            # wechat: 结束由输入法自行处理, 不注入
        except Exception as e:
            logger.warning(f"  ⚠️ [HotKey] 结束注入异常: {e}")
            try:
                key_injector.release_all()
            except Exception:
                pass

    # ================= 按键状态机 =================

    def _on_hid_voice_down(self):
        # 钩子回调必须零工作量: 开麦/开音频流(约0.5s)等重活若同步跑在
        # LL 键盘钩子回调里, 会触发系统钩子超时, 之后按键全部逃逸。
        # 因此这里只把事件甩给工作线程, 立即返回。
        self.key_mapper.record_event("voice", True)
        threading.Thread(target=self._button_down, args=("hid",), daemon=True).start()

    def _on_hid_voice_up(self):
        # X6 语音键 HID 是脉冲连发, 单个 keyup 不构成任何判定 (Challenge 07)。
        # 注意: 不能用 up 事件刷新去抖基准 —— X6 固件在每次物理按下时会同时发
        # BLE MIC_CLOSE + HID down (相差~1ms), 若 up/MIC_CLOSE 先到并刷新基准,
        # 紧随的 down 会被去抖窗口吞掉 (实测 08:25 三次按键全被吞)。
        self.key_mapper.record_event("voice", False)

    def _on_ble_control_event(self, event_name: str):
        logger.debug(f"[BLE-GATT] 控制信令: {event_name}")
        if event_name == "START_SEARCH":
            # X6 固件在收到关麦指令后 ~0.8s 会回发一个 START_SEARCH (搜索结束确认)。
            # 会话结束后 1.5s 不应期内忽略 BLE-only 的 START_SEARCH，防止幽灵会话；
            # 真实物理按键总是伴随 HID 事件，不受此限。
            if time.time() - self._session_stop_time < 1.5:
                logger.debug("[BLE-GATT] 不应期内的 START_SEARCH (关麔回声), 忽略")
                return
            self._button_down("ble")
        elif event_name == "MIC_CLOSE":
            self._button_up("ble")

    def _button_down(self, source: str):
        now = time.time()
        self._last_pulse_time = now

        # 去抖基准只在 down 脉冲上刷新: 同一串脉冲(长按连发)内的 down 间隔
        # 远小于窗口, 整串算一次点击; 与上一串最后一个 down 间隔超窗 = 新点击
        if now - self._last_edge_time < self.click_debounce_s:
            self._last_edge_time = now
            return
        self._last_edge_time = now

        if self.trigger_mode == CLICK:
            if self.is_session_active:
                self._stop_voice_session(f"再按一下 → 结束录音并上屏 [源:{source}]")
            else:
                self._start_voice_session(f"按下 → 开始录音 [源:{source}]")
        else:  # HOLD
            if not self.is_session_active:
                self._start_voice_session("按住 → 开始录音")

    def _button_up(self, source: str):
        if self.trigger_mode == CLICK:
            # click 模式不因松开结束; 也不刷新去抖基准 (见 _on_hid_voice_up 注释)
            return
        if self.is_session_active:
            self._stop_voice_session(f"松开 ({source}) → 结束录音")

    async def _watchdog_loop(self):
        """防挂死: hold 脉冲静止超时 + click 会话时长上限。"""
        try:
            while True:
                await asyncio.sleep(0.15)
                if not self.is_session_active:
                    continue
                now = time.time()
                if self.trigger_mode == HOLD and now - self._last_pulse_time > self.hold_release_timeout_s:
                    logger.info("  ⏳ [看门狗] HID 脉冲静止且未收到 MIC_CLOSE, 判定已松开")
                    self._stop_voice_session("脉冲静止 → 判定松开")
                elif self.trigger_mode == CLICK and now - self.session_start_time > self.max_session_s:
                    logger.info(f"  ⏳ [看门狗] 单次录音超过 {self.max_session_s:.0f}s 上限, 强制结束")
                    self._stop_voice_session("超时保护 → 强制结束")
        except asyncio.CancelledError:
            pass

    # ================= 会话生命周期 =================

    def _start_voice_session(self, reason: str):
        self.is_session_active = True
        self.current_session_pcm = []
        self.packet_counter = 0
        self.session_start_time = time.time()
        logger.info(f"\n🎙️ [X6-Session] {reason}")
        if self.text_delivery == "clipboard":
            from . import text_delivery
            text_delivery.hud_recording()
        self.audio_pipe.start()
        self.trigger_hotkey()
        if self.ble_bridge.is_connected:
            self._schedule_ble(self.ble_bridge.open_mic())

    def _stop_voice_session(self, reason: str):
        self.is_session_active = False
        self._session_stop_time = time.time()
        logger.info(f"  🏁 [X6-Session] {reason}")
        if self.text_delivery == "clipboard":
            from . import text_delivery
            text_delivery.hud_session_stopping()  # 顶掉常驻的"录音中"胶囊
        self.commit_hotkey()
        if self.ble_bridge.is_connected:
            self._schedule_ble(self.ble_bridge.close_mic())
        self.audio_pipe.stop()
        if self.recordings_dir and self.current_session_pcm:
            pcm = list(self.current_session_pcm)
            threading.Thread(target=self._save_wav_archive, args=(pcm,), daemon=True).start()

    def _schedule_ble(self, coro):
        """从回调线程向事件循环安全投递协程 (循环已关闭时静默丢弃)。"""
        if not self.loop or self.loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(coro, self.loop)
        except RuntimeError:
            pass

    def _save_wav_archive(self, pcm_samples):
        if not pcm_samples:
            return
        ts = time.strftime("%Y%m%d_%H%M%S")
        wav_file = os.path.join(self.recordings_dir, f"vremote_voice_{ts}.wav")
        try:
            # 增益直接作用于归档/转写音频 (clipboard 模式下 ASR 读的就是这份 WAV):
            # 遥控器增益在 UI 上的调节因此真实影响识别效果; clip 防削波。
            gain = float(getattr(self.audio_pipe, "x6_gain", 1.0) or 1.0)
            arr = np.asarray(pcm_samples, dtype=np.float64)
            if abs(gain - 1.0) > 1e-6:
                arr = np.clip(arr * gain, -32768, 32767)
            pcm_bytes = arr.astype("<i2").tobytes()
            with wave.open(wav_file, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(pcm_bytes)
            peak = int(np.max(np.abs(arr)))
            rms = float(np.sqrt(np.mean(arr ** 2)))
            logger.info(f"  💾 [Audio-Archive] 已存 WAV: {os.path.basename(wav_file)} | "
                  f"采样点 {len(pcm_samples)} | 增益 ×{gain:.2f} | 峰值 {peak}/32767 | RMS {rms:.0f}")
        except Exception as e:
            logger.warning(f"  ⚠️ 归档异常: {e}")
            return
        # clipboard 投递: 归档后异步走 vokie 本地转写 -> 剪贴板+粘贴+通知
        if self.text_delivery == "clipboard":
            self._transcribe_and_deliver(wav_file)

    def _transcribe_and_deliver(self, wav_file):
        """vokie 本地 ASR -> 文本投递 (在归档线程中运行, 不阻塞主循环)。

        HUD 过程态: 转写中(跳动秒表) -> 完成(复制粘贴预览)/无语音/失败。
        """
        from . import asr_client, text_delivery
        ticker = text_delivery.TranscribeTicker()
        t0 = time.time()
        try:
            logger.info("  🧠 [ASR] vokie 本地转写中...")
            text = asr_client.transcribe(wav_file, locale=self.asr_locale)
            if not text:
                text_delivery.show_hud("未识别到语音", "录音已保留在 captured_audio/",
                                       duration_ms=2200, accent="amber")
                logger.info("  ℹ️ [ASR] 无有效文本")
                return
            self._append_transcript_history(text, (time.time() - t0) * 1000)
            text_delivery.deliver(text)
        except Exception as e:
            logger.error(f"  ❌ [ASR/投递] 失败: {e}")
            text_delivery.show_hud("转写失败", f"{e}", duration_ms=2600, accent="red")
        finally:
            ticker.stop()

    def _append_transcript_history(self, text: str, asr_ms: float):
        """转写历史追加到 transcripts.jsonl (GUI 语音回眸页实时读取)。"""
        if not self.recordings_dir:
            return
        path = os.path.join(os.path.dirname(self.recordings_dir), "transcripts.jsonl")
        try:
            import json as _json
            with open(path, "a", encoding="utf-8") as f:
                f.write(_json.dumps({
                    "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "text": text, "asr_ms": round(asr_ms), "chars": len(text),
                }, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"  ⚠️ 转写历史写入失败: {e}")

    def _on_pcm_received(self, samples: list):
        if not self.is_session_active:
            return
        self._last_pulse_time = time.time()  # 持续推流中，刷新保活基准
        self.packet_counter += 1
        self.current_session_pcm.extend(samples)
        self.audio_pipe.push_pcm(samples)
        arr = np.array(samples, dtype=np.int16)
        rms = float(np.sqrt(np.mean(arr.astype(float) ** 2)))
        # GUI 电平表: dBFS, -60dB 底 (与 macOS 版 MeterView 同刻度)
        self._x6_level_db = max(-60.0, min(0.0, 20 * np.log10(max(rms, 1e-6) / 32768)))
        if self.packet_counter % 30 == 0:
            bars = "█" * min(10, int(rms / 100)) + "░" * max(0, 10 - int(rms / 100))
            logger.info(f"  🎙️ [录音中] 包 #{self.packet_counter:03d} | 电平 [{bars}] {rms:.0f} RMS")

    # ================= UI 集成 (供 GUI 轮询, 线程安全只读快照) =================

    def ui_snapshot(self) -> dict:
        return {
            "ble": self.ble_bridge.is_connected,
            "hid": self.search_suppressor.is_running,
            "session": self.is_session_active,
            "packets": self.packet_counter,
            "delivery": self.text_delivery,
            "trigger_mode": self.trigger_mode,
            "hotkey_target": self.hotkey_target,
            "max_session_s": self.max_session_s,
            "x6_level_db": self._x6_level_db,
            "mic_level_db": self.audio_pipe.mic_level_db,
            "output_device": (self.audio_pipe.device_info or {}).get("name"),
            "output_fanouts": [f.info.get("name") for f in self.audio_pipe.fanouts],
            "mix_mic": self.audio_pipe.mix_system_mic,
            "mix_x6": self.audio_pipe.mix_x6,
            "keymap": self.key_mapper.snapshot_maps(),
            "key_events": self.key_mapper.drain_events(),
            "intercept_enabled": self.search_suppressor.intercept_enabled,
            "isolation": self.device_arbiter.snapshot(),
        }

    async def restart_ble(self):
        """GUI '重连' 按钮: 释放并重建 BLE 会话"""
        logger.info("🔄 [GUI] 手动重连蓝牙...")
        await self.ble_bridge.shutdown()
        await asyncio.sleep(0.5)
        ok = await self.ble_bridge.connect()
        logger.info(f"🔄 [GUI] 重连{'成功' if ok else '失败'}")

    # ================= 主流程 =================

    async def start(self):
        self.loop = asyncio.get_running_loop()
        mode_desc = "按一下录音/再按一下上屏" if self.trigger_mode == CLICK else "按住说话/松开结束"
        deliver_desc = "剪贴板+自动粘贴 (无需配置音频源)" if self.text_delivery == "clipboard" \
            else f"{self.hotkey_target} 原生听写 (需配置其输入设备)"
        logger.info("=" * 65)
        logger.info("       🚀 vRemote for Windows (X6 语音飞鼠全功能交互中枢)")
        logger.info(f"       交互: {self.trigger_mode} ({mode_desc})")
        logger.info(f"       投递: {self.text_delivery} — {deliver_desc}")
        logger.info("=" * 65)

        # 连接也必须纳入 try/finally: 若用户在握手期间 Ctrl+C (设备休眠时
        # 蓝牙栈可能长时间挂起)，同样要走完整清理，否则资源泄漏 + 退出崩溃
        try:
            # 1. 先启动设备源仲裁 (Raw Input), 再挂钩子 ——
            #    顺序不能反: 钩子先跑会让首批按键拿不到权威来源
            self.device_arbiter.start()
            self.search_suppressor.start()
            self._watchdog_task = asyncio.create_task(self._watchdog_loop())

            # 2. 蓝牙连接循环: X6 休眠时只有按任意键才重连，失败后提示并重试
            attempt = 0
            while True:
                attempt += 1
                logger.info(f"📡 正在直连 X6 遥控器 ({self.mac_address})... [第 {attempt} 次]")
                ok = await self.ble_bridge.connect()
                if ok:
                    logger.info("  ✅ 蓝牙 ATVV 语音通道握手成功！")
                    break
                logger.warning("  ⚠️ 未连上：遥控器多半在休眠，请按遥控器任意键唤醒，3 秒后自动重试...")
                await asyncio.sleep(3.0)

            # 3. 蓝牙就绪后才允许加载 PortAudio/绑定声卡
            try:
                self.audio_pipe.prepare()
            except Exception as e:
                logger.warning(f"  ⚠️ 虚拟声卡绑定异常: {e}")

            logger.info("-" * 65)
            logger.info("🟢 vRemote-Win 守护就绪！")
            if self.trigger_mode == CLICK:
                logger.info("👉 按一下语音键开始录音，再按一下结束并上屏 (Ctrl+C 退出)")
            else:
                logger.info("👉 按住语音键说话，松开结束 (Ctrl+C 退出)")
            logger.info("=" * 65)

            while True:
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass
        finally:
            if self._watchdog_task:
                self._watchdog_task.cancel()
            self.search_suppressor.stop()
            self.device_arbiter.stop()
            # 会话进行中被退出: 先结束会话(关麦/收尾), 再停音频
            if self.is_session_active:
                self._stop_voice_session("程序退出")
            self.audio_pipe.stop()
            # 兜底释放本模块注入的按键; 进程即将退出，再无差别复位全部修饰键
            try:
                key_injector.release_all()
                key_injector.panic_release_all_modifiers()
            except Exception:
                pass
            try:
                self.key_mapper.release_all()
            except Exception:
                pass
            try:
                await asyncio.wait_for(self.ble_bridge.shutdown(), timeout=3.0)
            except Exception as e:
                logger.warning(f"  ⚠️ [BLEBridge] 关闭异常: {e}")
            await asyncio.sleep(0.25)
            logger.info("🧹 全部资源已释放，事件循环即将关闭。")
