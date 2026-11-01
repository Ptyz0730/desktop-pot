# -*- coding: utf-8 -*-
"""用校徽生成多尺寸 .ico（托盘 / exe / 窗口图标统一用它）。"""
import os

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
SRC = os.path.join(ASSETS, "school_badge.png")
OUT = os.path.join(ASSETS, "school_badge.ico")

img = Image.open(SRC).convert("RGBA")
# 圆外四角已经是透明的；这里再按正方形裁一次，保证 ico 里是完整圆形
side = min(img.size)
img = img.crop(((img.width - side) // 2, (img.height - side) // 2,
                (img.width + side) // 2, (img.height + side) // 2))
img.save(OUT, format="ICO",
         sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                (64, 64), (128, 128), (256, 256)])
print("ico ->", OUT, os.path.getsize(OUT), "bytes")
