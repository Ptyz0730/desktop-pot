# -*- coding: utf-8 -*-
"""第十一轮：给右键菜单补图标。"""
import io

P = 'desktop_pet.py'
s = io.open(P, encoding='utf-8').read()

old = '''    else:
        draw.ellipse([0.15 * s, 0.15 * s, 0.85 * s, 0.85 * s], outline=c, width=lw)
    img = big.resize((int(size), int(size)), Image.LANCZOS)'''
new = '''    elif name == "jump":
        line((0.50, 0.84), (0.50, 0.22))
        line((0.30, 0.42), (0.50, 0.20), (0.70, 0.42))
        line((0.24, 0.78), (0.76, 0.78))
    elif name == "squash":
        line((0.50, 0.12), (0.50, 0.50))
        line((0.32, 0.34), (0.50, 0.52), (0.68, 0.34))
        draw.ellipse([0.16 * s, 0.66 * s, 0.84 * s, 0.86 * s],
                     outline=c, width=lw)
    elif name == "spin":
        draw.arc([0.16 * s, 0.16 * s, 0.84 * s, 0.84 * s], 120, 60,
                 fill=c, width=lw)
        draw.polygon([(0.70 * s, 0.06 * s), (0.92 * s, 0.28 * s),
                      (0.66 * s, 0.36 * s)], fill=c)
    elif name == "dodge":
        draw.arc([0.26 * s, 0.20 * s, 0.96 * s, 0.80 * s], 120, 240,
                 fill=c, width=lw)
        draw.arc([0.04 * s, 0.20 * s, 0.74 * s, 0.80 * s], -60, 60,
                 fill=c, width=lw)
        draw.ellipse([0.40 * s, 0.40 * s, 0.60 * s, 0.60 * s], fill=c)
    elif name == "shoot":
        draw.polygon([(0.08 * s, 0.30 * s), (0.92 * s, 0.16 * s),
                      (0.44 * s, 0.86 * s), (0.38 * s, 0.54 * s)],
                     outline=c, width=lw)
        line((0.38, 0.54), (0.92, 0.16))
    elif name == "smile":
        draw.ellipse([0.12 * s, 0.12 * s, 0.88 * s, 0.88 * s],
                     outline=c, width=lw)
        draw.ellipse([0.32 * s, 0.34 * s, 0.40 * s, 0.46 * s], fill=c)
        draw.ellipse([0.60 * s, 0.34 * s, 0.68 * s, 0.46 * s], fill=c)
        draw.arc([0.30 * s, 0.36 * s, 0.70 * s, 0.72 * s], 20, 160,
                 fill=c, width=lw)
    elif name == "face":
        draw.ellipse([0.14 * s, 0.14 * s, 0.86 * s, 0.86 * s],
                     outline=c, width=lw)
        draw.ellipse([0.30 * s, 0.42 * s, 0.40 * s, 0.54 * s], fill=c)
        draw.ellipse([0.60 * s, 0.42 * s, 0.70 * s, 0.54 * s], fill=c)
        line((0.42, 0.64), (0.50, 0.70), (0.58, 0.64))
        draw.ellipse([0.20 * s, 0.54 * s, 0.30 * s, 0.62 * s], fill=c)
        draw.ellipse([0.70 * s, 0.54 * s, 0.80 * s, 0.62 * s], fill=c)
    elif name == "note":
        draw.ellipse([0.18 * s, 0.66 * s, 0.38 * s, 0.84 * s], fill=c)
        draw.ellipse([0.56 * s, 0.56 * s, 0.76 * s, 0.74 * s], fill=c)
        line((0.34, 0.74), (0.34, 0.24), (0.72, 0.18), (0.72, 0.66))
        line((0.34, 0.24), (0.72, 0.18))
    elif name == "globe":
        draw.ellipse([0.12 * s, 0.12 * s, 0.88 * s, 0.88 * s],
                     outline=c, width=lw)
        draw.ellipse([0.36 * s, 0.12 * s, 0.64 * s, 0.88 * s],
                     outline=c, width=lw)
        line((0.14, 0.50), (0.86, 0.50))
    elif name == "power":
        draw.arc([0.16 * s, 0.18 * s, 0.84 * s, 0.86 * s], 300, 240,
                 fill=c, width=lw)
        line((0.50, 0.10), (0.50, 0.46))
    else:
        draw.ellipse([0.15 * s, 0.15 * s, 0.85 * s, 0.85 * s], outline=c, width=lw)
    img = big.resize((int(size), int(size)), Image.LANCZOS)'''

assert old in s
s = s.replace(old, new, 1)
io.open(P, 'w', encoding='utf-8', newline='').write(s)
print('icons patched')
