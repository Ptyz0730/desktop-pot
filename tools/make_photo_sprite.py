#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一张"白底人像照片"做成桌宠立绘（透明背景 PNG）。

用法：
    python tools/make_photo_sprite.py 照片.png image/郑迪隆.png
    python tools/make_photo_sprite.py 照片.png image/郑迪隆.png --bottom 0.94

干的事：
  1. 从四边往里"泛洪"，把和边缘连通的近白像素判成背景（人物身上的白不误伤）；
  2. 按边缘羽化 alpha，再按 alpha 反解出原色（去掉白边，不然缩放后会有一圈白描边）；
  3. 裁到人物内容框，底部留一点点渐变（照片是半身，避免一刀切的硬边）；
  4. 存成 RGBA PNG —— 桌宠会自己识别透明通道。

只依赖 Pillow + numpy（打包环境里都有）。
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageFilter

WHITE = 246          # 近白判定：三通道都 >= 这个值才算背景
FEATHER = 1.2        # alpha 羽化半径（px）


def background_mask(rgb):
    """从四边泛洪：返回 bool 数组，True = 背景。"""
    arr = np.asarray(rgb, dtype=np.uint8).astype(np.int16)
    near_white = (arr >= WHITE).all(axis=2)
    h, w = near_white.shape

    bg = np.zeros((h, w), dtype=bool)
    bg[0, :] = near_white[0, :]
    bg[-1, :] = near_white[-1, :]
    bg[:, 0] = near_white[:, 0]
    bg[:, -1] = near_white[:, -1]

    while True:
        grown = bg.copy()
        grown[1:, :] |= bg[:-1, :]
        grown[:-1, :] |= bg[1:, :]
        grown[:, 1:] |= bg[:, :-1]
        grown[:, :-1] |= bg[:, 1:]
        grown &= near_white
        if (grown == bg).all():
            return bg
        bg = grown


def make_sprite(src_path, out_path, bottom_fade=0.94, pad=2):
    src = Image.open(src_path)
    if src.mode in ("RGBA", "LA", "P"):
        src = src.convert("RGBA")
        flat = Image.new("RGBA", src.size, (255, 255, 255, 255))
        flat.alpha_composite(src)
        src = flat
    rgb = src.convert("RGB")

    bg = background_mask(rgb)
    alpha = Image.fromarray(np.where(bg, 0, 255).astype(np.uint8), "L")
    # 先羽化再反解：摄影棚白底 + 羽化 = 一圈白边，必须把混进来的白除掉
    soft = alpha.filter(ImageFilter.GaussianBlur(FEATHER))

    rgb_arr = np.asarray(rgb, dtype=np.float32)
    a = np.asarray(soft, dtype=np.float32)[..., None] / 255.0
    with np.errstate(divide="ignore", invalid="ignore"):
        un = (rgb_arr - (1.0 - a) * 255.0) / np.maximum(a, 1e-3)
    un = np.clip(un, 0, 255)
    out_arr = np.dstack([un, np.asarray(soft, dtype=np.float32)])
    out = Image.fromarray(out_arr.astype(np.uint8), "RGBA")

    bbox = out.getbbox()
    if bbox:
        out = out.crop(bbox)
    w, h = out.size
    if pad:
        canvas = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
        canvas.alpha_composite(out, (pad, pad))
        out = canvas
        w, h = out.size

    # 底部渐隐：照片是半身像，直接切断像被裁掉；渐变让它"淡出"在桌面上
    if 0 < bottom_fade < 1.0:
        fade_h = max(8, int(round(h * (1.0 - bottom_fade))))
        mask = out.getchannel("A").copy()
        px = mask.load()
        for y in range(h - fade_h, h):
            k = (h - y) / float(fade_h)
            for x in range(w):
                px[x, y] = int(px[x, y] * k)
        out.putalpha(mask)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    out.save(out_path, "PNG", optimize=True)
    return out.size


def main(argv=None):
    ap = argparse.ArgumentParser(description="白底人像 -> 桌宠立绘")
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--bottom", type=float, default=0.94,
                    help="从这个比例开始向下渐隐（0.94 = 底部 6%%）")
    args = ap.parse_args(argv)
    size = make_sprite(args.src, args.out, bottom_fade=args.bottom)
    print("saved %s  %dx%d" % (args.out, size[0], size[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
