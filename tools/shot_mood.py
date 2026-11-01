# -*- coding: utf-8 -*-
"""给「吃醋 / 冷战 / 撤回」各截一张聊天窗图（不联网，假回复）。

用法：<DSH python> tools\\shot_mood.py
输出：mood_jealous.png / mood_cold.png / mood_withdraw.png（项目根目录）
"""
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


def grab(pet, win, name):
    from PIL import ImageGrab
    shot = ImageGrab.grab()
    k = shot.size[0] / float(pet.root.winfo_screenwidth())
    sc = pet.root.winfo_fpixels("1i") / 96.0
    box = (int(win.win.winfo_rootx() * sc), int(win.win.winfo_rooty() * sc),
           int((win.win.winfo_rootx() + win.W) * sc),
           int((win.win.winfo_rooty() + win.H) * sc))
    path = os.path.join(ROOT, name)
    shot.crop(tuple(int(round(v * k)) for v in box)).save(path)
    print("saved", path)
    return path


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
    pet.brain.chat_with_options = (
        lambda text, affection=0: ("（手指在屏幕上停了半拍）哦，他谁啊，跟我说说呗，"
                                   "我也认识认识", 3,
                                   ["就随口一说，你比他帅", "吃醋啦？", "不许阴阳怪气"], None))
    pet.open_chat()
    settle(pet, 0.5)
    win = pet.chat_win
    win.add_reply("今天在学校看到一个人打球，挺帅的。", [])
    win._had_reply = True

    win._send("他好帅啊")
    settle(pet, 1.0)
    win.win.lift()
    settle(pet, 0.4)
    grab(pet, win, "mood_jealous.png")

    print("state:", pet.mood.state, "| log tail:",
          win.log.get("1.0", "end").strip().splitlines()[-1])
    win._send("哦")
    settle(pet, 1.0)
    print("state:", pet.mood.state, "| log tail:",
          win.log.get("1.0", "end").strip().splitlines()[-1])
    grab(pet, win, "mood_cold.png")

    win.add_reply("……", [])
    settle(pet, 0.2)
    win.withdraw_last(delay_ms=0)
    settle(pet, 0.6)
    grab(pet, win, "mood_withdraw.png")
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
