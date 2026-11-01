# -*- coding: utf-8 -*-
"""截一张"好感度 +2 / 已满"提示的聊天窗（真接口、临时配置、用完还原）。"""
import io
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import desktop_pet as dp  # noqa: E402

CFG = dp.CONFIG_PATH
BAK = CFG + ".shot_aff_bak"
if os.path.exists(CFG):
    shutil.copy2(CFG, BAK)
try:
    if os.path.exists(CFG):
        os.remove(CFG)
    pet = dp.DesktopPet(use_ai=True, topmost=False, bubble=True)
    time.sleep(0.3)
    pet.cfg.setdefault("personas", {})[pet.image_name] = "闷骚少年"
    pet._persona = None
    pet._apply_persona()
    pet.open_chat()
    time.sleep(0.4)
    pet.root.update()
    win = pet.chat_win
    win.add_user("今天训练累不累")
    win.add_reply("还行吧，就投了几百个球。不过 I'm goat，"
                  "这种强度小意思。（把护腕往下扯了扯）", ["几百个？你练傻了？"])
    win.set_affection(100)
    win.add_reply("……你又来这套。", [])
    win.set_affection(100, 2)          # 满 100 再加 -> 显示「已满」
    for _ in range(20):
        pet.root.update()
        time.sleep(0.02)

    from PIL import ImageGrab
    r = win.win
    x, y = r.winfo_rootx(), r.winfo_rooty()
    w, h = r.winfo_width(), r.winfo_height()
    shot = ImageGrab.grab()
    sc = shot.size[0] / float(pet.root.winfo_screenwidth())
    shot.crop((int(x * sc), int(y * sc),
               int((x + w) * sc), int((y + h) * sc))).save("affection_preview.png")
    print("saved", (w, h), "delta label:", repr(win.aff_delta_var.get()))
    pet.root.destroy()
finally:
    try:
        if os.path.exists(CFG):
            os.remove(CFG)
        if os.path.exists(BAK):
            shutil.move(BAK, CFG)
    except Exception:                       # noqa: BLE001
        pass
