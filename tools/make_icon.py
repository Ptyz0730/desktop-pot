# -*- coding: utf-8 -*-
"""Build the app icon (multi-size .ico) from the pet sprite's head."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from PIL import Image  # noqa: E402

SRC = os.path.join(ROOT, "assets", "pet_gray_rgba.png")
OUT = os.path.join(ROOT, "assets", "pet.ico")


def main():
    img = Image.open(SRC).convert("RGBA")
    w, h = img.size
    # 头在上部约 1/3，取一个正方形并留一点边
    side = int(w * 0.62)
    left = (w - side) // 2
    top = int(h * 0.015)
    head = img.crop((left, top, left + side, top + side))

    # .ico 不支持半透明边缘之外的额外处理，但需要不透明底才好看：垫一层深色
    flat = Image.new("RGBA", head.size, (32, 36, 46, 255))
    flat.alpha_composite(head)

    flat.save(OUT, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print("wrote %s from %s" % (OUT, os.path.basename(SRC)))
    print("sizes:", Image.open(OUT).size)


if __name__ == "__main__":
    main()
