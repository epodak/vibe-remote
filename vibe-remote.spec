# -*- mode: python ; coding: utf-8 -*-

import os
import sys

block_cipher = None

# 收集项目静态资源与数据文件
added_files = [
    ('assets', 'assets'),
    ('keymap.example.json', '.'),
]

# 显式声明动态加载或 C-Extension 模块
hidden_imports = [
    'winrt.windows.devices.bluetooth',
    'winrt.windows.devices.bluetooth.genericattributeprofile',
    'winrt.windows.storage.streams',
    'winrt.windows.foundation',
    'winrt.windows.foundation.collections',
    'winrt.windows.devices.enumeration',
    'loguru',
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'numpy',
]

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy', 'pandas', 'unittest', 'IPython', 'notebook'],
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
