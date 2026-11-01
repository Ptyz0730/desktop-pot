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


def grab(pet, game, name):
    from PIL import ImageGrab
    shot = ImageGrab.grab()
    k = shot.size[0] / float(pet.root.winfo_screenwidth())
    sc = pet.root.winfo_fpixels("1i") / 96.0
    w, h = game.W, game.H
    box = (game.win.winfo_rootx() * sc, game.win.winfo_rooty() * sc,
           (game.win.winfo_rootx() + w) * sc,
           (game.win.winfo_rooty() + h) * sc)
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
