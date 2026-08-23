import asyncio
import struct
import uuid
from winrt.windows.devices.bluetooth import BluetoothLEDevice
from winrt.windows.devices.bluetooth.genericattributeprofile import (
    GattClientCharacteristicConfigurationDescriptorValue,
    GattCommunicationStatus
)
from winrt.windows.storage.streams import DataWriter, DataReader
from .adpcm_decoder import ADPCMDecoder
from .log import logger

UUID_SERVICE_STR = "ab5e0001-5a21-4f05-bc7d-af01f617b664"
UUID_TX_CMD_STR  = "ab5e0002-5a21-4f05-bc7d-af01f617b664"
UUID_RX_AUD_STR  = "ab5e0003-5a21-4f05-bc7d-af01f617b664"
UUID_RX_CTL_STR  = "ab5e0004-5a21-4f05-bc7d-af01f617b664"

class BLEBridge:
    """
    WinRT 原生蓝牙 BLE 通道桥接器 (对齐 macOS vRemote BLEBridge)
    极速秒级直连，解析 Google ATVV 协议信令并流式接收语音包。
    """
    def __init__(self, mac_address: str, on_pcm_decoded=None, on_control_event=None):
        self.mac_address = mac_address
        self.mac_int = int(mac_address.replace(":", ""), 16)
        self.on_pcm_decoded = on_pcm_decoded
        self.on_control_event = on_control_event
        
        self.dev = None
        self.tx_cmd = None
        self.rx_aud = None
        self.rx_ctl = None
        self._ctl_token = None
        self._aud_token = None
        # 关闭闸门: teardown 期间让 WinRT 线程池迟到的通知直接丢弃，
        # 防止回调跨生命周期悬空 (段错误 / Event loop is closed 的根因)
        self._closing = False

        self.decoder = ADPCMDecoder()
        self.atvv_version = "v04"
        self.is_connected = False
        self.is_mic_open = False
        self.keep_alive_task = None

    @staticmethod
    async def _await_op(op, timeout, name):
        """带硬超时地 await 一个 WinRT 操作，超时即放弃等待、绝不取消。

        不能用 asyncio.wait_for: 取消在途 WinRT 操作会掉进 wrap_async 的
        二段等待洞 (winrt _internals 自标 REVISIT)，设备休眠时 op.cancel()
        后事件永远不置位，wait_for 的超时形同虚设 -> connect() 无声挂死。
        放弃的僵尸操作最终完成时只是无人取结果，无副作用。
        """
        task = asyncio.ensure_future(op)
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        done, _ = await asyncio.wait({task}, timeout=timeout)
        if not done:
            logger.info(f"  ⏳ [BLEBridge] {name}: {timeout}s 内未完成 (设备不可达)")
            return False, None
        try:
            return True, task.result()
        except Exception as e:
            logger.error(f"  ❌ [BLEBridge] {name}: {e!r}")
            return False, None

    async def connect(self) -> bool:
        try:
            ok, self.dev = await self._await_op(
                BluetoothLEDevice.from_bluetooth_address_async(self.mac_int),
                timeout=4.0, name="获取蓝牙设备对象")
            if not ok or not self.dev:
                logger.error(f"  ❌ [BLEBridge] 无法获取蓝牙设备对象 ({self.mac_address})。")
                return False

            # 使用 Windows 缓存快速解析服务；设备刚唤醒时链路参数还在爬坡，
            # GATT 发现可能需要数秒，超时给足 10s (超时本身不会挂死，会走重试)
            ok, res = await self._await_op(
                self.dev.get_gatt_services_async(),
                timeout=10.0, name="GATT 服务查询")
            if not ok or res is None or res.status != GattCommunicationStatus.SUCCESS or not res.services:
                logger.error("  ❌ [BLEBridge] GATT 服务不可达 (遥控器休眠?)。")
                return False

            atvv_service = None
            for s in res.services:
                if str(s.uuid).lower().startswith("ab5e0001"):
                    atvv_service = s
                    break

            if not atvv_service:
                logger.error("  ❌ [BLEBridge] 未匹配到 ATVV 服务 (UUID: AB5E0001)。")
                return False

            ok, char_res = await self._await_op(
                atvv_service.get_characteristics_async(),
                timeout=4.0, name="特征值发现")
            if not ok or char_res is None:
                return False
            char_map = {str(c.uuid).lower(): c for c in char_res.characteristics}

            self.tx_cmd = char_map.get(UUID_TX_CMD_STR)
            self.rx_aud = char_map.get(UUID_RX_AUD_STR)
            self.rx_ctl = char_map.get(UUID_RX_CTL_STR)

            if not (self.tx_cmd and self.rx_aud and self.rx_ctl):
                logger.error("  ❌ [BLEBridge] ATVV 特征值不完整。")
                return False

            # 订阅控制与音频通知 (保存令牌，退出时必须 remove，否则回调悬空)
            self._ctl_token = self.rx_ctl.add_value_changed(self._on_control_value_changed)
            await self.rx_ctl.write_client_characteristic_configuration_descriptor_async(
                GattClientCharacteristicConfigurationDescriptorValue.NOTIFY
            )

            self._aud_token = self.rx_aud.add_value_changed(self._on_audio_value_changed)
            await self.rx_aud.write_client_characteristic_configuration_descriptor_async(
                GattClientCharacteristicConfigurationDescriptorValue.NOTIFY
            )

            # 查询 Capabilities
            writer = DataWriter()
            writer.write_bytes(bytes([0x0A, 0x00, 0x04, 0x01, 0x00]))
            await self.tx_cmd.write_value_async(writer.detach_buffer())

            self.is_connected = True
            logger.info(f"  ✅ [BLEBridge] 成功握手 X6 蓝牙遥控器 ({self.dev.name})")
            return True
        except Exception as e:
            logger.error(f"  ❌ [BLEBridge] 连接失败: {e}")
            return False

    def _on_control_value_changed(self, sender, args):
        if self._closing:
            return
        reader = DataReader.from_buffer(args.characteristic_value)
        data = bytearray(reader.unconsumed_buffer_length)
        reader.read_bytes(data)
        if not data: return

        logger.info(f"  📡 [BLE-CTL] 收到控制包: 0x{data.hex()} (len={len(data)})")
        op = data[0]
        if op == 0x0B:
            if len(data) >= 3 and data[1:3] == b'\x01\x00':
                self.atvv_version = "v10"
            else:
                self.atvv_version = "v04"
        elif op == 0x0C or (op == 0x00 and len(data) == 1):
            # 0x0C (如 0x0c010f): X6 语音键按下开麦请求; 0x00 (单字节): 标准 ATVV START_SEARCH
            logger.info(f"  🎙️ [BLE-GATT] 收到语音按键按下信令 (op=0x{op:02X})")
            if self.on_control_event:
                self.on_control_event("START_SEARCH")
        elif op in (0x08, 0x0D) or (op == 0x00 and len(data) > 1):
            # 0x08: 标准 ATVV MIC_CLOSE 关麦信令 (按键松开); 0x0000: 关麦确认回声
            logger.info(f"  🛑 [BLE-GATT] 收到语音按键松开/关麦信令 (op=0x{op:02X})")
            if self.on_control_event:
                self.on_control_event("MIC_CLOSE")
        else:
            if self.on_control_event:
                self.on_control_event(f"OP_0x{op:02X}")

    def _on_audio_value_changed(self, sender, args):
        if self._closing:
            return
        reader = DataReader.from_buffer(args.characteristic_value)
        data = bytearray(reader.unconsumed_buffer_length)
        reader.read_bytes(data)

        if len(data) >= 6:
            pred = struct.unpack(">h", data[3:5])[0]
            step_idx = min(data[5], 88)
            self.decoder.predictor = pred
            self.decoder.step_index = step_idx
            samples = [pred] + self.decoder.decode(data[6:])
        else:
            samples = self.decoder.decode(data)

        if self.on_pcm_decoded and samples:
            self.on_pcm_decoded(samples)

    def _fire_and_forget_write(self, char, data: bytes):
        """发出 GATT 写入但不等待完成。

        sounddevice (PortAudio) 加载后，WinRT 写操作的完成回调可能不再送达
        (同类死锁，实测通知与设备侧均不受影响)，因此运行期指令一律
        fire-and-forget：操作会真正到达设备，完成事件无人消费也无副作用。
        """
        if not char:
            return
        try:
            writer = DataWriter()
            writer.write_bytes(data)
            task = asyncio.ensure_future(char.write_value_async(writer.detach_buffer()))
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        except Exception as e:
            logger.warning(f"  ⚠️ [BLEBridge] 指令发送异常: {e!r}")

    async def open_mic(self):
        if not self.tx_cmd or self.is_mic_open:
            return

        self.is_mic_open = True
        open_cmd = bytes([0x0C, 0x00, 0x02]) if self.atvv_version == "v04" else bytes([0x0C, 0x00, 0x00, 0x02])
        self._fire_and_forget_write(self.tx_cmd, open_cmd)

        if not self.keep_alive_task:
            self.keep_alive_task = asyncio.create_task(self._keep_alive_loop())

    async def close_mic(self):
        if not self.tx_cmd or not self.is_mic_open:
            return

        self.is_mic_open = False
        if self.keep_alive_task:
            self.keep_alive_task.cancel()
            self.keep_alive_task = None

        self._fire_and_forget_write(self.tx_cmd, bytes([0x0D, 0x00]))

    async def _keep_alive_loop(self):
        try:
            while self.is_mic_open:
                await asyncio.sleep(2.0)
                if self.tx_cmd and self.is_mic_open:
                    self._fire_and_forget_write(self.tx_cmd, bytes([0x0A, 0x00]))
        except asyncio.CancelledError:
            pass

    async def shutdown(self):
        """事件循环关闭前必须调用：关麦 -> 退订 CCCD -> 摘除回调 -> 释放设备。

        不做这四步，WinRT C++ 线程池会在 Python 事件循环销毁后继续派发通知，
        产生跨生命周期悬空调用 (段错误) 和 run_coroutine_threadsafe 打到已关闭循环
        (RuntimeError: Event loop is closed)。
        """
        if not self.dev:
            return

        self._closing = True
        self.is_connected = False

        # 1. 关麦 (含 keep_alive 任务取消)
        try:
            await self.close_mic()
        except Exception:
            pass

        # 2. GATT 层退订 (写 CCCD = NONE)；PortAudio 已加载时完成回调可能
        #    不再送达，用硬超时兜底，失败不阻断后续释放
        for char, name in ((self.rx_ctl, "CCCD ctl"), (self.rx_aud, "CCCD aud")):
            if char:
                await self._await_op(
                    char.write_client_characteristic_configuration_descriptor_async(
                        GattClientCharacteristicConfigurationDescriptorValue.NONE),
                    timeout=2.0, name=name)

        # 3. 摘除 Python 回调 (关键：切断 C++ 线程池对 Python 闭包的引用)
        for char, token in ((self.rx_ctl, self._ctl_token), (self.rx_aud, self._aud_token)):
            try:
                if char and token is not None:
                    char.remove_value_changed(token)
            except Exception:
                pass
        self._ctl_token = None
        self._aud_token = None

        # 4. 释放 BluetoothLEDevice (IClosable)，让 Windows 释放 GATT 会话
        try:
            self.dev.close()
        except Exception:
            pass

        self.dev = None
        self.tx_cmd = None
        self.rx_aud = None
        self.rx_ctl = None
