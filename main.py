import asyncio
import sys
import os
import threading

# 开启标准输出即时刷新 (防止 Windows 终端缓存导致的视觉卡顿)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)

# 将当前目录加入 Python 寻包路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _install_benign_race_filter():
    """过滤 winrt wrap_async 的一个已知收尾竞态 (不影响其它异常)。

    蓝牙栈挂起时，被取消的 IAsyncOperation 可能在事件循环关闭后才完成，
    winrt 的 on_complete 会向已关闭循环 call_soon_threadsafe 并在线程池线程
    抛 RuntimeError: Event loop is closed。此错误在清理完成后发生、无副作用，
    仅产生吓人的 traceback。这里精确匹配该消息并静默，其余异常照常打印。
    """
    _orig = threading.excepthook

    def _hook(args):
        if args.exc_type is RuntimeError and "Event loop is closed" in str(args.exc_value):
            tb = args.exc_traceback
            if tb is not None and "winrt" in tb.tb_frame.f_code.co_filename:
                return
        _orig(args)

    threading.excepthook = _hook


from config import (
    REMOTE_MAC,
    VOICE_TRIGGER_HOTKEY,
    VOICE_TRIGGER_MODE,
    CLICK_DEBOUNCE_MS,
    HOLD_RELEASE_TIMEOUT_MS,
    MAX_SESSION_MS,
    AUDIO_OUTPUT_KEYWORDS,
    AUDIO_MIX_SYSTEM_MIC,
    AUDIO_MIX_X6,
    AUDIO_X6_GAIN,
    AUDIO_MIC_GAIN,
    TEXT_DELIVERY,
    ASR_LOCALE,
    RECORDINGS_DIR
)
from core.session_coordinator import X6SessionCoordinator
from core.log import logger
from core import single_instance, user_settings

async def async_main():
    coordinator = X6SessionCoordinator(
        mac_address=REMOTE_MAC,
        hotkey_target=VOICE_TRIGGER_HOTKEY,
        trigger_mode=VOICE_TRIGGER_MODE,
        click_debounce_ms=CLICK_DEBOUNCE_MS,
        hold_release_timeout_ms=HOLD_RELEASE_TIMEOUT_MS,
        max_session_ms=MAX_SESSION_MS,
        audio_output_keywords=AUDIO_OUTPUT_KEYWORDS,
        audio_mix_system_mic=AUDIO_MIX_SYSTEM_MIC,
        audio_mix_x6=AUDIO_MIX_X6,
        audio_x6_gain=AUDIO_X6_GAIN,
        audio_mic_gain=AUDIO_MIC_GAIN,
        text_delivery=TEXT_DELIVERY,
        asr_locale=ASR_LOCALE,
        recordings_dir=RECORDINGS_DIR
    )
    # config.py 是静态默认; GUI 里保存过的偏好优先 (两个入口保持一致的行为)
    user_settings.apply_to_coordinator(coordinator)
    await coordinator.start()

def main():
    _install_benign_race_filter()
    holder = single_instance.acquire()
    if holder:
        logger.error(f"❌ 已有 vRemote 实例在运行 (PID {holder})。"
                     "同时运行两个实例会互相抢占 X6 蓝牙 (GATT ProtocolError)。"
                     "请先结束旧实例 (taskkill /F /PID "
                     f"{holder}) 或删除 .vremote.lock 后重试。")
        sys.exit(1)
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        logger.info("\n⏹️ vRemote-Win 已正常退出。")
    finally:
        single_instance.release()

if __name__ == "__main__":
    main()
