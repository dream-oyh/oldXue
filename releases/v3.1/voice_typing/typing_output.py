"""
文字输出模块：标准模式（Unicode 注入）+ 兼容模式（剪贴板粘贴）。

标准模式使用 SendInput + KEYEVENTF_UNICODE，每批少量字符 +
批间延迟，避免 CEF/Electron 应用（微信）的事件管线溢出导致吞字、双标点。

兼容模式使用 GetClipboardSequenceNumber 检测粘贴是否被目标消费，
全程不读用户剪贴板原有内容，安全 + 可靠。
"""

import ctypes
import time
from ctypes import wintypes

# ---------------------------------------------------------------------------
# Win32 常量
# ---------------------------------------------------------------------------

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

VK_CONTROL = 0x11
VK_V = 0x56

# Unicode 注入参数
UNICODE_BATCH_SIZE = 6        # 每批字符数（CEF 事件管线友好）
UNICODE_BATCH_DELAY = 0.025   # 批间延迟（秒），给 blink 事件循环喘息

# ---------------------------------------------------------------------------
# SendInput 结构体（64-bit 兼容）
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _make_unicode_input(ch: str, keyup: bool = False) -> _INPUT:
    """构造 KEYEVENTF_UNICODE 按键事件。wVk=0 表示 Unicode 模式。"""
    inp = _INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = 0
    inp.union.ki.wScan = ord(ch)
    inp.union.ki.dwFlags = KEYEVENTF_UNICODE
    if keyup:
        inp.union.ki.dwFlags |= KEYEVENTF_KEYUP
    return inp


def _make_kb_input(vk: int, flags: int = 0) -> _INPUT:
    """构造普通虚拟键事件。"""
    inp = _INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = vk
    inp.union.ki.dwFlags = flags
    return inp


def _send_ctrl_v():
    """用 SendInput 模拟 Ctrl 按下 + V 按下/松开 + Ctrl 松开。"""
    inputs = (_INPUT * 4)()
    inputs[0] = _make_kb_input(VK_CONTROL, 0)
    inputs[1] = _make_kb_input(VK_V, 0)
    inputs[2] = _make_kb_input(VK_V, KEYEVENTF_KEYUP)
    inputs[3] = _make_kb_input(VK_CONTROL, KEYEVENTF_KEYUP)
    ctypes.windll.user32.SendInput(4, inputs, ctypes.sizeof(_INPUT))


# ---------------------------------------------------------------------------
# 方案 A：Unicode 分批注入
# ---------------------------------------------------------------------------

def paste_text_unicode(text: str) -> None:
    """
    KEYEVENTF_UNICODE 逐字注入，每批 UNICODE_BATCH_SIZE 个字符，
    批间延迟 UNICODE_BATCH_DELAY 秒。

    不分批的问题：微信 PC 版（CEF/Chromium）的事件管线在收到大量
    WM_CHAR 时会出现事件溢出（吞字）和重复处理（双标点）。
    分批 + 延迟给 blink 事件循环足够的喘息时间逐批处理。
    """
    if not text:
        return

    total = len(text)
    for start in range(0, total, UNICODE_BATCH_SIZE):
        batch = text[start : start + UNICODE_BATCH_SIZE]
        n = len(batch)

        # 构造本批所有 keydown + keyup 事件
        inputs = (_INPUT * (n * 2))()
        for i, ch in enumerate(batch):
            inputs[i * 2] = _make_unicode_input(ch, False)
            inputs[i * 2 + 1] = _make_unicode_input(ch, True)

        ctypes.windll.user32.SendInput(n * 2, inputs, ctypes.sizeof(_INPUT))

        # 批次间延迟（最后一批不需要）
        if start + UNICODE_BATCH_SIZE < total:
            time.sleep(UNICODE_BATCH_DELAY)


# ---------------------------------------------------------------------------
# 方案 B：剪贴板粘贴（序列号检测，不读用户剪贴板内容）
# ---------------------------------------------------------------------------

def paste_text_clipboard(text: str) -> bool:
    """
    通过剪贴板 + Ctrl+V 粘贴文字。

    使用 GetClipboardSequenceNumber() 追踪粘贴是否被目标应用消费，
    全程不读剪贴板原有内容。

    返回:
        True  — 粘贴被目标应用消费（序列号有额外变化）
        False — 粘贴可能失败（序列号仅 +1，即只有我们写入剪贴板的操作）
    """
    if not text:
        return True

    try:
        import pyperclip
    except ImportError:
        # 没有 pyperclip 时退化到 Unicode 注入
        paste_text_unicode(text)
        return True

    seq_before = ctypes.windll.user32.GetClipboardSequenceNumber()

    pyperclip.copy(text)
    time.sleep(0.03)  # 等剪贴板就绪

    _send_ctrl_v()
    time.sleep(0.15)  # 等目标应用处理粘贴

    seq_after = ctypes.windll.user32.GetClipboardSequenceNumber()

    # 序列号分析：
    #   seq_after == seq_before + 1 → 只有我们的 pyperclip.copy() 动了剪贴板
    #                                目标应用没有消费（管理员窗口等）
    #   seq_after > seq_before + 1  → 目标应用消费了粘贴，触发了额外剪贴板操作
    success = seq_after > seq_before + 1
    return success


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def paste_text(text: str, method: str = "unicode") -> None:
    """
    将识别文本输出到当前光标位置。

    method:
        "unicode"   — Unicode 分批注入（默认，不碰剪贴板，CEF 友好）
        "clipboard" — 剪贴板 Ctrl+V 粘贴（100% 兼容，可在设置中切换）
    """
    if not text:
        return

    if method == "clipboard":
        paste_text_clipboard(text)
    else:
        paste_text_unicode(text)