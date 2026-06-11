# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置

用法:
    pyinstaller voice-typing.spec

输出: dist/薛氏语音助手.exe
"""

import sys
from pathlib import Path

# 项目根目录
ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / 'voice_typing' / '__main__.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # 如果 VAD 模型已下载，打包进去（省去首次下载）
        (str(Path.home() / '.config' / 'voice-typing' / 'silero_vad.onnx'), '.'),
    ] if (Path.home() / '.config' / 'voice-typing' / 'silero_vad.onnx').exists() else [],
    hiddenimports=[
        'tkinter',
        'numpy',
        'sounddevice',
        'websockets',
        'pyperclip',
        'onnxruntime',
        'urllib.request',        # VAD 模型下载
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'scipy',
        'pandas',
        'PIL',
        'cv2',
        'torch',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='薛氏语音助手',                    # 可改为英文: VoiceTyping
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                         # 无控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / 'icon.ico'),           # 应用图标
)
