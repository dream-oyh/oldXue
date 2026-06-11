"""
用户反馈模块：提示音 + 托盘图标生成。

提示音：MessageBeep（系统声卡，零文件依赖）
托盘图标：内存动态生成 .ico（16x16 纯色方块，零文件依赖）
"""

import ctypes
import struct
from ctypes import wintypes

# ---------------------------------------------------------------------------
# MessageBeep 提示音
# ---------------------------------------------------------------------------

MB_OK = 0x00000000
MB_ICONERROR = 0x00000010
MB_ICONWARNING = 0x00000030
MB_ICONINFORMATION = 0x00000040


def beep_start():
    """开始录音提示音。"""
    ctypes.windll.user32.MessageBeep(MB_OK)


def beep_stop():
    """结束录音提示音。"""
    ctypes.windll.user32.MessageBeep(MB_OK)


def beep_warning():
    """警告提示音（快到 60s / 错误）。"""
    ctypes.windll.user32.MessageBeep(MB_ICONWARNING)


def beep_error():
    """错误提示音。"""
    ctypes.windll.user32.MessageBeep(MB_ICONERROR)


def beep_double():
    """急促连两声（快到 60s 上限）。"""
    import time
    ctypes.windll.user32.MessageBeep(MB_OK)
    time.sleep(0.1)
    ctypes.windll.user32.MessageBeep(MB_OK)


# ---------------------------------------------------------------------------
# 托盘图标：内存动态生成 ICO
# ---------------------------------------------------------------------------

# ICO 文件结构（简化但完整）：
#   ICO header (6 bytes)
#   ICO directory entry (16 bytes) × 1
#   BMP info header (40 bytes)
#   XOR mask (16×16×4 = 1024 bytes, BGRA)
#   AND mask (16×16/8 = 32 bytes)

def _make_icon_resource(r: int, g: int, b: int) -> bytes:
    """
    生成 16×16 纯色图标资源数据（BMP DIB + XOR + AND）。

    CreateIconFromResourceEx 需要的是纯 BMP 资源格式（无 ICO 文件头），
    不是完整的 .ico 文件。这里只生成资源部分。
    """
    width, height = 16, 16
    xor_size = width * height * 4       # 1024 bytes BGRA
    and_size = (width * height) // 8    # 32 bytes

    # BMP info header (BITMAPINFOHEADER)
    # height*2: ICO 格式约定（XOR mask + AND mask 的总高度）
    bmp_header = struct.pack("<IiiHHIIiiII",
                             40,                       # header size
                             width, height * 2,        # height*2
                             1, 32,                    # planes=1, bpp=32
                             0, xor_size,              # BI_RGB
                             0, 0, 0, 0)

    # XOR mask — BGRA pixels, bottom-up
    xor = b""
    for y in range(height - 1, -1, -1):
        for x in range(width):
            xor += struct.pack("BBBB", b, g, r, 0xFF)

    # AND mask — all 0 = fully opaque
    and_mask = b"\x00" * and_size

    return bmp_header + xor + and_mask


def _make_ico_data(r: int, g: int, b: int) -> bytes:
    """
    生成完整的 16×16 纯色 .ico 文件数据（含 ICO 头部 + 目录），
    用于应用图标文件（generate_icon.py 调用）。
    """
    width, height = 16, 16
    resource = _make_icon_resource(r, g, b)
    xor_size = width * height * 4
    and_size = (width * height) // 8
    image_size = len(resource)

    # ICO header
    ico_header = struct.pack("<HHH", 0, 1, 1)

    # Directory entry
    entry = struct.pack("<BBBBHHII",
                         width, height, 0, 0, 1, 32,
                         image_size, 6 + 16)

    return ico_header + entry + resource


def load_icon(color: str = "gray") -> int:
    """
    从内存中的 BMP 资源数据创建 HICON 句柄。

    CreateIconFromResourceEx 要求纯 BMP DIB 格式（无 ICO 文件头）。
    调用方负责在不需要时 DestroyIcon(hIcon)。
    """
    mapping = {
        "green": _make_icon_resource(0x00, 0xCC, 0x00),
        "red": _make_icon_resource(0xCC, 0x00, 0x00),
        "gray": _make_icon_resource(0x88, 0x88, 0x88),
    }
    data = mapping.get(color, mapping["gray"])

    hicon = ctypes.windll.user32.CreateIconFromResourceEx(
        data, len(data),
        1,                          # fIcon: TRUE = icon
        0x00030000,                 # version
        16, 16,                     # cxDesired, cyDesired
        0x0000,                     # flags (LR_DEFAULTCOLOR)
    )
    return hicon
