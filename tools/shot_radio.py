# -*- coding: utf-8 -*-
"""截在线电台窗口 + 弹幕贴边效果（不真的放台，避免等 25 秒）。

用法：<DSH python> tools\\shot_radio.py
输出：radio_dialog.png / danmaku_edge.png
"""
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import desktop_pet as dp        # noqa: E402


def settle(pet, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pet.root.update()
        time.sleep(0.015)


def grab_win(pet, win, w, h, name):
    from PIL import ImageGrab
    shot = ImageGrab.grab()
    k = shot.size[0] / float(pet.root.winfo_screenwidth())
    sc = pet.root.winfo_fpixels("1i") / 96.0
    x, y = win.winfo_rootx(), win.winfo_rooty()
    box = (x * sc, y * sc, (x + w) * sc, (y + h) * sc)
    path = os.path.join(ROOT, name)
    shot.crop(tuple(int(round(v * k)) for v in box)).save(path)
    print("saved", path)
    return path


def grab_region(pet, x, y, w, h, name, pad=16):
    from PIL import ImageGrab
    shot = ImageGrab.grab()
    k = shot.size[0] / float(pet.root.winfo_screenwidth())
    sc = pet.root.winfo_fpixels("1i") / 96.0
    box = ((x - pad) * sc, (y - pad) * sc, (x + w + pad) * sc, (y + h + pad) * sc)
    path = os.path.join(ROOT, name)
    shot.crop(tuple(int(round(v * k)) for v in box)).save(path)
    print("saved", path)
    return path


CFG = dp.CONFIG_PATH
BAK = CFG + ".shot_radio_bak"
if os.path.exists(CFG):
    shutil.copy2(CFG, BAK)
try:
    if os.path.exists(CFG):
        os.remove(CFG)
    pet = dp.DesktopPet(use_ai=False, topmost=True, bubble=True, style="colorkey")
    settle(pet, 0.8)

    # --- 电台窗口：塞几个假的台进去，避免联网等结果
    pet.open_radio()
    dlg = pet._radio_dialog
    stations = [
        {"name": "中国之声", "url": "https://lhttp.qtfm.cn/live/15318317/64k.mp3",
         "tags": "news", "codec": "MP3", "bitrate": 64},
        {"name": "怀集音乐之声", "url": "https://lhttp.qingting.fm/live/4804/64k.mp3",
         "tags": "music", "codec": "MP3", "bitrate": 64},
        {"name": "清晨音乐台", "url": "http://lhttp.qingting.fm/live/4915/64k.mp3",
         "tags": "music", "codec": "MP3", "bitrate": 64},
        {"name": "SomaFM Groove Salad", "url": "http://ice1.somafm.com/groovesalad-128-mp3",
         "tags": "chill", "codec": "MP3", "bitrate": 128},
    ]
    if dlg is not None and hasattr(dlg, "win"):
        dlg._seq = getattr(dlg, "_seq", 0) + 1
        dlg._done(dlg._seq, stations)
        settle(pet, 0.6)
        w = dlg.win.winfo_width() or 420
        h = dlg.win.winfo_height() or 480
        grab_win(pet, dlg.win, w, h, "radio_dialog.png")
        dlg.close()
        settle(pet, 0.3)

    # --- 弹幕贴边：把宠物挪到屏幕最左边，摸头，等字冒出来
    pet.win_x = 0
    pet.root.geometry("+%d+%d" % (pet.win_x, pet.win_y))
    settle(pet, 0.3)
    settle(pet, 0.4)
    pet.petting_until = time.time() + 12
    now = time.time()
    for _i in range(90):
        pet.danmaku.update(0.05, pet.head_anchor(), True, time.time())
        pet.root.update()
        time.sleep(0.016)
        if pet.danmaku.items:
            break
    for _i in range(8):
        pet.danmaku.update(0.05, pet.head_anchor(), True, time.time())
        pet.root.update()
        time.sleep(0.02)
    head = pet.head_anchor()
    grab_region(pet, pet.win_x, int(head[1]) - 200, pet.win_w, 380,
                "danmaku_edge.png", pad=10)
    pet.quit()
finally:
    if os.path.exists(BAK):
        shutil.copy2(BAK, CFG)
        os.remove(BAK)
    elif os.path.exists(CFG):
        os.remove(CFG)
