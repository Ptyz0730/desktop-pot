# -*- coding: utf-8 -*-
"""截两张带颜文字的气泡图，检查气泡字体里有没有这些符号（缺字会画成方块）。"""
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import desktop_pet as dp  # noqa: E402
import kaomoji  # noqa: E402
from PIL import ImageGrab  # noqa: E402

CFG = dp.CONFIG_PATH
BAK = CFG + ".kaoshot"
if os.path.exists(CFG):
    shutil.copy2(CFG, BAK)

pet = None


def grab(name):
    win = pet.bubble.win
    win.update_idletasks()
    im = ImageGrab.grab(all_screens=True)
    sc = im.size[0] / float(pet.root.winfo_screenwidth())
    bx, by = win.winfo_rootx(), win.winfo_rooty()
    bw, bh = win.winfo_width(), win.winfo_height()
    box = (max(0, int((bx - 16) * sc)), max(0, int((by - 16) * sc)),
           int((bx + bw + 16) * sc), int((by + bh + 16) * sc))
    im.crop(box).save(os.path.join(ROOT, name))
    print("saved", name, box)


try:
    if os.path.exists(CFG):
        os.remove(CFG)
    pet = dp.DesktopPet(use_ai=False, topmost=True, bubble=True)
    for _ in range(50):
        pet.root.update()
        time.sleep(0.05)
    pet.move(110, 110)
    for _ in range(20):
        pet.root.update()
        time.sleep(0.05)

    pet.speak("今天训练还行吧 " + " ".join(kaomoji.GROUPS[m][0]
                                         for m in ("开心", "害羞", "得意", "疑问")))
    for _ in range(12):
        pet.root.update()
        time.sleep(0.05)
    grab("kaomoji_preview.png")

    pet.speak("哦。" + " ".join(kaomoji.GROUPS[m][0]
                               for m in ("生气", "无语", "难过", "困")))
    for _ in range(12):
        pet.root.update()
        time.sleep(0.05)
    grab("kaomoji_preview2.png")
finally:
    try:
        if pet is not None:
            pet.quit()
    except Exception:                       # noqa: BLE001
        pass
    if os.path.exists(CFG):
        os.remove(CFG)
    if os.path.exists(BAK):
        shutil.move(BAK, CFG)
