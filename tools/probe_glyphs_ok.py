# -*- coding: utf-8 -*-
"""列出气泡字体能画的字符（用来挑颜文字用的符号）。"""
import sys
import tkinter as tk
import tkinter.font as tkfont
import unicodedata

HERE = __import__("os").path.dirname(__import__("os").path.abspath(__file__))
ROOT = __import__("os").path.dirname(HERE)
sys.path.insert(0, ROOT)

import desktop_pet as dp  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

root = tk.Tk()
root.withdraw()
tkf = tkfont.Font(root=root, family=dp.FONT_FAMILY, size=dp.FONT_SIZE)
font = dp.pick_pil_font(tkf, "\u684c\u9762\u5ba0\u7269 Desktop Pet 1234")


def mask_of(ch):
    im = Image.new("L", (56, 56), 0)
    ImageDraw.Draw(im).text((4, 4), ch, font=font, fill=255)
    return im.tobytes()


tofu = mask_of(chr(0xE123))
blank = mask_of(" ")

candidates = (
    "()\uff08\uff09[]\u3010\u3011{}\u300a\u300b"
    "\uffe3_^vV\u03c9\u03a9\u00b0\u25bd\u25b3\u2267\u2266\u2606\u2605\u2661\u2665\u00b7\u30fb.,:;!?\uff01\uff1f\u2026\u2014-+=*/\\|"
    "\u2200\u25e1\u2310\u25a0\u25a1\u2299\uff20\uff03\uff04\uff05\uff06\uff0a\uff3e\uff3f\uff5c\uff5e\uff40\u30fd\u30fe\u30ce\u30df\uff89\u309e"
    "\u02c2\u02c3\u02d8\u02c7\u00a8\u3003\uff0a\u203b\uff40"
    "\u30fc\u30a1\u30a3\u30a5\u30a7\u30a9\u30ab\u30ad\u30af\u30b1\u30b3\u30b5\u30b7\u30b9\u30bb\u30bd\u30bf\u30c1\u30c4\u30c6\u30c8"
)
print("可用字符:")
ok_chars = []
for ch in candidates:
    m = mask_of(ch)
    if m == tofu or m == blank:
        continue
    if unicodedata.combining(ch):
        continue
    ok_chars.append(ch)
print("".join(ok_chars))
print("个数:", len(ok_chars))
root.destroy()
