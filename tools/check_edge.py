# -*- coding: utf-8 -*-
"""边界情况自检：选项行显隐、关窗时回复迟到、切人设、超长输入。

用法：<DSH python> tools\\check_edge.py
（不联网：把 chat_with_options 换成本地假实现。）
检查项用英文名，避免 GBK 控制台打印 ♥/中文时报错。
"""
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import desktop_pet as dp  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print("  %-44s %s %s" % (name, "ok" if cond else "FAIL", detail))


def settle(pet, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pet.root.update()
        time.sleep(0.015)


def mapped(win):
    return [bool(b.winfo_ismapped()) for b in win.option_buttons]


CFG = dp.CONFIG_PATH
BAK = CFG + ".edge_bak"
if os.path.exists(CFG):
    shutil.copy2(CFG, BAK)
try:
    if os.path.exists(CFG):
        os.remove(CFG)
    pet = dp.DesktopPet(use_ai=True, topmost=True, bubble=True)
    settle(pet, 0.3)
    pet.brain.api_key = "test"
    pet.cfg.setdefault("personas", {})[pet.image_name] = "闷骚少年"
    pet._persona = None
    pet._apply_persona()
    pet.affection = 100
    pet.romance = False
    pet._stash_persona()
    pet.brain.chat_with_options = (
        lambda text, affection=0: ("还行吧", 0, ["一", "二", "三"], None))
    pet.open_chat()
    settle(pet, 0.4)
    win = pet.chat_win

    print("=== options row visibility ===")
    win.refresh_romance()
    settle(pet, 0.1)
    check("romance only at 100", mapped(win) == [True, False, False],
          str(mapped(win)))
    win.set_options(["只有一条"])
    settle(pet, 0.1)
    check("romance + 1 option", mapped(win) == [True, True, False],
          str(mapped(win)))
    win.set_options(["一二三四五六七八九十一二三四五六七八九十"])
    settle(pet, 0.1)
    check("long option wraps, no extra box",
          mapped(win) == [True, True, False], str(mapped(win)))
    win.set_options([])
    settle(pet, 0.1)
    check("empty options -> romance only",
          mapped(win) == [True, False, False], str(mapped(win)))

    print("=== romance ===")
    win._use_option(0)
    settle(pet, 0.2)
    check("clicked -> together", pet.romance is True, "")
    check("row hidden", mapped(win) == [False, False, False], str(mapped(win)))
    check("confession line in log",
          dp.ai_client.ROMANCE_LINE in win.log.get("1.0", "end"), "")
    win.set_options(["a", "b", "c"])
    settle(pet, 0.1)
    check("next turn: 3 options, no romance slot",
          mapped(win) == [True, True, True]
          and win.option_buttons[0].cget("text") == "a",
          str([b.cget("text") for b in win.option_buttons]))

    print("=== switch persona ===")
    win.switch_persona("话痨朋友", 30)
    settle(pet, 0.1)
    check("title follows persona", "黄世举" in win.win.title(), win.win.title())
    check("no romance slot for hsj", mapped(win)[0] is False, str(mapped(win)))

    print("=== long input ===")
    win.entry.insert(0, "长" * 800)
    try:
        win.submit()
        settle(pet, 0.8)
        check("800 chars no crash", True, "")
    except Exception as exc:                # noqa: BLE001
        check("800 chars no crash", False, repr(exc))

    print("=== late reply after close ===")
    win.cancel()
    settle(pet, 0.2)
    check("chat_win cleared", pet.chat_win is None, "")
    pet.brain.chat_with_options = (
        lambda text, affection=0: ("迟到的回复", 1, ["x", "y"], None))
    try:
        pet.ask_ai("还在吗")
        settle(pet, 1.4)
        check("late reply no crash", True, "")
        plan = getattr(pet.bubble, "_plan", None) or {}
        texts = [str(x) for x in (plan.get("lines") or [])]
        check("bubble shows late reply", any("迟到" in t for t in texts),
              str(texts))
    except Exception as exc:                # noqa: BLE001
        check("late reply no crash", False, repr(exc))

    print("=== forget chat ===")
    pet.open_chat()
    settle(pet, 0.4)
    win = pet.chat_win
    check("still together after reopen", pet.romance is True, "")
    check("no romance slot after reopen", mapped(win)[0] is False,
          str(mapped(win)))
    pet.forget_chat()
    settle(pet, 0.2)
    check("romance cleared", pet.romance is False, "")
    check("title without heart", "\u2665" not in win.win.title(), "")
    win.cancel()
    settle(pet, 0.2)

    print("=== chat window must not cover the pet ===")
    pet.ai_enabled = True
    pet.brain.api_key = pet.brain.api_key or "sk-test"
    pet.open_chat()
    settle(pet, 0.8)
    wr = pet._chat_rect()
    if wr is None:
        print("  chat window not open, skip")
    else:
        pr = (pet.win_x, pet.win_y, pet.win_x + pet.win_w, pet.win_y + pet.win_h)
        overlap = not (wr[2] <= pr[0] or wr[0] >= pr[2]
                       or wr[3] <= pr[1] or wr[1] >= pr[3])
        check("chat does not overlap pet", not overlap,
              "chat=%s pet=%s" % (wr, pr))
        pet.chat_win._close()
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

print("RESULT:", "OK" if ok else "FAILED")

