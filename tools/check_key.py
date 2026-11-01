# -*- coding: utf-8 -*-
"""Check that hardening the fringe does not punch holes in the subject."""
import os
import sys
from PIL import Image

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


def check(path, key):
    im = Image.open(path).convert("RGB")
    w, h = im.size
    px = im.load()
    same = 0
    interior = 0
    for y in range(h):
        for x in range(w):
            if px[x, y] == key:
                same += 1
                # a keyed pixel with keyed neighbours on all 4 sides is "interior"
                if all(
                    0 <= x + dx < w and 0 <= y + dy < h and px[x + dx, y + dy] == key
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                ):
                    interior += 1
    print("%-24s key-px=%-7d fully-enclosed key-px=%-6d (%.3f%%)"
          % (os.path.basename(path), same, interior, 100.0 * interior / (w * h)))


if __name__ == "__main__":
    check(os.path.join(ASSETS, "pet_black_flat.png"), (0, 0, 0))
    check(os.path.join(ASSETS, "pet_white_flat.png"), (255, 255, 255))
    check(os.path.join(ASSETS, "pet_gray_flat.png"), (120, 126, 136))
