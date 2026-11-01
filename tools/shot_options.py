# -*- coding: utf-8 -*-
"""截一张真接口跑出来的对话窗：看三个选项是不是"贴着这句话"写的。

用法：<DSH python> tools\\shot_options.py
输出：options_preview.png
"""
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import ctypes  # noqa: E402
import ctypes.wintypes  # noqa: E402

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
    pet.brain.api_key = dp.BUILTIN_API_KEY
    pet.cfg.setdefault("personas", {})[pet.image_name] = "闷骚少年"
    pet._persona = None
    pet._apply_persona()
    pet.affection = 45
    pet.romance = False
    pet._stash_persona()
    pet.open_chat()
    settle(pet, 0.4)
    win = pet.chat_win
    win.win.lift()
    win.win.deiconify()
    win.entry.insert(0, "今天训练累不累")
    win.submit()
    deadline = time.monotonic() + 30
    while "chat" in pet._ai_lanes and time.monotonic() < deadline:
        settle(pet, 0.2)
    settle(pet, 1.0)
    print("options:", [b.cget("text") for b in win.option_buttons])
    u = ctypes.windll.user32
    hwnd = u.GetParent(win.win.winfo_id()) or win.win.winfo_id()
    r = ctypes.wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    print("rect", (r.left, r.top, r.right, r.bottom))
    sc = pet.root.winfo_fpixels("1i") / 96.0
    box = (int(win.win.winfo_rootx() * sc), int(win.win.winfo_rooty() * sc),
           int((win.win.winfo_rootx() + win.W) * sc),
           int((win.win.winfo_rooty() + win.H) * sc))
    print("saved", grab(box, os.path.join(ROOT, "options_preview.png"),
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
