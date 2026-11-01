# -*- coding: utf-8 -*-
"""截图：「添加网页」小窗（自己填名字+网址）。"""
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import desktop_pet as dp  # noqa: E402
from PIL import ImageGrab  # noqa: E402

CFG = dp.CONFIG_PATH
BAK = CFG + ".shotweb_bak"
pet = None
try:
    if os.path.exists(CFG):
        shutil.copy2(CFG, BAK)
        os.remove(CFG)
    pet = dp.DesktopPet(use_ai=False, topmost=True, bubble=False)
    for _ in range(40):
        pet.root.update()
        time.sleep(0.05)
    dlg = dp.WebLinkDialog(pet)
    dlg._build()
    dlg.name_var.set("Bilibili 直播")
    dlg.url_var.set("live.bilibili.com")
    for _ in range(30):
        pet.root.update()
        time.sleep(0.05)
    w = dlg.win
    w.update_idletasks()
    im = ImageGrab.grab(all_screens=True)
    sc = im.size[0] / float(pet.root.winfo_screenwidth())
    x, y = w.winfo_rootx(), w.winfo_rooty()
    ww, wh = w.winfo_width(), w.winfo_height()
    box = (max(0, int((x - 14) * sc)), max(0, int((y - 34) * sc)),
           int((x + ww + 14) * sc), int((y + wh + 14) * sc))
    im.crop(box).save(os.path.join(ROOT, "weblink_dialog.png"))
    print("saved", box, "mapped", w.winfo_ismapped())
finally:
    try:
        if pet is not None:
            pet.quit()
    except Exception:                       # noqa: BLE001
        pass
    try:
        if os.path.exists(CFG):
            os.remove(CFG)
        if os.path.exists(BAK):
            shutil.move(BAK, CFG)
    except Exception:                       # noqa: BLE001
        pass
