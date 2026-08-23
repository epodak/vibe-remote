import numpy as np
import threading
import time
from .log import logger

X6_SAMPLE_RATE = 16000


class _FanOut:
    """单路虚拟声卡输出: 独立流/缓冲/采样率 (每路完整拿到全部样本)。"""

    def __init__(self, idx, info):
        self.idx = idx
        self.info = info
        self.sr = None
        self.stream = None
        self.lock = threading.Lock()
        self.x6_buf = np.zeros(0, dtype=np.int16)
        self.mic_buf = np.zeros(0, dtype=np.int16)


class AudioPipe:
    """
    混音路由管道 (对齐 macOS vRemote AudioPipe 的职责, Windows 实现):

        X6 解码音频 (16k)  ─┐
                            ├─ 混音 -> [扇出] 全部虚拟声卡输出 (VB-CABLE / ToDesk ...)
        系统默认麦克风     ─┘

    2026-08-23 扇出架构: 同时向所有匹配的虚拟声卡输出端推流 —— vokie 原生听写
    模式下无论它选了哪块虚拟声卡的配对输入都能听到遥控器音频, 消解"vokie 到底
    听哪个设备"的探测问题 (唯一盲区: vokie 被固定为物理麦克风, 由链路自检暴露)。

    ⚠️ sounddevice (PortAudio) 必须延迟加载: 实测该 DLL 一加载, 本进程内
    后续的 WinRT get_gatt_services_async 全部死锁。prepare()/start() 只允许
    在 BLE GATT 连接建立之后调用。
    """

    def __init__(self, output_keywords=None, mix_system_mic=True, mix_x6=True,
                 x6_gain=1.0, mic_gain=1.0):
        self.output_keywords = output_keywords or ["CABLE Input", "ToDesk Virtual Audio", "Virtual Audio"]
        self.mix_system_mic = mix_system_mic
        self.mix_x6 = mix_x6
        self.x6_gain = x6_gain
        self.mic_gain = mic_gain

        self._sd = None
        # 兼容旧字段 (GUI 状态显示用): 主绑定 = 扇出第一路
        self.device_idx = None
        self.device_info = None
        self.fanouts = []            # [_FanOut]

        self.mic_stream = None
        self.mic_sr = None
        self.is_running = False

        self._mic_lock = threading.Lock()
        self._mic_master = np.zeros(0, dtype=np.int16)  # 麦克风主缓冲 (分发源)
        self.mic_level_db = -60.0  # GUI 电平表 (dBFS, _mic_callback 更新)

    # ---------- 设备绑定 ----------

    def _ensure_sounddevice(self):
        if self._sd is None:
            import sounddevice as sd
            self._sd = sd
        return self._sd

    @staticmethod
    def _is_virtual_output(name: str) -> bool:
        n = name.lower()
        return ("cable" in n or "virtual audio" in n or "virtual cable" in n
                or "line 1" in n or "vb-audio" in n)

    def prepare(self):
        """BLE 握手成功后调用: 加载 PortAudio 并绑定全部虚拟声卡输出 (提前暴露绑定问题)。"""
        sd = self._ensure_sounddevice()
        devices = sd.query_devices()
        self.fanouts = []
        for i, d in enumerate(devices):
            if d.get("max_output_channels", 0) > 0 and self._is_virtual_output(d["name"]):
                self.fanouts.append(_FanOut(i, d))
        if self.fanouts:
            self.device_idx = self.fanouts[0].idx
            self.device_info = self.fanouts[0].info
            names = " | ".join(f"[{f.idx}] {f.info['name']}" for f in self.fanouts)
            logger.info(f"  🔊 [AudioPipe] 混音扇出绑定 {len(self.fanouts)} 路: {names}")
        else:
            logger.warning("  ⚠️ [AudioPipe] 未找到虚拟声卡输出, 音频路由未生效 (安装 VB-CABLE 后自动生效)")

    def _virtual_inputs(self):
        """枚举虚拟声卡的配对输入端 (链路自检/引导用)。"""
        sd = self._ensure_sounddevice()
        out = []
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0 and self._is_virtual_output(d["name"]):
                out.append((i, d))
        return out

    # ---------- 会话生命周期 ----------

    def start(self):
        if not self.fanouts:
            self.prepare()
        if self.is_running or not self.fanouts:
            return
        sd = self._ensure_sounddevice()
        try:
            for fo in self.fanouts:
                fo.sr = int(fo.info["default_samplerate"])
                fo.stream = sd.OutputStream(
                    samplerate=fo.sr, channels=1, dtype='int16',
                    device=fo.idx, blocksize=512,
                    callback=lambda outdata, frames, t, st, f=fo: self._out_callback(f, outdata, frames, t, st))
                fo.stream.start()

            if self.mix_system_mic:
                mic = sd.query_devices(kind='input')
                self.mic_sr = int(mic["default_samplerate"])
                self.mic_stream = sd.InputStream(
                    samplerate=self.mic_sr, channels=1, dtype='int16',
                    blocksize=512, callback=self._mic_callback)
                self.mic_stream.start()
                logger.info(f"  🎤 [AudioPipe] 已混入系统麦克风: {mic['name']} ({self.mic_sr}Hz)")
            self.is_running = True
            logger.info(f"  🔊 [AudioPipe] 扇出推流中 ({len(self.fanouts)} 路虚拟声卡)")
        except Exception as e:
            logger.warning(f"  ⚠️ [AudioPipe] 启动异常: {e}")
            self.stop()

    def stop(self):
        for fo in self.fanouts:
            if fo.stream:
                try:
                    fo.stream.stop()
                    fo.stream.close()
                except Exception:
                    pass
                fo.stream = None
            with fo.lock:
                fo.x6_buf = np.zeros(0, dtype=np.int16)
                fo.mic_buf = np.zeros(0, dtype=np.int16)
        if self.mic_stream:
            try:
                self.mic_stream.stop()
                self.mic_stream.close()
            except Exception:
                pass
            self.mic_stream = None
        self.is_running = False
        with self._mic_lock:
            self._mic_master = np.zeros(0, dtype=np.int16)

    # ---------- 数据面 ----------

    def push_pcm(self, samples_int16):
        """X6 解码出的 16kHz 单声道样本 (int16 列表) —— 完整复制进每一路扇出。"""
        if not samples_int16 or not self.fanouts:
            return
        arr = np.asarray(samples_int16, dtype=np.int16)
        for fo in self.fanouts:
            with fo.lock:
                fo.x6_buf = np.concatenate([fo.x6_buf, arr])

    def _mic_callback(self, indata, frames, time_info, status):
        data = indata[:, 0]
        rms = float(np.sqrt(np.mean(data.astype(np.float32) ** 2)))
        self.mic_level_db = max(-60.0, min(0.0, 20 * np.log10(max(rms, 1e-6) / 32768)))
        with self._mic_lock:
            self._mic_master = np.concatenate([self._mic_master, data.copy()])
        self._distribute_mic()

    def _distribute_mic(self):
        """把主麦克风缓冲完整复制进每路扇出 (各路独立消耗)。"""
        with self._mic_lock:
            take = self._mic_master
            self._mic_master = np.zeros(0, dtype=np.int16)
        if len(take) == 0:
            return
        for fo in self.fanouts:
            with fo.lock:
                fo.mic_buf = np.concatenate([fo.mic_buf, take])

    def _pull(self, fo: _FanOut, buf_attr: str, in_sr: int, frames: int):
        """按该路输出时钟比例取缓冲并重采样; 空路补零; 积压限幅防延迟膨胀。"""
        want_in = max(1, int(round(frames * in_sr / fo.sr)))
        maxlen = int(in_sr * 0.5)  # 最多缓存 0.5s, 超出丢弃最旧
        with fo.lock:
            buf = getattr(fo, buf_attr)
            if len(buf) > maxlen:
                buf = buf[-maxlen // 2:]
            take = buf[:want_in]
            setattr(fo, buf_attr, buf[want_in:])
        if len(take) == 0:
            return np.zeros(frames, dtype=np.float32)
        if len(take) < want_in:
            take = np.concatenate([take, np.zeros(want_in - len(take), dtype=np.int16)])
        pos = np.linspace(0, len(take) - 1, frames)
        return np.interp(pos, np.arange(len(take)), take.astype(np.float32))

    def _out_callback(self, fo: _FanOut, outdata, frames, time_info, status):
        mix = np.zeros(frames, dtype=np.float32)
        if self.mix_x6:
            mix += self._pull(fo, "x6_buf", X6_SAMPLE_RATE, frames) * self.x6_gain
        if self.mix_system_mic and self.mic_stream is not None:
            mix += self._pull(fo, "mic_buf", self.mic_sr, frames) * self.mic_gain
        np.clip(mix, -32768, 32767, out=mix)
        outdata[:, 0] = mix.astype(np.int16)

    # ---------- 链路自检 (vokie 原生模式引导) ----------

    def self_test(self, duration_s: float = 2.0) -> list:
        """向全部扇出播放测试音, 同时录制全部虚拟声卡配对输入, 返回各输入能否听到。

        返回 [{idx, name, rms, heard}] —— 告诉用户"这些输入端都能听到遥控器音频,
        在 vokie 设置里任选其一即可"; 若某输入无信号则说明该路未通。
        在调用方线程运行 (GUI 按钮请开工作线程)。
        """
        sd = self._ensure_sounddevice()
        if not self.fanouts:
            self.prepare()
        inputs = self._virtual_inputs()
        if not self.fanouts or not inputs:
            return []

        was_running = self.is_running
        if not was_running:
            self.start()
        time.sleep(0.2)

        # 440Hz 测试音 (16k 采样) 推进 X6 通道
        t = np.arange(int(X6_SAMPLE_RATE * duration_s)) / X6_SAMPLE_RATE
        tone = (np.sin(2 * np.pi * 440 * t) * 12000).astype(np.int16)

        recs = {}
        rec_lock = threading.Lock()

        def _rec_cb(idx):
            def cb(indata, frames, ti, st):
                with rec_lock:
                    recs[idx] = np.concatenate([recs[idx], indata[:, 0].copy()])
            return cb

        streams = []
        for i, d in inputs:
            recs[i] = np.zeros(0, dtype=np.int16)
            s = sd.InputStream(samplerate=int(d["default_samplerate"]), channels=1,
                               dtype="int16", device=i, blocksize=512, callback=_rec_cb(i))
            s.start()
            streams.append(s)

        for chunk_start in range(0, len(tone), 1600):
            self.push_pcm(tone[chunk_start:chunk_start + 1600].tolist())
            time.sleep(0.1)
        time.sleep(0.3)

        results = []
        for i, d in inputs:
            rms = float(np.sqrt(np.mean(recs[i].astype(np.float32) ** 2))) if len(recs[i]) else 0.0
            db = max(-60.0, min(0.0, 20 * np.log10(max(rms, 1e-6) / 32768)))
            results.append({"idx": i, "name": d["name"], "rms": rms, "db": db,
                            "heard": rms > 60.0})  # 底噪 ~0.5, 测试音 RMS ~8500
        for s in streams:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        if not was_running:
            self.stop()
        return results
