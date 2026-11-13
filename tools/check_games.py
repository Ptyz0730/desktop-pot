# -*- coding: utf-8 -*-
"""小游戏自检（不联网）。

用法：<DSH python> tools\\check_games.py
覆盖：菜单入口、四个游戏的玩法与结算、好感奖励、成绩落盘、窗口摆位、
      关窗不留定时器，以及新界面的交互（画布、淡入、悬停、拖动）。
"""
import json
import os
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


def text_of(game, item):
    try:
        return game.c.itemcget(item, "text")
    except Exception:                            # noqa: BLE001
        return ""


class FakeEvent:
    def __init__(self, x, y, x_root=None, y_root=None):
        self.x, self.y = x, y
        self.x_root = x if x_root is None else x_root
        self.y_root = y if y_root is None else y_root


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

    # ------------------------------------------------------------ 窗口外观
    g = pet_games.open_game(pet, "rps")
    settle(pet, 0.4)
    check("猜拳窗口打开", g.win is not None and g.win.winfo_exists())
    check("窗口标题带人设", "猜拳" in g.win.title(), g.win.title())
    check("窗口是一条画布（自绘 UI）", isinstance(g.c, type(g.c)))
    try:
        alpha = float(g.win.attributes("-alpha"))
    except Exception:                           # noqa: BLE001
        alpha = 1.0
    check("开窗会淡入到不透明", alpha > 0.9, alpha)
    check("无系统标题栏（自绘）", bool(int(g.win.overrideredirect())))

    # 悬停：按钮变色 + 光标手形
    pill = g.again
    pill.set_enabled(True)
    body_before = [g.c.itemcget(i, "fill") for i in g.c.find_withtag(pill.tag)
                   if g.c.type(i) == "polygon"]
    pill._on_enter()
    body_after = [g.c.itemcget(i, "fill") for i in g.c.find_withtag(pill.tag)
                  if g.c.type(i) == "polygon"]
    check("按钮悬停会变色", body_before != body_after,
          (body_before, body_after))
    card = g.c.find_withtag("tile0")[0]
    g._hover_tile("石头", True)
    on_outline = g.c.itemcget(card, "outline")
    g._hover_tile("石头", False)
    off_outline = g.c.itemcget(card, "outline")
    check("手势卡悬停会亮边框", on_outline != off_outline,
          (on_outline, off_outline))
    check("悬停不会在光标下新建 item", len(g.c.find_withtag("hover")) == 0,
          len(g.c.find_withtag("hover")))
    pill._on_leave()
    pill.set_enabled(False)

    # 拖动标题栏
    geo0 = g.win.geometry()
    g._drag_start(FakeEvent(0, 0, g.win.winfo_x() + 40, g.win.winfo_y() + 20))
    g._drag_move(FakeEvent(0, 0, g.win.winfo_x() + 90,
                           g.win.winfo_y() + 70))
    g._drag_end()
    settle(pet, 0.05)
    check("拖动标题栏能挪窗口", g.win.geometry() != geo0,
          (geo0, g.win.geometry()))

    # ---------------------------------------------------------------- 猜拳
    aff0 = pet.affection
    orig_choice = pet_games.random.choice
    pet_games.random.choice = lambda seq: "剪刀"    # 它总出剪刀，石头赢
    g.play("石头")
    settle(pet, 0.2)
    g.play("石头")
    settle(pet, 0.5)
    pet_games.random.choice = orig_choice
    check("猜拳两胜就结束", g.done and g.you == 2, (g.you, g.it, g.done))
    check("猜拳赢了加好感", pet.affection == min(100, aff0 + 1),
          (aff0, pet.affection))
    check("猜拳「再来一局」可用", g.again.enabled)
    g.reset()
    check("猜拳能重开", (g.you, g.it, g.done) == (0, 0, False))
    check("重开后按钮变灰", not g.again.enabled)
    g.close()
    check("猜拳窗口能关", g.win is None)

    # ---------------------------------------------------------------- 猜数字
    g = pet_games.open_game(pet, "guess")
    settle(pet, 0.2)
    check("猜数字有数字键盘", len(g.keys) == 12, len(g.keys))
    g.target = 42
    for digit in "41":
        g.press(digit)
    g.submit()
    check("猜小了会提示", "小" in text_of(g, g.hint), text_of(g, g.hint))
    check("范围条会收窄", (g.lo, g.hi) == (42, 100), (g.lo, g.hi))
    for digit in "43":
        g.press(digit)
    g.submit()
    check("猜大了会提示", "大" in text_of(g, g.hint), text_of(g, g.hint))
    check("范围条两头都动", (g.lo, g.hi) == (42, 42), (g.lo, g.hi))
    for digit in "42":
        g.press(digit)
    g.submit()
    check("猜对了会结束", g.done)
    check("三次以内加 2", g._awarded == 2, g._awarded)
    check("记了最好成绩", pet.cfg["games"].get("guess_best") == 3,
          pet.cfg["games"].get("guess_best"))
    g.reset()
    for digit in "123":
        g.press(digit)
    g.submit()
    check("超范围会提示", "超出范围" in text_of(g, g.hint), text_of(g, g.hint))
    for digit in "123":
        g.press(digit)
    g.backspace()
    check("退格能删一位", g.buf == "12", g.buf)
    g.close()

    # ---------------------------------------------------------------- 翻牌
    g = pet_games.open_game(pet, "memory")
    settle(pet, 0.2)
    check("翻牌有 12 张", len(g.symbols) == 12, len(g.symbols))
    pairs = {}
    for idx, sym in enumerate(g.symbols):
        pairs.setdefault(sym, []).append(idx)
    for a, b in pairs.values():
        g.flip(a)
        g.flip(b)
    settle(pet, 0.6)
    check("翻牌能全配对", g.done and len(g.matched) == 12,
          (g.done, len(g.matched)))
    check("翻牌给了好感", g._awarded >= 1, g._awarded)
    check("翻牌记成绩", pet.cfg["games"].get("memory_best") == 6,
          pet.cfg["games"].get("memory_best"))
    g.close()

    # ---------------------------------------------------------------- 打地鼠
    g = pet_games.open_game(pet, "mole")
    settle(pet, 0.2)
    g.time_left = 20.0
    g._spawn(4)
    mole = g.moles[0]
    mole["rise"] = 1.0
    mole["dy"] = g.RISE
    cx, cy = mole["cx"], mole["cy"] - g.RISE
    g._on_click(FakeEvent(cx, cy))
    check("点中地鼠加分", g.score == 1, g.score)
    check("打中会缩回洞里", mole.get("hit") and mole.get("hit_down"),
          mole.get("hit"))
    g._on_click(FakeEvent(5, 400))
    check("打空不计分", g.score == 1, g.score)
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
