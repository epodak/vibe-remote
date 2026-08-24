# -*- mode: python ; coding: utf-8 -*-

import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# 收集项目静态资源与数据文件
added_files = [
    ('assets', 'assets'),
    ('keymap.example.json', '.'),
]

# 完整收集 winrt 及其所有 C-Extension pyd / DLL / 子包
winrt_datas, winrt_binaries, winrt_hidden = collect_all('winrt')

# collect_all 漏掉了 winrt/ 下的 .pyd C 扩展文件（namespace package 缺陷）
# 显式收集所有 .pyd 文件到 winrt/ 目录
import glob as _glob
winrt_pyd_dir = os.path.join(sys.prefix, "Lib", "site-packages", "winrt")
for _pyd in _glob.glob(os.path.join(winrt_pyd_dir, "*.pyd")):
    winrt_binaries.append((_pyd, "winrt"))

# 自动处理 Conda/Miniforge 环境下的 DLL (OpenBLAS, MKL, FFI 等)
conda_lib_bin = os.path.join(sys.prefix, "Library", "bin")
conda_binaries = []
pathex_dirs = ['.']
if os.path.exists(conda_lib_bin):
    pathex_dirs.append(conda_lib_bin)
    for dll_name in os.listdir(conda_lib_bin):
        if dll_name.lower().endswith(".dll") and any(k in dll_name.lower() for k in ["blas", "lapack", "openblas", "mkl", "ffi", "lzma", "bz2"]):
            conda_binaries.append((os.path.join(conda_lib_bin, dll_name), "."))

# 显式声明动态加载或 C-Extension 模块
# PyWinRT 3.x 是 PEP420 命名空间包: 每个投影 API 是独立安装的顶层模块,
# 静态分析对它不可靠 —— 这里按 site-packages 实际安装的轮子逐一点名兜底。
# 轮子清单自检探针: tools/diag_winrt_packaging.py (panorama L6.frozen-env)
winrt_projection_modules = [
    'winrt',
    'winrt.runtime',
    'winrt.system',
    'winrt.windows.foundation',
    'winrt.windows.foundation.collections',
    'winrt.windows.storage.streams',
    'winrt.windows.devices.bluetooth',
    'winrt.windows.devices.bluetooth.advertisement',
    'winrt.windows.devices.bluetooth.genericattributeprofile',
    'winrt.windows.devices.enumeration',
    'winrt.windows.devices.radios',
]

hidden_imports = [
    'loguru',
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'numpy',
] + winrt_hidden + collect_submodules('winrt') + winrt_projection_modules

all_datas = added_files + winrt_datas
all_binaries = winrt_binaries + conda_binaries

a = Analysis(
    ['gui.py'],
    pathex=pathex_dirs,
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PySide2', 'PySide6', 'tkinter', 'matplotlib', 'scipy', 'pandas', 'unittest', 'IPython', 'notebook'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='vibe-remote',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False, # 无控制台黑色窗口 (GUI 应用)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='assets/icon.ico', # 若有 ico 可在此指定
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='vibe-remote',
)
