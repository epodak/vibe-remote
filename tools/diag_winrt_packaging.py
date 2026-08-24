# -*- coding: utf-8 -*-
"""diag_winrt_packaging.py - 诊断 winrt 投影包在 site-packages 的真实布局 (panorama 探针)"""
import importlib.util
import os
import sys

print("python:", sys.version)
spec = importlib.util.find_spec("winrt")
if spec is None:
    print("winrt NOT FOUND")
    sys.exit(1)

roots = list(spec.submodule_search_locations or [])
print("winrt search locations:", roots)

site = os.path.dirname(roots[0])
print("site-packages:", site)
for d in sorted(os.listdir(site)):
    if d.lower().startswith("winrt"):
        full = os.path.join(site, d)
        kind = "DIR " if os.path.isdir(full) else "FILE"
        print(f"  {kind} {d}")

print()
modules = [
    "winrt.windows.devices.bluetooth",
    "winrt.windows.devices.bluetooth.genericattributeprofile",
    "winrt.windows.devices.bluetooth.advertisement",
    "winrt.windows.devices.enumeration",
    "winrt.windows.devices.radios",
    "winrt.windows.storage.streams",
    "winrt.windows.foundation",
    "winrt.windows.foundation.collections",
]
for m in modules:
    s = importlib.util.find_spec(m)
    origin = getattr(s, "origin", None) if s else None
    print(f"  {'OK ' if s else 'MISS'} {m}")
    if origin:
        print(f"       {origin}")

# 关键: 列出每个 winrt* 目录里的 pyd / py 顶层内容
print()
for d in sorted(os.listdir(site)):
    if d.lower().startswith("winrt") and os.path.isdir(os.path.join(site, d)):
        entries = sorted(os.listdir(os.path.join(site, d)))
        print(f"{d}: {entries[:12]}")
