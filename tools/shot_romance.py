# -*- coding: utf-8 -*-
"""给"好感度 100 + 陈瀚铭"的聊天窗截一张图，看「♡ 恋爱」选项长什么样。"""
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import ctypes.wintypes  # noqa: E402
import desktop_pet as dp  # noqa: E402


def settle(pet, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pet.root.update()
        time.sleep(0.015)


def grab(box, path, screen_logical_w):
    """整屏抓（物理像素），再按 物理/逻辑 比例裁出窗口那块。"""
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
    pet.affection = 100
    pet.romance = False
    pet._stash_persona()
    pet.open_chat()
    settle(pet, 0.5)
    win = pet.chat_win
    win.set_options(["嗯嗯，然后呢？", "我在听，你继续", "说下去"])
    win._append("前辈，今天怎么这么晚还在？", "pet")
    win.win.lift()
    win.win.deiconify()
    settle(pet, 0.6)
    import ctypes
    u = ctypes.windll.user32
    hwnd = u.GetParent(win.win.winfo_id()) or win.win.winfo_id()
    r = ctypes.wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    print("hwnd", hwnd, "visible", u.IsWindowVisible(hwnd),
          "state", win.win.state(), "viewable", win.win.winfo_viewable(),
          "rect", (r.left, r.top, r.right, r.bottom),
          "topmost", win.win.attributes("-topmost"))
    scale = pet.root.winfo_fpixels("1i") / 96.0
    sc = pet.root.winfo_fpixels("1i") / 96.0
    box = (int(win.win.winfo_rootx() * sc), int(win.win.winfo_rooty() * sc),
           int((win.win.winfo_rootx() + win.W) * sc),
           int((win.win.winfo_rooty() + win.H) * sc))
    print("box", box, "size", win.W, win.H)
    print("saved", grab(box, os.path.join(ROOT, "romance_preview.png"),
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
