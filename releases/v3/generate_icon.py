#!/usr/bin/env python3
"""
图标生成/转换工具。

1. 从 PNG/JPG 图片生成 .ico:
   python generate_icon.py --input logo.png

2. 自动生成默认图标（纯色方块 + 波形图案）:
   python generate_icon.py

输出: icon.ico（含 16/24/32/48/64/128/256 px 七种分辨率）
"""

import argparse
import struct
import sys
from pathlib import Path

SIZES = [16, 24, 32, 48, 64, 128, 256]


def _png_to_ico(input_path: str) -> bytes:
    """从 PNG/JPG 图片生成多分辨率 .ico。"""
    from PIL import Image

    img = Image.open(input_path).convert("RGBA")

    # 裁成正方形（取中心）
    w, h = img.size
    size = min(w, h)
    left = (w - size) // 2
    top = (h - size) // 2
    img = img.crop((left, top, left + size, top + size))

    ico_header = struct.pack("<HHH", 0, 1, len(SIZES))
    entries = b""
    images = b""
    offset = 6 + 16 * len(SIZES)

    for s in SIZES:
        resized = img.resize((s, s), Image.LANCZOS)

        # BMP DIB header (height*2 for ICO: XOR + AND mask)
        xor_size = s * s * 4
        and_size = (s * s) // 8
        bmp = struct.pack("<IiiHHIIiiII",
                          40, s, s * 2, 1, 32,
                          0, xor_size, 0, 0, 0, 0)

        # XOR mask: BGRA, bottom-up
        pixels = list(resized.getdata())
        xor = b""
        for y in range(s - 1, -1, -1):
            row = pixels[y * s : (y + 1) * s]
            for r, g, b, a in row:
                xor += struct.pack("BBBB", b, g, r, a)

        and_mask = b"\x00" * and_size
        image_data = bmp + xor + and_mask

        stored = 0 if s == 256 else s
        entries += struct.pack("<BBBBHHII",
                               stored, stored, 0, 0, 1, 32,
                               len(image_data), offset)
        offset += len(image_data)
        images += image_data

    return ico_header + entries + images


def _auto_ico() -> bytes:
    """自动生成默认图标（纯色波形图案）。"""
    # 颜色: 亮青色 #1D6AD4
    r, g, b = 0x1D, 0x6A, 0xD4
    ico_header = struct.pack("<HHH", 0, 1, len(SIZES))
    entries = b""
    images = b""
    offset = 6 + 16 * len(SIZES)

    for s in SIZES:
        xor_size = s * s * 4
        and_size = (s * s) // 8
        bmp = struct.pack("<IiiHHIIiiII",
                          40, s, s * 2, 1, 32,
                          0, xor_size, 0, 0, 0, 0)

        # 圆角矩形 + 渐变 + 波形图案
        xor = b""
        cx, cy = s // 2, s // 2
        for y in range(s - 1, -1, -1):
            for x in range(s):
                px = _auto_pixel(x, y, s, r, g, b)
                xor += struct.pack("BBBB", px[2], px[1], px[0], px[3])

        and_mask = b"\x00" * and_size
        image_data = bmp + xor + and_mask

        stored = 0 if s == 256 else s
        entries += struct.pack("<BBBBHHII",
                               stored, stored, 0, 0, 1, 32,
                               len(image_data), offset)
        offset += len(image_data)
        images += image_data

    return ico_header + entries + images


def _auto_pixel(x, y, size, bg_r, bg_g, bg_b):
    """默认图标像素生成（简化的圆角矩形 + 波形）。"""
    import math
    margin = max(1, size // 12)
    radius = max(2, size // 5)

    # 圆角矩形检测
    in_bg = True
    if x < margin + radius and y < margin + radius:
        dx, dy = x - (margin + radius), y - (margin + radius)
        if dx * dx + dy * dy > radius * radius:
            in_bg = False
    if x >= size - margin - radius and y < margin + radius:
        dx, dy = x - (size - margin - radius - 1), y - (margin + radius)
        if dx * dx + dy * dy > radius * radius:
            in_bg = False
    if x < margin + radius and y >= size - margin - radius:
        dx, dy = x - (margin + radius), y - (size - margin - radius - 1)
        if dx * dx + dy * dy > radius * radius:
            in_bg = False
    if x >= size - margin - radius and y >= size - margin - radius:
        dx, dy = x - (size - margin - radius - 1), y - (size - margin - radius - 1)
        if dx * dx + dy * dy > radius * radius:
            in_bg = False
    if x < margin or x >= size - margin or y < margin or y >= size - margin:
        if not in_bg:
            in_bg = False

    if not in_bg:
        return (0, 0, 0, 0)  # 透明

    # 渐变
    t = y / size
    dark_r, dark_g, dark_b = int(bg_r * 0.75), int(bg_g * 0.75), int(bg_b * 0.75)
    pr = int(bg_r * (1 - t) + dark_r * t)
    pg = int(bg_g * (1 - t) + dark_g * t)
    pb = int(bg_b * (1 - t) + dark_b * t)

    # 波形图案（三条竖线）
    bar_w = max(1, size // 10)
    cx2 = size // 2
    cy2 = size // 2
    gap = max(2, size // 7)
    ratios = [0.35, 0.72, 0.50]
    offsets = [-gap, 0, gap]

    for off, ratio in zip(offsets, ratios):
        bx = cx2 + off
        bw2 = bar_w // 2
        bh2 = int(size * ratio / 2)
        if (bx - bw2 <= x <= bx + bw2 and
                cy2 - bh2 <= y <= cy2 + bh2):
            return (255, 255, 255, 255)

    return (pr, pg, pb, 255)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="图标生成/转换")
    parser.add_argument("--input", help="PNG/JPG 图片路径（可选，不指定则自动生成）")
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    output = script_dir / "icon.ico"

    if args.input:
        if not Path(args.input).exists():
            print(f"错误: 文件不存在 {args.input}")
            sys.exit(1)
        ico_data = _png_to_ico(args.input)
        print(f"输入: {args.input}")
    else:
        ico_data = _auto_ico()
        print("自动生成默认图标")

    with open(output, "wb") as f:
        f.write(ico_data)

    size_kb = len(ico_data) / 1024
    print(f"输出: {output}")
    print(f"分辨率: {SIZES}")
    print(f"大小: {size_kb:.1f} KB")
    print("打包前用此文件替换 icon.ico 即可")
