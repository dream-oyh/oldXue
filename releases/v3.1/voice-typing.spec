# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置

用法:
    pyinstaller voice-typing.spec

输出: dist/薛老头.exe
"""

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_dynamic_libs
from PyInstaller.building.datastruct import TOC

ROOT = Path(SPECPATH)

# --- 收集 onnxruntime 原生 DLL + MSVC 运行时 ---
onnx_binaries = collect_dynamic_libs('onnxruntime')

msvc_dlls = ['vcruntime140.dll', 'msvcp140.dll', 'vcruntime140_1.dll']
for dll in msvc_dlls:
    dll_path = Path(os.environ.get('SYSTEMROOT', 'C:\\Windows')) / 'System32' / dll
    if dll_path.exists():
        onnx_binaries.append((str(dll_path), '.'))

# --- 数据文件 ---
datas = []

# VAD 模型
vad_model = (Path(os.environ.get('APPDATA', Path.home() / '.config'))
             / 'voice-typing' / 'silero_vad.onnx')
if vad_model.exists():
    datas.append((str(vad_model), '.'))

# 托盘图标
datas.append((str(ROOT / 'icon.ico'), '.'))

# SenseVoice 本地模型
sensevoice_dir = ROOT / 'asr-test' / 'models' / 'SenseVoiceSmall'
if sensevoice_dir.exists():
    for f in sensevoice_dir.iterdir():
        datas.append((str(f), 'SenseVoiceSmall'))

# --- 隐藏导入 ---
hiddenimports = [
    'tkinter',
    'numpy',
    'sounddevice',
    'websockets',
    'urllib.request',
    'onnxruntime',
    'onnxruntime.capi',
]

# --- 排除项 ---
excludes = [
    'matplotlib', 'scipy', 'pandas', 'PIL', 'cv2', 'torch',
]

a = Analysis(
    [str(ROOT / 'voice_typing' / '__main__.py')],
    pathex=[str(ROOT)],
    binaries=onnx_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# 排除 sherpa-onnx 自带的 onnxruntime.dll，统一使用 pip 安装版
# 两个不同版本的 DLL 共存会导致 InferenceSession 初始化失败
a.binaries = TOC([
    (n, p, t) for (n, p, t) in a.binaries
    if not (n.lower() == 'onnxruntime.dll' and 'sherpa_onnx' in str(p).lower())
])

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='薛老头',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / 'icon.ico'),
)
