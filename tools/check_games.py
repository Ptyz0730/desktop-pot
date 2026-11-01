# -*- coding: utf-8 -*-
"""小游戏自检（不联网）。

用法：<DSH python> tools\\check_games.py
覆盖：菜单入口、猜拳结算、猜数字提示、翻牌配对、打地鼠点击计分、
      窗口不压住宠物、成绩写进配置、关窗不留定时器。
"""
import json
import os
import random
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import desktop_pet as dp        # noqa: E402
import pet_games                # noqa: E402

OK = True


def check(name, cond, detail=""):
    global OK
    if cond:
        print("ok   -", name)
    else:
        OK = False
        print("FAIL -", name, ("| " + str(detail)) if detail else "")


def settle(pet, seconds=0.15):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pet.root.update()
        time.sleep(0.01)


class FakeEvent:
    def __init__(self, x, y):
        self.x = x
        self.y = y


CFG = dp.CONFIG_PATH
BAK = CFG + ".games_bak"
if os.path.exists(CFG):
    shutil.copy2(CFG, BAK)

try:
    if os.path.exists(CFG):
        os.remove(CFG)
    pet = dp.DesktopPet(use_ai=True, topmost=True, bubble=False)
    pet.brain.api_key = "test"
    settle(pet, 0.3)

    # ---------------------------------------------------------------- 菜单
    labels = []
    menu = pet.menu
    for i in range(menu.index("end") + 1):
        try:
            if menu.type(i) == "cascade":
                labels.append(menu.entrycget(i, "label"))
        except Exception:                       # noqa: BLE001
            pass
    check("右键菜单里有「小游戏」", "小游戏" in labels, labels)
    game_menu = pet._game_menu
    items = [game_menu.entrycget(i, "label")
             for i in range(game_menu.index("end") + 1)
             if game_menu.type(i) == "command"]
    check("四个小游戏都在", len(items) == 5, items)
    check("有成绩行", "成绩" in items[-1], items[-1])

    # ---------------------------------------------------------------- 猜拳
    g = pet_games.open_game(pet, "rps")
    settle(pet, 0.1)
    check("猜拳窗口打开", g.win is not None and g.win.winfo_exists())
    check("窗口标题带人设", "猜拳" in g.win.title(), g.win.title())
    aff0 = pet.affection
    orig_choice = pet_games.random.choice
    pet_games.random.choice = lambda seq: "剪刀"    # 它总出剪刀，石头赢
    g.play("石头")
    g.play("石头")
    pet_games.random.choice = orig_choice
    check("猜拳两胜就结束", g.done and g.you == 2, (g.you, g.it, g.done))
    check("猜拳赢了加好感", pet.affection == min(100, aff0 + 1),
          (aff0, pet.affection))
    check("猜拳「再来一局」可用", str(g.again.cget("state")) == "normal")
    g.reset()
    check("猜拳能重开", (g.you, g.it, g.done) == (0, 0, False))
    g.close()
    check("猜拳窗口能关", g.win is None)

    # ---------------------------------------------------------------- 猜数字
    g = pet_games.open_game(pet, "guess")
    settle(pet, 0.1)
    g.target = 42
    g.entry.insert(0, "41")
    g.guess()
    check("猜小了会提示", "小" in g.state_var.get(), g.state_var.get())
    g.entry.insert(0, "43")
    g.guess()
    check("猜大了会提示", "大" in g.state_var.get(), g.state_var.get())
    g.entry.insert(0, "42")
    g.guess()
    check("猜对了会结束", g.done)
    check("三次以内加 2", g._awarded == 2, g._awarded)
    check("记了最好成绩", pet.cfg["games"].get("guess_best") == 3,
          pet.cfg["games"].get("guess_best"))
    g.entry.insert(0, "abc")
    g.done = False
    g.guess()
    check("乱填不崩", "整数" in g.state_var.get(), g.state_var.get())
    g.close()

    # ---------------------------------------------------------------- 翻牌
    g = pet_games.open_game(pet, "memory")
    settle(pet, 0.1)
    pairs = {}
    for idx, sym in enumerate(g.symbols):
        pairs.setdefault(sym, []).append(idx)
    for a, b in pairs.values():
        g.flip(a)
        g.flip(b)
    settle(pet, 0.05)
    check("翻牌能全配对", g.done and len(g.matched) == 12,
          (g.done, len(g.matched)))
    check("翻牌给了好感", g._awarded >= 1, g._awarded)
    check("翻牌记成绩", pet.cfg["games"].get("memory_best") == 6,
          pet.cfg["games"].get("memory_best"))
    g.close()

    # ---------------------------------------------------------------- 打地鼠
    g = pet_games.open_game(pet, "mole")
    settle(pet, 0.1)
    g._pop()
    idx = g.mole[0]
    cx, cy = g.holes[idx]
    g.on_click(FakeEvent(cx, cy))
    check("点中地鼠加分", g.score == 1, g.score)
    g.score = 16
    g._finish()
    check("打地鼠高分加 2", g._awarded == 2, g._awarded)
    check("打地鼠记成绩", pet.cfg["games"].get("mole_best") == 16,
          pet.cfg["games"].get("mole_best"))
    g.reset()
    check("打地鼠能重开", g.score == 0 and not g.done, (g.score, g.done))
    g.close()
    settle(pet, 0.4)
    check("关窗后定时器不再报错", g.win is None)

    # ---------------------------------------------------------------- 摆位
    g = pet_games.open_game(pet, "rps")
    settle(pet, 0.1)
    left, top, right, bottom = dp.work_area(pet.root)
    geo = g.win.geometry()
    size, x, y = geo.split("+")[0], int(geo.split("+")[1]), int(geo.split("+")[2])
    w, h = (int(v) for v in size.split("x"))
    check("窗口在屏幕内", left <= x and x + w <= right and
          top <= y and y + h <= bottom, geo)
    check("窗口没压住宠物", y + h <= pet.win_y or y >= pet.win_y + pet.win_h
          or x + w <= pet.win_x or x >= pet.win_x + pet.win_w, geo)
    g.close()

    # ---------------------------------------------------------------- 落盘
    pet._save_config()
    with open(CFG, encoding="utf-8") as fh:
        saved = json.load(fh)
    check("成绩写进配置", isinstance(saved.get("games"), dict)
          and saved["games"].get("mole_best") == 16, saved.get("games"))
    pet._refresh_game_stats()
    check("菜单成绩行会更新", "打地鼠 16" in pet._game_menu.entrycget(
        pet._games_stats_index, "label"),
        pet._game_menu.entrycget(pet._games_stats_index, "label"))

    pet.quit()
finally:
    try:
        if os.path.exists(CFG):
            os.remove(CFG)
        if os.path.exists(BAK):
            shutil.move(BAK, CFG)
    except Exception:                           # noqa: BLE001
        pass

print("RESULT:", "OK" if OK else "FAILED")
sys.exit(0 if OK else 1)
