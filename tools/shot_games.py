# -*- coding: utf-8 -*-
"""给四个小游戏各截一张图（不联网）。

用法：<DSH python> tools\\shot_games.py
输出：game_rps.png / game_guess.png / game_memory.png / game_mole.png
"""
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import desktop_pet as dp        # noqa: E402
import pet_games                # noqa: E402


def settle(pet, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pet.root.update()
        time.sleep(0.015)


def _blt_window(hwnd, w, h):
    """直接从窗口 DC BitBlt：抓到的是窗口自己画的像素，
    既不会混进搜狗工具条，也不会像 PrintWindow 那样把文字叠两遍。"""
    import ctypes
    from ctypes import wintypes
    from PIL import Image

    u = ctypes.windll.user32
    g = ctypes.windll.gdi32
    u.GetWindowDC.restype = wintypes.HDC
    u.GetWindowDC.argtypes = [wintypes.HWND]
    g.CreateCompatibleDC.restype = wintypes.HDC
    g.CreateCompatibleDC.argtypes = [wintypes.HDC]
    g.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    g.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    g.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    g.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int,
                         wintypes.DWORD]
    g.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, ctypes.c_uint,
                            ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p,
                            ctypes.c_uint]
    g.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    g.DeleteDC.argtypes = [wintypes.HDC]
    u.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]

    hdc = u.GetWindowDC(hwnd)
    mdc = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, w, h)
    g.SelectObject(mdc, bmp)
    g.BitBlt(mdc, 0, 0, w, h, hdc, 0, 0, 0x00CC0020)   # SRCCOPY

    class BMI(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint), ("biWidth", ctypes.c_long),
                    ("biHeight", ctypes.c_long), ("biPlanes", ctypes.c_ushort),
                    ("biBitCount", ctypes.c_ushort), ("biCompression", ctypes.c_uint),
                    ("biSizeImage", ctypes.c_uint), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", ctypes.c_uint),
                    ("biClrImportant", ctypes.c_uint)]
    bi = BMI(ctypes.sizeof(BMI), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    g.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    img = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1).copy()
    g.DeleteObject(bmp)
    g.DeleteDC(mdc)
    u.ReleaseDC(hwnd, hdc)
    return img


def grab(pet, game, name):
    """屏幕抓图再按比例裁窗口。

    截图前把窗口挪到固定的空位：输入法工具条是别的进程的顶层窗口，
    会正好压在新窗口的标题上，换个位置它就留在原地了。
    """
    from PIL import ImageGrab

    game.win.geometry("+140+80")
    end = time.monotonic() + 0.45
    while time.monotonic() < end:
        pet.root.update()
        time.sleep(0.02)

    shot = ImageGrab.grab()
    k = shot.size[0] / float(pet.root.winfo_screenwidth())
    sc = 1.0
    x, y = game.win.winfo_rootx(), game.win.winfo_rooty()
    box = (x * sc, y * sc, (x + game.W) * sc, (y + game.H) * sc)
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
    pet = dp.DesktopPet(use_ai=True, topmost=True, bubble=False)
    settle(pet, 0.5)
    pet.brain.api_key = "test"

    # 猜拳：赢一局，停在“你赢这局”的画面
    g = pet_games.open_game(pet, "rps")
    settle(pet, 0.5)
    orig = pet_games.random.choice
    pet_games.random.choice = lambda seq: "剪刀"
    g.play("石头")
    settle(pet, 0.4)
    g.play("石头")
    settle(pet, 0.8)
    pet_games.random.choice = orig
    grab(pet, g, "game_rps.png")
    g.close()

    # 猜数字：猜小了一次，停在“大了/小了”的画面
    g = pet_games.open_game(pet, "guess")
    settle(pet, 0.5)
    g.target = 42
    for d in "30":
        g.press(d)
    g.submit()
    for d in "60":
        g.press(d)
    g.submit()
    settle(pet, 0.3)
    grab(pet, g, "game_guess.png")
    g.close()

    # 翻牌：翻开一对 + 一张
    g = pet_games.open_game(pet, "memory")
    settle(pet, 0.5)
    pairs = {}
    for idx, sym in enumerate(g.symbols):
        pairs.setdefault(sym, []).append(idx)
    vals = list(pairs.values())
    for a, b in vals[:2]:
        g.flip(a)
        settle(pet, 0.2)
        g.flip(b)
        settle(pet, 0.4)
    g.flip(vals[2][0])
    settle(pet, 0.3)
    grab(pet, g, "game_memory.png")
    g.close()

    # 打地鼠：冒出三只，分数 7
    g = pet_games.open_game(pet, "mole")
    settle(pet, 0.5)
    g.score = 7
    g.c.itemconfigure(g.score_txt, text="得分 7")
    for hole in (1, 4, 7):
        g._spawn(hole)
    settle(pet, 0.55)
    grab(pet, g, "game_mole.png")
    g.close()

    pet.quit()
finally:
    try:
        if os.path.exists(CFG):
            os.remove(CFG)
        if os.path.exists(BAK):
            shutil.move(BAK, CFG)
    except Exception:                       # noqa: BLE001
        pass
