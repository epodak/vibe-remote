# vibe-remote (Windows)

<p align="center">
  <b>Ultra-low Latency Hardware Remote Controller & Voice/AirMouse Control Center for Windows</b><br>
  <i>Empowering X6 and BLE ATVV-compatible hardware remotes with sub-millisecond input isolation and native audio streaming.</i>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6?logo=windows" alt="Platform">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/GUI-PyQt6-41CD52?logo=qt" alt="PyQt6">
  <img src="https://img.shields.io/badge/BLE-WinRT%20Native-00A4EF" alt="WinRT">
  <img src="https://img.shields.io/badge/Protocol-Google%20ATVV-orange" alt="ATVV">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License">
  <a href="README.md"><img src="https://img.shields.io/badge/Language-中文说明-red" alt="Chinese README"></a>
</p>

---

## 🌟 Key Features

- 🎙️ **Native BLE Voice Streaming (Google ATVV Protocol)**
  - Direct GATT connection via Windows native WinRT BLE APIs.
  - Integrated real-time IMA-ADPCM streaming decoder converting compressed audio to 16kHz 16-bit linear PCM with sub-frame latency.
- 🛡️ **Hardware-level Input Isolation (Windows Raw Input)**
  - Solves key code collisions between external remotes and the host physical keyboard.
  - Utilizes Windows `Raw Input` (WM_INPUT) and `Low-Level Keyboard Hook` (WH_KEYBOARD_LL) to intercept and remap key events specifically originating from the remote device without polluting the native keyboard.
- 🎛️ **Real-time Hardware Workbench**
  - Instant 16-key matrix matrix hit visualizer.
  - Real-time acoustic VU meter (dBFS peak meter) for incoming mic audio.
  - Live arbitration diagnostic card and event stream monitor.
- ⚡ **Seamless Text Delivery & Dictation Integration**
  - **Clipboard Instant Paste (`clipboard`)**: Automatically transcribes voice via offline/local ASR and pastes text directly into active windows.
  - **Virtual Audio Pipeline (`vokie` / Virtual Cable)**: Feeds decoded audio into virtual microphones for compatibility with third-party voice input engines.
- 🎨 **Modern Fluent UI**
  - Adaptive Dark/Light UI built with PyQt6.
  - Non-intrusive floating HUD notifications and system tray management.

---

## 📐 Architecture & Flow

```
                      [ X6 Smart Remote / AirMouse ]
                                     │
         ┌───────────────────────────┴───────────────────────────┐
         │ (BLE GATT Audio Stream)                               │ (HID Keyboard/Mouse Stream)
         ▼                                                       ▼
[ WinRT BLE Native Driver ]                            [ Windows Raw Input API ]
         │ (ATVV Protocol Handshake)                             │ (Device Handle / VID:PID Matching)
         ▼                                                       ▼
 [ Real-time IMA-ADPCM Decoder ]                       [ Device Source Arbiter (Isolation Layer) ]
         │                                                       │
 16kHz 16-bit Linear PCM Stream                             Remote Keys ────┬───► Physical Keyboard (Direct Passthrough)
         │                                                       │
 ┌───────┴───────┐                                               ▼
 ▼               ▼                                   [ Key Mapper Engine (Custom Bindings) ]
[ Local Offline ] [ Virtual Audio Mixing ]                       │
[  ASR Engine   ] [ (Virtual Cable Out)  ]                       ▼
 │               │                                   [ Automation Actions / Keystroke Injection ]
 ▼               ▼                                               │
[ Auto Paste ]   [ 3rd-party Dictation ]                         ▼
 └───────┬───────┘                                     [ Windows Desktop Applications ]
         ▼
 [ Floating HUD Toast ]
```

---

## 📥 Download & Installation (Zero Setup)

No Python configuration required. Grab the pre-built Windows releases directly from GitHub:

👉 **[Go to GitHub Releases](https://github.com/epodak/vibe-remote/releases)**

| Package Type | File | Details |
| :--- | :--- | :--- |
| 🌟 **Setup Wizard (Recommended)** | `vibe-remote-Setup-x64.exe` | **Standard Windows Installer**: Double-click setup wizard, auto-creates **Desktop shortcut**, **Start Menu items**, optional **Auto-start on boot**, clean Control Panel uninstaller |
| 💼 **Portable Bundle** | `vibe-remote-windows-x64-portable.zip` | **Zero Installation**: Extract to any folder, run `vibe-remote.exe` directly |

---

## 📦 Requirements

- **Operating System**: Windows 10 (1809+) or Windows 11
- **Bluetooth Hardware**: Built-in or external BLE 4.0+ adapter
- **Python Runtime**: Python 3.10 or higher

---

## 🚀 Quick Start

### 1. Clone & Install Dependencies

```bash
git clone https://github.com/epodak/vibe-remote.git
cd vibe-remote

# Create virtual environment
python -m venv .venv
.\.venv\Scripts\activate

# Install requirements
pip install -r requirements.txt
```

### 2. Launch vibe-remote

```bash
python main.py
```

> **Tip**: Upon startup, the application minimizes to the system tray. Right-click the tray icon to open the Control Panel or Hardware Workbench.

---

## ⚙️ Configuration Reference (`config.py`)

| Key | Default | Description |
| :--- | :--- | :--- |
| `REMOTE_MAC` | Bound MAC | Bluetooth physical address of the remote controller |
| `VOICE_TRIGGER_MODE` | `"hold"` | Trigger mode: `"hold"` (Push-to-Talk) / `"click"` (Toggle click-to-start / click-to-stop) |
| `TEXT_DELIVERY` | `"clipboard"` | Delivery mechanism: `"clipboard"` (Local ASR + Ctrl+V) / `"vokie"` (Virtual mic routing) |
| `ASR_LOCALE` | `"zh"` | Transcription language: `"zh"` (Chinese) / `"en"` (English) |
| `AUDIO_MIX_SYSTEM_MIC`| `True` | Mix default system microphone with remote audio in virtual cable |
| `RECORDINGS_DIR` | `./recordings` | Directory for audio archives (overridable via `VREMOTE_RECORDINGS_DIR`) |

---

## 🛠️ Project Structure

```
vibe-remote/
├── core/                       # Core engine
│   ├── ble_bridge.py           # WinRT BLE & Google ATVV protocol implementation
│   ├── adpcm_decoder.py        # IMA-ADPCM streaming audio decoder
│   ├── device_source.py        # Raw Input hardware isolation & device arbitration
│   ├── search_suppressor.py    # Keystroke & search popup suppression engine
│   ├── session_coordinator.py  # Voice session state machine coordinator
│   ├── key_mapper.py           # Key mapping engine and profile manager
│   ├── text_delivery.py        # Clipboard injection & focus management
│   ├── audio_pipe.py           # WASAPI / Virtual Audio routing & mixing
│   └── hud_toast.py            # Floating HUD toast notification window
├── ui/                         # PyQt6 modern interface
│   ├── main_hub_window.py      # Main Hub window
│   ├── view_hardware_workbench.py # Hardware workbench (Acoustic level, key matrix)
│   ├── view_mapping.py         # Visual keymapping canvas
│   ├── view_audio_devices.py   # Audio device router
│   └── style_theme.py          # Adaptive theme system (Dark/Light)
├── assets/                     # Vector graphics & remote diagrams
├── main.py                     # Main application entry point
├── gui.py                      # Standalone GUI launcher
├── config.py                   # Centralized configuration
└── requirements.txt            # Python dependencies
```

---

## 🤝 Contributing

Contributions, issues, and feature requests are welcome! Feel free to check the issues page.

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📄 License

Distributed under the [MIT License](LICENSE).
