"""
文字输出模块：剪贴板 + SendInput Ctrl+V。

路线：
1. 保存剪贴板当前内容
2. 识别文本写入剪贴板
3. SendInput 模拟 Ctrl+V
4. 检测粘贴是否成功
5. 恢复原剪贴板（不覆盖用户同期复制的内容）
"""

import ctypes
import time
from ctypes import wintypes

import pyperclip

# ---------------------------------------------------------------------------
# Win32 SendInput 常量
# ---------------------------------------------------------------------------

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

VK_CONTROL = 0x11
VK_V = 0x56


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", _KEYBDINPUT),
        ("mi", _MOUSEINPUT),
    ]


class _INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", _INPUT_UNION),
    ]


def _make_kb_input(vk: int, flags: int) -> _INPUT:
    inp = _INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = vk
    inp.union.ki.dwFlags = flags
    return inp


def _send_ctrl_v():
    """用 SendInput 模拟一次 Ctrl+V。"""
    inputs = (_INPUT * 4)()
    inputs[0] = _make_kb_input(VK_CONTROL, 0)                       # Ctrl 按下
    inputs[1] = _make_kb_input(VK_V, 0)                             # V 按下
    inputs[2] = _make_kb_input(VK_V, KEYEVENTF_KEYUP)               # V 松开
    inputs[3] = _make_kb_input(VK_CONTROL, KEYEVENTF_KEYUP)         # Ctrl 松开
    ctypes.windll.user32.SendInput(4, inputs, ctypes.sizeof(_INPUT))


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def paste_text(text: str) -> None:
    """将文本通过剪贴板 Ctrl+V 粘贴到当前光标位置。"""
    if not text:
        return

    # 1. 保存当前剪贴板
    try:
        old = pyperclip.paste()
    except Exception:
        old = ""

    # 2. 写入文本
    pyperclip.copy(text)
    time.sleep(0.05)

    # 3. 模拟 Ctrl+V
    _send_ctrl_v()
    time.sleep(0.15)  # 等目标应用完成粘贴

    # 4. 恢复原剪贴板
    #    注意：无法可靠判断"粘贴成功还是失败"（剪贴板不变），
    #    正常窗口下粘贴总能成功，管理员窗口留文本在剪贴板 + 托盘提示。
    try:
        pyperclip.copy(old)
    except Exception:
        pass