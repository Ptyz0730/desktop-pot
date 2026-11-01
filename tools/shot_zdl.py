# -*- coding: utf-8 -*-
"""给郑迪隆截两张图：聊天窗（日语 + 中文翻译）和桌面立绘。

用法：<DSH python> tools\\shot_zdl.py
输出：zdl_chat.png / zdl_desktop.png（项目根目录）
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


def grab(pet, name, pad=0):
    from PIL import ImageGrab
    shot = ImageGrab.grab()
    root = pet.root
    k = shot.size[0] / float(root.winfo_screenwidth())
    sc = root.winfo_fpixels("1i") / 96.0
    x, y = pet.win_x, pet.win_y
    w, h = pet.win_w, pet.win_h
    print("pet window:", w, "x", h, "at", x, y)
    box = ((x - pad) * sc, (y - pad) * sc,
           (x + w + pad) * sc, (y + h + pad) * sc)
    path = os.path.join(ROOT, name)
    shot.crop(tuple(int(round(v * k)) for v in box)).save(path)
    print("saved", path)
    return path


def grab_chat(pet, win, name):
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
    pet = dp.DesktopPet(use_ai=True, topmost=True, bubble=True, style="colorkey")
    settle(pet, 0.4)
    pet.brain.api_key = "test"
    pet.set_image("郑迪隆.png")
    settle(pet, 0.5)
    pet.cfg.setdefault("personas", {})[pet.image_name] = "骚话少年"
    pet._persona = None
    pet._apply_persona()
    pet.set_affection(52)
    settle(pet, 4.0)          # 等 set_image 那句气泡自己消失

    # 摸头弹幕：郑迪隆的日语一行 + 中文一行（先截，别让气泡压住）
    end = time.monotonic() + 2.0
    last = time.monotonic()
    while time.monotonic() < end:
        pet.root.update()
        now = time.monotonic()
        pet.danmaku.update(now - last, pet.head_anchor(), True, time.time())
        last = now
        time.sleep(0.015)
    items = [(getattr(it, "jp", None), getattr(it, "cn", None)) for it in pet.danmaku.items]
    print("danmaku items:", items)
    grab(pet, "zdl_danmaku.png", pad=60)
    pet.danmaku.clear()
    settle(pet, 0.3)

    # 桌面立绘：连气泡一起截（气泡里正好是带翻译的日语）
    pet.speak("（手指在桌上敲了两下）気持ちいい")
    settle(pet, 0.9)
    grab(pet, "zdl_desktop.png", pad=24)

    # 聊天窗：一句日语骚话 + 一句中文翻译
    pet.brain.chat_with_options = (
        lambda text, affection=0: ("（说完就低头看手机）気持ちいい（好舒服啊）", 2,
                                   ["你日语跟谁学的？", "听不懂，再说一遍",
                                    "别装没事，脸都红了"], None))
    pet.open_chat()
    settle(pet, 0.5)
    win = pet.chat_win
    win.add_reply("今天食堂的饭気持ちいい", [])
    win._had_reply = True
    win._send("你又在说日语")
    settle(pet, 1.0)
    win.win.lift()
    settle(pet, 0.4)
    grab_chat(pet, win, "zdl_chat.png")
    print("log tail:", win.log.get("1.0", "end").strip().splitlines()[-3:])
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
