#!/usr/bin/env python3
"""
生成应用图标 icon.ico（多分辨率，纯 Python，零依赖）。

运行一次即可：
    python generate_icon.py

输出: icon.ico（项目根目录）
包含: 16×16, 24×24, 32×32, 48×48, 64×64, 128×128, 256×256
"""

import struct

# ── 颜色常量 (BGRA) ──
BG_TEAL = (0xD4, 0x6A, 0x1D, 0xFF)      # 背景：亮青色 #1D6AD4
BG_DARK = (0xB8, 0x55, 0x16, 0xFF)      # 背景深色：暗蓝 #1655B8
WHITE = (0xFF, 0xFF, 0xFF, 0xFF)
TRANS = (0x00, 0x00, 0x00, 0x00)        # 全透明


def _make_bmp(width: int, height: int) -> bytes:
    """
    生成带音频波形图案的 32-bit BGRA 位图（含 XOR + AND mask）。
    height 应为实际高度的 2 倍（ICO 格式要求 XOR + AND）。
    """
    real_h = height // 2
    xor_size = width * real_h * 4
    and_size = (width * real_h) // 8

    # BMP info header (40 bytes)
    bmp = struct.pack("<IiiHHIIiiII",
                      40,                    # header size
                      width, height,         # width, height*2
                      1, 32,                 # planes=1, bpp=32
                      0, xor_size,           # BI_RGB
                      0, 0, 0, 0)

    # XOR mask (bottom-up)
    xor = b""
    cx, cy = width / 2, real_h / 2          # 中心点

    for y in range(real_h - 1, -1, -1):
        for x in range(width):
            r, g, b, a = _pixel(x, y, width, real_h)
            xor += struct.pack("BBBB", b, g, r, a)

    # AND mask (1-bit transparency, all 0 = fully opaque)
    and_mask = b"\x00" * and_size

    return bmp + xor + and_mask


def _pixel(x: int, y: int, w: int, h: int) -> tuple:
    """计算 (x, y) 处的像素颜色 (R, G, B, A)。"""

    # ── 圆角矩形背景 ──
    margin = max(1, w // 16)
    radius = max(2, w // 6)

    # 圆角矩形内？
    in_bg = True
    # 左上角
    if x < margin + radius and y < margin + radius:
        dx, dy = x - (margin + radius), y - (margin + radius)
        if dx*dx + dy*dy > radius*radius:
            in_bg = False
    # 右上角
    if x >= w - margin - radius and y < margin + radius:
        dx, dy = x - (w - margin - radius - 1), y - (margin + radius)
        if dx*dx + dy*dy > radius*radius:
            in_bg = False
    # 左下角
    if x < margin + radius and y >= h - margin - radius:
        dx, dy = x - (margin + radius), y - (h - margin - radius - 1)
        if dx*dx + dy*dy > radius*radius:
            in_bg = False
    # 右下角
    if x >= w - margin - radius and y >= h - margin - radius:
        dx, dy = x - (w - margin - radius - 1), y - (h - margin - radius - 1)
        if dx*dx + dy*dy > radius*radius:
            in_bg = False
    # 四条边
    if x < margin or x >= w - margin or y < margin or y >= h - margin:
        if not in_bg:  # 已在角区判过
            in_bg = False

    if not in_bg:
        return TRANS

    # ── 渐变背景（顶部亮一点） ──
    t = y / h  # 0(顶部) ~ 1(底部)
    bg_r = int(BG_TEAL[0] * (1 - t) + BG_DARK[0] * t)
    bg_g = int(BG_TEAL[1] * (1 - t) + BG_DARK[1] * t)
    bg_b = int(BG_TEAL[2] * (1 - t) + BG_DARK[2] * t)
    bg_a = 255

    # ── 音频波形图案（三条竖线） ──
    bar_w = max(1, w // 10)
    center_x = w // 2
    center_y = h // 2

    # 三条竖线：左(-gap)、中、右(+gap)
    gap = max(2, w // 7)
    # 每条竖线的高度用正弦函数模拟波形
    import math as _math
    bar_h_ratios = [0.35, 0.72, 0.50]  # 左中右三条线的高度比例
    bar_x_offsets = [-gap, 0, gap]

    for bx_off, ratio in zip(bar_x_offsets, bar_h_ratios):
        bx = center_x + bx_off
        bar_half_w = bar_w // 2
        bar_half_h = int(h * ratio / 2)
        bar_top = center_y - bar_half_h
        bar_bot = center_y + bar_half_h

        if (bx - bar_half_w <= x <= bx + bar_half_w and
                bar_top <= y <= bar_bot):
            # 竖条顶端加小圆角（仅在两端 15% 区域检查）
            if y <= bar_top + bar_half_w and x != bx:
                dy2 = y - bar_top
                dx2 = abs(x - bx)
                if dx2 * dx2 + dy2 * dy2 > (bar_half_w + 1) ** 2:
                    continue
            if y >= bar_bot - bar_half_w and x != bx:
                dy2 = bar_bot - y
                dx2 = abs(x - bx)
                if dx2 * dx2 + dy2 * dy2 > (bar_half_w + 1) ** 2:
                    continue
            return WHITE

    return (bg_r, bg_g, bg_b, bg_a)


def build_ico(sizes: list[int] = None) -> bytes:
    """构建多分辨率 .ico 文件。"""
    if sizes is None:
        sizes = [16, 24, 32, 48, 64, 128, 256]

    # 处理 256 的限制（ICO format: width/height stored as 1 byte, 0 = 256）
    entries = []
    images = []

    offset = 6 + 16 * len(sizes)  # header + directory entries

    for size in sizes:
        stored = 0 if size == 256 else size
        bmp_data = _make_bmp(size, size * 2)
        images.append(bmp_data)

        entry = struct.pack("<BBBBHHII",
                            stored, stored,           # width, height (0 = 256)
                            0, 0,                     # palette, reserved
                            1, 32,                     # planes=1, bpp=32
                            len(bmp_data), offset)
        entries.append(entry)
        offset += len(bmp_data)

    # ICO header: reserved(2) + type(2) + count(2)
    header = struct.pack("<HHH", 0, 1, len(sizes))

    return header + b"".join(entries) + b"".join(images)


if __name__ == "__main__":
    import os

    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(script_dir, "icon.ico")

    ico_data = build_ico()
    with open(output_path, "wb") as f:
        f.write(ico_data)

    file_size = len(ico_data) / 1024
    print(f"Icon generated: {output_path}")
    print(f"Resolutions: 16/24/32/48/64/128/256 px")
    print(f"Size: {file_size:.1f} KB")
    print(f"")
    print(f"Tip: To use a custom icon, replace {output_path} and rebuild.")