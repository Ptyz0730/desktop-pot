# -*- coding: utf-8 -*-
"""Inspect the source cutout so we can pick a background/colorkey strategy."""
import sys
from collections import Counter
from PIL import Image

SRC = sys.argv[1]
im = Image.open(SRC)
print("mode:", im.mode, im.size)
im = im.convert("RGBA")
w, h = im.size
px = im.load()

alpha_hist = Counter()
lum_sum = 0
samples = 0
for y in range(0, h, 3):
    for x in range(0, w, 3):
        r, g, b, a = px[x, y]
        alpha_hist[a // 16] += 1
        lum_sum += (r + g + b) / 3.0
        samples += 1

print("avg luma (all):", round(lum_sum / max(1, samples), 1))
print("alpha buckets (x16):", sorted(alpha_hist.items()))

# bounding box of anything with alpha > 8
bbox = im.split()[3].point(lambda v: 255 if v > 8 else 0).getbbox()
print("alpha>8 bbox:", bbox)

# bounding box of "solid" subject (alpha > 200)
bbox2 = im.split()[3].point(lambda v: 255 if v > 200 else 0).getbbox()
print("alpha>200 bbox:", bbox2)

# vertical profile of subject width, to find the shadow tail
prof = im.split()[3]
for y in range(0, h, 25):
    row = [x for x in range(w) if prof.getpixel((x, y)) > 40]
    if row:
        print(f"y={y:4d}  x {min(row):3d}..{max(row):3d}  n={len(row)}")
    else:
        print(f"y={y:4d}  -")
