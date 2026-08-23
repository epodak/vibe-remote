# vibe-remote (Windows)

<p align="center">
  <b>极简、极速、低延迟的硬件遥控器驱动与语音/飞鼠控制中心</b><br>
  <i>(Ultra-low Latency Hardware Remote Controller & Voice/AirMouse Hub for Windows)</i>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6?logo=windows" alt="Platform">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/GUI-PyQt6-41CD52?logo=qt" alt="PyQt6">
  <img src="https://img.shields.io/badge/BLE-WinRT%20Native-00A4EF" alt="WinRT">
  <img src="https://img.shields.io/badge/Protocol-Google%20ATVV-orange" alt="ATVV">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License">
  <a href="README_EN.md"><img src="https://img.shields.io/badge/Language-English-lightgrey" alt="English README"></a>
</p>

---

## 📸 界面预览 (UI Showcase)

<div align="center">

### 1. 全能硬件检测工作台 (Hardware Workbench)
> 实时按键打卡矩阵 (16键物理按下即时点亮) · X6 声学实时电平表 (dBFS 真实电平) · 底层输入源隔离诊断面板
<img src="assets/screenshots/workbench.png" width="850" alt="Hardware Workbench">

<br><br>

### 2. 可视化按键映射画板 (Keymap Canvas - 正反双面)
> 正面多功能键与背面 47 键全键盘物理打卡映射 · 预设方案一键切换 (标准/3D查看器/多媒体/演示)
<table align="center">
  <tr>
    <td width="50%" align="center"><b>正面按键映射 (Front Controls)</b></td>
    <td width="50%" align="center"><b>背面全键盘映射 (Back QWERTY)</b></td>
  </tr>
  <tr>
    <td><img src="assets/screenshots/mapping_front.png" alt="Front Mapping"></td>
    <td><img src="assets/screenshots/mapping_back.png" alt="Backside Mapping"></td>
  </tr>
</table>

<br>

### 3. 音频路由、转写历史与个性化偏好
<table align="center">
  <tr>
    <td width="50%" align="center"><b>音频设备与虚拟混音路由</b></td>
    <td width="50%" align="center"><b>语音转写历史与记录回溯</b></td>
  </tr>
  <tr>
    <td><img src="assets/screenshots/audio_routing.png" alt="Audio Routing"></td>
    <td><img src="assets/screenshots/transcripts.png" alt="Transcripts"></td>
  </tr>
  <tr>
    <td width="50%" align="center"><b>全局交互与偏好设置</b></td>
    <td width="50%" align="center"><b>亮色主题工作台界面 (Light Theme)</b></td>
  </tr>
  <tr>
    <td><img src="assets/screenshots/settings.png" alt="Settings"></td>
    <td><img src="assets/screenshots/workbench_light.png" alt="Light Workbench"></td>
  </tr>
</table>

</div>

---

## 🌟 核心特性 (Features)

- 🎙️ **原生 BLE 语音流链路 (Google ATVV 协议)**
  - 基于 Windows 原生 WinRT BLE 驱动实现 GATT 服务秒级直连。
  - 内置 IMA-ADPCM 实时流式硬件解码，无缝输出 16kHz 16-bit 线性 PCM 音频，延迟低至数十毫秒。
- 🛡️ **底层硬件级输入隔离 (Raw Input Device Isolation)**
  - 彻底解决遥控器与电脑物理键盘的键码冲突痛点（如遥控器发送的按键与物理主键盘混淆）。
  - 基于 Windows `Raw Input` (WM_INPUT) + `Low-Level Keyboard Hook` (WH_KEYBOARD_LL) 实现双层精准仲裁，仅拦截并映射遥控器来源的事件，物理键盘丝毫不受影响。
- 🎛️ **实时硬件检测工作台 (Hardware Workbench)**
  - 真实按键打卡矩阵（16键物理按下即时点亮）。
  - 实时 X6 声学电平表（dBFS 真实电平，带峰值保持）。
  - 输入源仲裁诊断面板与毫秒级事件流监视。
- ⚡ **无感文本投递与语音转写 (Text Delivery)**
  - 支持 **剪贴板极速上屏 (`clipboard`)**：录音结束自动调度本地/离线 ASR 并将文本安全粘贴至当前获得焦点的窗口。
  - 支持 **虚拟音频管道 (`vokie`/虚拟声卡)**：将遥控器音频注入系统虚拟麦克风，联动各类听写软件。
- 🎨 **现代化精致拟态 UI (Fluent & Modern Design)**
  - 基于 PyQt6 打造的自适应暗色/亮色主题界面。
  - 毫秒级动态悬浮 HUD 状态指示器与轻量化系统托盘驻留。

---

## 📐 架构与工作原理 (Architecture)

```
                       [ X6 智能遥控器 / 飞鼠 ]
                                  │
         ┌────────────────────────┴────────────────────────┐
         │ (BLE GATT 语音通道)                              │ (HID 键盘/鼠标通道)
         ▼                                                 ▼
[ WinRT BLE Native Driver ]                     [ Windows Raw Input API ]
         │ (ATVV 信令交互)                                  │ (设备句柄 / VID:PID 仲裁)
         ▼                                                 ▼
 [ IMA-ADPCM 实时解码器 ]                       [ Device Source Arbiter (隔离层) ]
         │                                                 │
 16kHz 16bit PCM 流                                   遥控器按键 ───┬───► 物理键盘按键 (直接放行)
         │                                                 │
 ┌───────┴───────┐                                         ▼
 ▼               ▼                             [ Key Mapper (自定义映射) ]
[ 本地 ASR 转写 ] [ 虚拟音频混音 ]                          │
 │ (Offline ASR)  │ (Virtual Cable)                        ▼
 ▼               ▼                             [ 自动化动作 / 快捷键注入 ]
[ 剪贴板自动上屏 ] [ 第三方语音输入 ]                       │
 └───────┬───────┘                                         ▼
         ▼                                        [ Windows 桌面环境 ]
 [ 悬浮 HUD 状态通知 ]
```

