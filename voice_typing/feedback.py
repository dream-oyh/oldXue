"""
用户反馈模块：提示音 + 托盘图标。

提示音：MessageBeep（系统声卡，零文件依赖）
托盘图标：从 icon.ico 加载（和 exe 图标同一文件）
"""

import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path

# ---------------------------------------------------------------------------
# MessageBeep 提示音
# ---------------------------------------------------------------------------

MB_OK = 0x00000000
MB_ICONERROR = 0x00000010
MB_ICONWARNING = 0x00000030


def beep_error():
    ctypes.windll.user32.MessageBeep(MB_ICONERROR)


# ---------------------------------------------------------------------------
# 图标查找路径
# ---------------------------------------------------------------------------

def _find_icon_path() -> Path:
    """查找 icon.ico，兼容开发模式和 PyInstaller 打包。"""
    # 1. 环境变量覆盖
    env = os.environ.get("VOICE_TYPING_ICON", "")
    if env:
        return Path(env)
    # 2. PyInstaller 打包后
    if getattr(sys, "frozen", False):
        bundled = Path(sys._MEIPASS) / "icon.ico"
        if bundled.exists():
            return bundled
        exe_dir = Path(sys.executable).parent / "icon.ico"
        if exe_dir.exists():
            return exe_dir
    # 3. 开发模式：voice_typing/ 的父目录
    dev = Path(__file__).parent.parent / "icon.ico"
    if dev.exists():
        return dev
    raise FileNotFoundError("icon.ico 未找到，请将图标文件放在可执行文件同目录")


# ---------------------------------------------------------------------------
# 托盘图标：从 icon.ico 加载
# ---------------------------------------------------------------------------

# Win32 常量
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
LR_DEFAULTSIZE = 0x00000040


def load_icon() -> int:
    """
    从 icon.ico 文件加载 HICON 句柄（16x16，适合托盘）。
    调用方负责 DestroyIcon(hIcon)。
    """
    path = str(_find_icon_path())
    hicon = ctypes.windll.user32.LoadImageW(
        None,                       # hInst (NULL = from file)
        path,                       # 文件路径
        IMAGE_ICON,                 # 类型
        16, 16,                     # cxDesired, cyDesired
        LR_LOADFROMFILE | LR_DEFAULTSIZE,
    )
    if not hicon:
        # 回退：尝试不指定尺寸
        hicon = ctypes.windll.user32.LoadImageW(
            None, path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE,
        )
    if not hicon:
        raise RuntimeError(f"无法加载图标: {path}")
    return hicon
