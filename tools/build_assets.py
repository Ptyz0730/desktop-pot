# -*- coding: utf-8 -*-
"""Build desktop-pet sprites from the source cutout.

Outputs, per key colour (black / white / gray):

  pet_<name>_rgba.png  untouched RGBA, for the per-pixel-alpha backend
  pet_<name>_flat.png  flattened onto the chroma-key colour, for the
                       Tk -transparentcolor (1-bit) backend

The app picks whichever matches the backend it managed to start.
"""
import os
import sys
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ASSETS = os.path.join(ROOT, "assets")

OUT_W = 420            # sprite width in px
HARD_CUT = 14          # alpha <= this -> key colour (window transparent)
SOLID = 205            # alpha >= this -> fully opaque subject
NOISE_MIN = 60         # drop connected blobs smaller than this many px
KEEP_BLOB_MIN = 400    # after cleanup only blobs this big survive the final pass
EDGE_TINT = (120, 126, 136)
KEYS = (("black", (0, 0, 0)),
        ("white", (255, 255, 255)),
        ("gray", EDGE_TINT))



def key_out(im, key):
    """把 RGBA 压平到抠底色上：低 alpha 的边缘并进底色，主体保持原色。"""
    flat = Image.new("RGBA", im.size, key + (255,))
    flat.alpha_composite(im)
    px = flat.load()
    w, h = flat.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a <= HARD_CUT:
                px[x, y] = key + (255,)
            elif a >= SOLID:
                px[x, y] = (r, g, b, 255)
            else:
                # 边缘只有一位可用：低于阀值的直接归底色，其余按 alpha 混过去
                t = (a - HARD_CUT) / float(SOLID - HARD_CUT)
                px[x, y] = (
                    int(round(key[0] + (r - key[0]) * t)),
                    int(round(key[1] + (g - key[1]) * t)),
                    int(round(key[2] + (b - key[2]) * t)),
                    255,
                )
    return flat.convert("RGB")


def blobs(alpha):
    """Yield each connected lit region as a list of pixels (8-connected)."""
    from collections import deque
    w, h = alpha.size
    px = alpha.load()
    seen = bytearray(w * h)
    for sy in range(h):
        for sx in range(w):
            if seen[sy * w + sx] or px[sx, sy] == 0:
                continue
            q = deque([(sx, sy)])
            seen[sy * w + sx] = 1
            blob = []
            while q:
                x, y = q.popleft()
                blob.append((x, y))
                for ny in (y - 1, y, y + 1):
                    for nx in (x - 1, x, x + 1):
                        if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx] and px[nx, ny]:
                            seen[ny * w + nx] = 1
                            q.append((nx, ny))
            yield blob


def drop_speckles(alpha):
    """Zero out tiny disconnected alpha islands (JPEG crumbs).

    Uses a very low threshold so that nearly-invisible crumbs (alpha == 1) are
    still seen, then junks isolated pixels by neighbour count: real antialiased
    edges always have at least two neighbours on a continuous contour.
    """
    w, h = alpha.size
    px = alpha.load()
    dropped = 0
    for blob in blobs(alpha):
        if len(blob) < NOISE_MIN:
            dropped += len(blob)
            for x, y in blob:
                px[x, y] = 0
    if dropped:
        print("  dropped %d speckle px in small blobs" % dropped)

    # isolated-pixel pass: any lit pixel with fewer than 2 lit neighbours
    kill = []
    for y in range(h):
        for x in range(w):
            if not px[x, y] or not (0 < x < w - 1 and 0 < y < h - 1):
                continue
            n = sum(1 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1),
                                     (1, 1), (1, -1), (-1, 1), (-1, -1))
                    if px[x + dx, y + dy])
            if n < 2:
                kill.append((x, y))
    for x, y in kill:
        px[x, y] = 0
    if kill:
        print("  dropped %d isolated pixels" % len(kill))
    return alpha


def keep_main(alpha, label="resize"):
    """Keep only the subject: discard leftover satellite islands entirely."""
    px = alpha.load()
    parts = sorted(blobs(alpha), key=len, reverse=True)
    total = sum(len(p) for p in parts)
    dropped = 0
    for part in parts:
        if len(part) >= KEEP_BLOB_MIN:
            continue
        dropped += len(part)
        for x, y in part:
            px[x, y] = 0
    if dropped:
        print("  [%s] kept %d blob(s), dropped %d px in %d satellite component(s)"
              % (label, sum(1 for p in parts if len(p) >= KEEP_BLOB_MIN), dropped,
                 sum(1 for p in parts if len(p) < KEEP_BLOB_MIN)))
    return alpha


def strip_satellites(rgb, key):
    """Flattened sprite: drop every non-key component except the biggest one.

    Runs last, on exactly the pixels Tk will see, so no crumb can survive —
    including ones that only become non-key after the matte is flattened.
    """
    w, h = rgb.size
    px = rgb.load()
    mask = rgb.copy()
    mpx = mask.load()
    for y in range(h):
        for x in range(w):
            mpx[x, y] = 0 if px[x, y] == key else 255
    parts = sorted(blobs(mask.split()[0]), key=len, reverse=True)
    if len(parts) <= 1:
        return rgb
    dropped = 0
    for part in parts[1:]:
        dropped += len(part)
        for x, y in part:
            px[x, y] = key
    print("  flattened: dropped %d px in %d stray component(s), kept main %d px"
          % (dropped, len(parts) - 1, len(parts[0])))
    return rgb


def build(src, out_w=OUT_W):
    im = Image.open(src).convert("RGBA")
    # speckle removal first (so faint crumbs are still visible), then smooth edges
    a = drop_speckles(im.split()[3])
    a = a.filter(ImageFilter.MedianFilter(3))
    im.putalpha(a)

    bbox = a.point(lambda v: 255 if v > 40 else 0).getbbox()
    if bbox:
        im = im.crop(bbox)
    w, h = im.size
    out_h = max(1, int(round(h * out_w / float(w))))
    im = im.resize((out_w, out_h), Image.LANCZOS)

    # resize can create new halo crumbs; isolate the subject last so nothing
    # (not even the median filter) can leave satellites behind
    im.putalpha(im.split()[3].filter(ImageFilter.MedianFilter(3)))
    im.putalpha(keep_main(im.split()[3], "pre-key"))

    os.makedirs(ASSETS, exist_ok=True)
    # 抠底色的三个选择：黑/白适合同色桌面，灰是"深浅桌面都不刺眼"的折中
    for name, key in KEYS:
        # 逐像素 alpha 后端直接吃 RGBA，边缘最干净
        rgba_path = os.path.join(ASSETS, "pet_%s_rgba.png" % name)
        im.save(rgba_path)
        print("wrote %s %s" % (os.path.basename(rgba_path), im.size))

        sprite = strip_satellites(key_out(im, key), key)
        path = os.path.join(ASSETS, "pet_%s_flat.png" % name)
        sprite.save(path)
        print("wrote %s %s" % (os.path.basename(path), sprite.size))

        # mock preview: what the sprite looks like over a desktop
        tint = {"black": (26, 30, 40), "white": (246, 247, 251),
                "gray": (236, 238, 244)}[name]
        bg = Image.new("RGB", sprite.size, tint)
        sp = sprite.load()
        bp = bg.load()
        for y in range(sprite.size[1]):
            for x in range(sprite.size[0]):
                if sp[x, y] != key:
                    bp[x, y] = sp[x, y]
        bg.save(os.path.join(ASSETS, "preview_%s.png" % name))
    return (out_w, out_h)


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "source", "pet_source.png")
    print("source:", src)
    print("final size:", build(src))
