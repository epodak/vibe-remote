import os

# ============================================================
# vRemote 配置 —— 单一事实来源 (跨平台: 状态机只读本文件, 平台差异
# 隔离在 key_injector / ble_bridge / audio_pipe 三个平台实现里)
# ============================================================

# ---------- X6 硬件 ----------
REMOTE_MAC = "B0:EF:D7:8B:56:AC"
REMOTE_NAME = "X6-Remote"

# ---------- 交互模式 (决定语音键状态机) ----------
# 'hold'  : 按住说话, 松开结束。【默认, 推荐】符合物理遥控器直觉 (PTT 对讲机模型)
#           松开判定优先用 BLE MIC_CLOSE 信令, HID 脉冲静止超过 HOLD_RELEASE_TIMEOUT_MS 时兜底
# 'click' : 按一下语音键开始录音，再按一下结束并上屏
VOICE_TRIGGER_MODE = "hold"

# click 模式: 脉冲串内的重复按下(含 HID 与 BLE 同时到达)视为同一次点击
CLICK_DEBOUNCE_MS = 400

# hold 模式: HID 脉冲静止超过该值判定松开 (毫秒)
HOLD_RELEASE_TIMEOUT_MS = 700

# click 模式单次录音上限 (毫秒), 防挂死
MAX_SESSION_MS = 60000

# ---------- 文本投递 (语音 -> 文字的送达方式) ----------
# 'clipboard' : 【默认, 推荐】会话结束 -> 调 vokie 本地转写 API (/v1/asr/offline2pass)
#               -> 文本入剪贴板 + 尝试 Ctrl+V 粘贴 + 气泡通知。
#               完全不依赖音频源设置 (无需虚拟声卡/无需选 vokie 输入设备/无需右Alt),
#               焦点不可输入时文本保留在剪贴板并提示, 永不丢失。
# 'vokie'     : 右Alt 驱动 vokie 原生听写 UI —— 需把 vokie 输入设备选成
#               麦克风 (ToDesk Virtual Audio) (或系统"默认通信设备"指向它)
TEXT_DELIVERY = "clipboard"

ASR_LOCALE = "zh"   # vokie 转写语言: zh | en

# ---------- 热键目标 (仅 TEXT_DELIVERY='vokie' 时生效) ----------
# 'vokie' : 右 Alt   —— click=起止各脉冲一次; hold=按下/松开
# 'wechat': Ctrl+Win —— 仅 click 语义(开始时脉冲一次); 需微信输入法已激活才响应
VOICE_TRIGGER_HOTKEY = "vokie"

# ---------- 音频路由 ----------
# 混音架构: X6解码音频(16k) + 系统默认麦克风 -> 虚拟声卡输出
# 目标应用(vokie等)把输入设备选成虚拟声卡的配对输入(如 麦克风 (ToDesk Virtual Audio))
# 即可同时听到本地麦克风与遥控器传来的声音
AUDIO_OUTPUT_KEYWORDS = [
    "CABLE Input",           # VB-Audio Virtual Cable (标准首选)
    "ToDesk Virtual Audio",  # 本机已装
    "Virtual Audio",
    "Line 1",
]
AUDIO_MIX_SYSTEM_MIC = True   # 混入系统默认麦克风 (False=虚拟声卡里只有 X6 音频)
AUDIO_MIX_X6 = True           # 推 X6 音频 (调试对比时可关)
AUDIO_X6_GAIN = 1.0           # X6 支路增益
AUDIO_MIC_GAIN = 1.0          # 本地麦克风支路增益

# ---------- 录音归档 ----------
RECORDINGS_DIR = os.environ.get(
    "VREMOTE_RECORDINGS_DIR",
    os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "recordings"))
)
os.makedirs(RECORDINGS_DIR, exist_ok=True)
