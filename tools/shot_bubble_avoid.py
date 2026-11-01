# -*- coding: utf-8 -*-
"""截图验证：聊天窗开着时，气泡会不会躲开窗口（不盖住输入框/发送键）。"""
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import desktop_pet as dp  # noqa: E402


def settle(pet, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pet.root.update()
        time.sleep(0.015)


def grab(box, path, screen_logical_w):
    from PIL import ImageGrab
    shot = ImageGrab.grab()
    k = shot.size[0] / float(screen_logical_w)
    x0, y0, x1, y1 = [int(round(v * k)) for v in box]
    shot.crop((x0, y0, x1, y1)).save(path)
    return shot.size, k


CFG = dp.CONFIG_PATH
BAK = CFG + ".shot_bak"
if os.path.exists(CFG):
    shutil.copy2(CFG, BAK)
try:
    if os.path.exists(CFG):
        os.remove(CFG)
    pet = dp.DesktopPet(use_ai=True, topmost=True, bubble=True)
    settle(pet, 0.4)
    pet.brain.api_key = "test"
    pet.cfg.setdefault("personas", {})[pet.image_name] = "闷骚少年"
    pet._persona = None
    pet._apply_persona()
    pet.affection = 60
    pet._stash_persona()
    pet.open_chat()
    settle(pet, 0.5)
    win = pet.chat_win
    win._append("今天训练累不累", "me")
    pet.speak("还行吧，就是手有点酸。")
    settle(pet, 0.6)
    rect = pet._chat_rect()
    plan = pet.bubble._plan or {}
    print("chat rect", rect)
    print("bubble rect", (plan.get("x"), plan.get("y"), plan.get("w"), plan.get("h")))
    print("overlap", dp._rect_hit(plan.get("x", 0), plan.get("y", 0),
                                  plan.get("w", 0), plan.get("h", 0), rect)
          if rect and plan else "n/a")
    box = (0, 0, pet.root.winfo_screenwidth(), pet.root.winfo_screenheight())
    print("saved", grab(box, os.path.join(ROOT, "bubble_avoid.png"),
                        pet.root.winfo_screenwidth()))
    win.cancel()
    settle(pet, 0.2)
    pet.quit()
finally:
    try:
        if os.path.exists(CFG):
            os.remove(CFG)
        if os.path.exists(BAK):
            shutil.move(BAK, CFG)
    except Exception:                       # noqa: BLE001
        pass