---

## 📥 下载与安装 (Download & Installation)

无需配置 Python 环境，直接前往 Releases 页面获取编译好的 Windows 版本：

👉 **[前往 GitHub Releases 下载最新版本](https://github.com/epodak/vibe-remote/releases)**

| 版本类型 | 文件名 | 适用人群 / 特性 |
| :--- | :--- | :--- |
| 🌟 **标准安装向导 (推荐)** | `vibe-remote-Setup-x64.exe` | **普通用户首选**：双击一键安装，自动创建**桌面快捷方式**、**开始菜单**，可选**开机自启动**，支持 Windows 设置面板规范卸载 |
| 💼 **绿色免安装版** | `vibe-remote-windows-x64-portable.zip` | **便携/极客测试**：解压到任意目录，双击 `vibe-remote.exe` 直接运行，零系统残留 |

---

## 📦 环境要求 (Requirements)

- **操作系统**：Windows 10 (1809 及以上) / Windows 11
- **蓝牙硬件**：支持 BLE (Bluetooth Low Energy 4.0+) 的内置或外置蓝牙适配器
- **Python 版本**：Python 3.10 或更高版本

---

## 🚀 快速上手 (Quick Start)

### 1. 克隆仓库与安装依赖

```bash
git clone https://github.com/epodak/vibe-remote.git
cd vibe-remote

# 推荐在虚拟环境中安装依赖
python -m venv .venv
.\.venv\Scripts\activate

# 安装项目依赖
pip install -r requirements.txt
```

### 2. 启动控制中心

```bash
# 启动图形管理面板与后台服务
python main.py
```

> **提示**：启动后软件会自动最小化到系统托盘，右键托盘图标可打开「控制面板」或「硬件工作台」。

---

## ⚙️ 核心配置说明 (Configuration)

配置文件位于 `config.py`，你也可以直接在 UI 设置面板中进行修改：

| 配置项 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `REMOTE_MAC` | 绑定设备 MAC | 目标遥控器的蓝牙物理地址 |
| `VOICE_TRIGGER_MODE` | `"hold"` | 语音触发模式：`"hold"` (按住说话，松开结束) / `"click"` (点击开始，再次点击结束) |
| `TEXT_DELIVERY` | `"clipboard"` | 文本送达方式：`"clipboard"` (本地转写+自动粘贴) / `"vokie"` (联动虚拟麦克风) |
| `ASR_LOCALE` | `"zh"` | 离线转写语言：`"zh"` (中文) / `"en"` (英文) |
| `AUDIO_MIX_SYSTEM_MIC`| `True` | 是否将系统默认麦克风混音进虚拟声卡通道 |
| `RECORDINGS_DIR` | `./recordings` | 音频录音存档目录（支持环境变量 `VREMOTE_RECORDINGS_DIR` 自定义） |

---

## 🛠️ 模块一览 (Project Structure)

```
vibe-remote/
├── core/                       # 核心底层引擎
│   ├── ble_bridge.py           # WinRT 原生 BLE 通信与 ATVV 协议栈
│   ├── adpcm_decoder.py        # IMA-ADPCM 音频流解码算法
│   ├── device_source.py        # Windows Raw Input 硬件级输入源仲裁隔离
│   ├── search_suppressor.py    # 键盘按键与搜索弹窗智能抑制器
│   ├── session_coordinator.py  # 语音会话全局状态机协调器
│   ├── key_mapper.py           # 按键映射引擎与预设管理器
│   ├── text_delivery.py        # 剪贴板注入与焦点自动补全
│   ├── audio_pipe.py           # WASAPI / 虚拟音频路由与混音
│   └── hud_toast.py            # 毫秒级轻量悬浮 HUD 弹窗
├── ui/                         # PyQt6 现代化图形界面
│   ├── main_hub_window.py      # 主控制中心窗口
│   ├── view_hardware_workbench.py # 硬件检测工作台 (实时电平/按键矩阵)
│   ├── view_mapping.py         # 可视化按键映射配置画板
│   ├── view_audio_devices.py   # 音频设备检测与路由面板
│   └── style_theme.py          # Fluent 主题系统 (暗色/亮色自适应)
├── assets/                     # 静态资源与遥控器矢量图
├── main.py                     # 应用主入口
├── gui.py                      # GUI 独立启动入口
├── config.py                   # 全局配置中心
└── requirements.txt            # Python 依赖清单
```

---

## 🤝 参与贡献 (Contributing)

欢迎提交 Issue 和 Pull Request！如果你有新型号遥控器的协议适配需求或新的功能建议，请随时发起讨论。

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交改动 (`git commit -m 'Add some AmazingFeature'`)
4. 推送分支 (`git push origin feature/AmazingFeature`)
5. 发起 Pull Request

---

## 📄 开源协议 (License)

本项目采用 [MIT License](LICENSE) 许可证开源。
