# -*- coding: utf-8 -*-
"""检查气泡字体（PIL 那一套）能不能画出颜文字里的每个字符。

画不出来的字符在气泡里会变成方块 ▯，所以词库里出现这种字符就要换掉。
"""
import sys
import tkinter as tk
import tkinter.font as tkfont

HERE = __import__("os").path.dirname(__import__("os").path.abspath(__file__))
ROOT = __import__("os").path.dirname(HERE)
sys.path.insert(0, ROOT)

import desktop_pet as dp  # noqa: E402
import kaomoji  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

root = tk.Tk()
root.withdraw()
tkf = tkfont.Font(root=root, family=dp.FONT_FAMILY, size=dp.FONT_SIZE)
font = dp.pick_pil_font(tkf, "桌面宠物 Desktop Pet 1234")


def mask_of(ch):
    im = Image.new("L", (48, 48), 0)
    ImageDraw.Draw(im).text((4, 4), ch, font=font, fill=255)
    return im.tobytes()


# 私用区字符几乎必然缺字，用它当"方块"的参照
tofu = mask_of(chr(0xE123))
blank = mask_of(" ")

chars = sorted({ch for k in kaomoji.all_kaomoji() for ch in k})
missing = []
for ch in chars:
    m = mask_of(ch)
    if m == tofu or m == blank:
        missing.append(ch)
print("字符数:", len(chars))
print("缺字:", "".join(missing) if missing else "（无）")
for ch in missing:
    print("   U+%04X %r" % (ord(ch), ch))
bad = [k for k in kaomoji.all_kaomoji() if any(c in missing for c in k)]
print("受影响的颜文字:", bad)
root.destroy()
