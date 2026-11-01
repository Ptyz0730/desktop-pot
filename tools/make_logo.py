# -*- coding: utf-8 -*-
"""把附件里的校徽处理成对话框用的小图标：切圆 + 存成 assets/school_logo.png"""
import os
import sys

from PIL import Image, ImageDraw

SRC = (r"C:\Users\011\.dsh\attachments\v1\objects\76"
       r"\7651c582e480d468f1246c513c9978c6f11ff23df297cc822e4bb02d4ed0be52")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "assets", "school_logo.png")

im = Image.open(SRC).convert("RGBA")
w, h = im.size
side = min(w, h)
im = im.crop(((w - side) // 2, (h - side) // 2,
              (w - side) // 2 + side, (h - side) // 2 + side))
im = im.resize((256, 256), Image.LANCZOS)

# 圆形透明遮罩（略往里收一点，避免留下白色方角）
mask = Image.new("L", (256, 256), 0)
ImageDraw.Draw(mask).ellipse((2, 2, 253, 253), fill=255)
im.putalpha(mask)
im.save(OUT)
print("wrote", OUT, im.size, im.mode)
