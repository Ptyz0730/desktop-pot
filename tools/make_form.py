# -*- coding: utf-8 -*-
"""把一张"透明背景"的立绘做成桌宠能用的**纯色背景**版本。

为什么必须做成纯色背景：本机 layered（真透明）后端一个像素都不画（实测 0.0%），
带透明通道的图会自动走 layered -> 屏幕上什么都看不到。程序对**不带 alpha**的图
会取"四条边上出现最多的颜色"当抠底色，再用 -transparentcolor 抠掉。

底色怎么选（关键）：Tk 的 -transparentcolor 只认**完全相等**的颜色，而缩放会在
人物边缘混出一圈"人物+底色"的过渡色 —— 那些像素不等于底色，就成了描边。
所以底色要：
  1. 人物身上**完全不存在**（否则会被挖洞）；
  2. 尽量中性/贴近常见桌面色，这样那圈过渡色不显眼（绿幕就是一圈刺眼的绿边）；
程序会在候选里自动挑一个"人物身上一个像素都不等于它、且最接近它的人最少"的颜色。

用法：
    python tools/make_form.py [源图] [输出名]
"""
import os
import sys

from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_SRC = (r"C:\Users\011\.dsh\attachments\v1\objects\35"
               r"\35906be87526726771e7b5b91e13051b75281a94dc522281f7aaa3a27848e9f2")
MARGIN = 48                # 四周留白（缩放后保证四条采样边都是纯底色）
ERODE = 1                  # 收掉半透明羽化边
MIN_GAP = 45               # 底色离人物最近的颜色至少要差这么多（cut_out_flat 容差是 10）


def subject_bounds(rgba, threshold=8):
    return rgba.getchannel("A").point(lambda v: 255 if v > threshold else 0).getbbox()


def candidate_colors():
    """候选底色：饱和度高的"幕布色"。

    为什么不用中性灰/白：照片缩放到统一高度时用 LANCZOS，中间调是混出来的
    （白衬衫的褶皱混合后很容易正好落在某个中灰上），程序抠底的小容差就会把
    那些**衣服**像素当成背景 -> 衣服被挖洞。饱和色的混合结果几乎不可能正好
    落在幕布色上，安全得多。
    """
    return [(0, 177, 64),      # 绿幕
            (255, 0, 176),     # 品红
            (0, 96, 255),      # 蓝幕
            (255, 128, 0)]     # 橙幕


def pick_chroma(subject_rgb):
    """挑一个"离人物所有颜色都足够远"的幕布色。"""
    px = subject_rgb.load()
    w, h = subject_rgb.size
    colors = {}
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            colors[px[x, y]] = colors.get(px[x, y], 0) + 1

    def lum_diff(c, o):
        dr, dg, db = abs(c[0] - o[0]), abs(c[1] - o[1]), abs(c[2] - o[2])
        return 0.299 * dr + 0.587 * dg + 0.114 * db

    for c in candidate_colors():
        if c in colors:
            continue
        closest = min(lum_diff(c, o) for o in colors)
        print("候选 #%02x%02x%02x 离人物最近 %.1f" % (c[0], c[1], c[2], closest))
        if closest >= MIN_GAP:
            print("选定 #%02x%02x%02x" % c)
            return c, closest
    print("没有安全的幕布色，退回绿幕")
    return (0, 177, 64), 0


def main():
    src_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    name = sys.argv[2] if len(sys.argv) > 2 else "chm_love_me.png"
    src = Image.open(src_path).convert("RGBA")
    alpha = src.getchannel("A")
    bbox = subject_bounds(src)
    print("源图 %s，alpha 包围盒 %s" % (src.size, bbox))

    left = max(0, bbox[0] - MARGIN)
    top = max(0, bbox[1] - MARGIN)
    right = min(src.size[0], bbox[2] + MARGIN)
    bottom = min(src.size[1], bbox[3] + MARGIN)
    body = src.crop((left, top, right, bottom))

    # 先把人物单独抠出来（硬边：可见像素都是人物自己的颜色）
    hard = body.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
    for _ in range(ERODE):
        hard = hard.filter(ImageFilter.MinFilter(3))
    subject = Image.composite(body.convert("RGB"),
                              Image.new("RGB", body.size, (0, 0, 0)), hard)
    subject_crop = subject.crop(hard.getbbox()) if hard.getbbox() else subject

    chroma, _ = pick_chroma(subject_crop)

    canvas = Image.new("RGB", (body.size[0] + 2 * MARGIN, body.size[1] + 2 * MARGIN),
                       chroma)
    canvas.paste(subject, (MARGIN, MARGIN), hard)
    canvas = canvas.resize((max(1, canvas.size[0] // 2), max(1, canvas.size[1] // 2)),
                           Image.LANCZOS)

    w, h = canvas.size
    px = canvas.load()
    edges = set()
    for x in range(w):
        edges.add(px[x, 0])
        edges.add(px[x, h - 1])
    for y in range(h):
        edges.add(px[0, y])
        edges.add(px[w - 1, y])
    print("四条边上的颜色种类 %d -> %s" % (len(edges), list(edges)[:3]))

    targets = [os.path.join(ROOT, "image", name),
               os.path.join(ROOT, "dist", "桌面宠物", "image", name)]
    for target in targets:
        folder = os.path.dirname(target)
        os.makedirs(folder, exist_ok=True)
        canvas.save(target, "PNG")
        print("写入 %s  %s" % (target, canvas.size))
    preview = os.path.join(ROOT, "form_preview.png")
    canvas.resize((canvas.size[0] * 2, canvas.size[1] * 2), Image.NEAREST).save(preview)
    print("预览", preview)


if __name__ == "__main__":
    main()
