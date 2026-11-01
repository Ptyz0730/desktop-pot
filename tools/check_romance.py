# -*- coding: utf-8 -*-
"""恋爱选项：好感度 100 + 陈瀚铭 -> 出现「♡ 恋爱」；点它说"前辈请与我交往吧"。

只会动测试用的临时配置：跑完把用户原来的 pet_config.json 原样放回去。
"""
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import ai_client  # noqa: E402
import desktop_pet as dp  # noqa: E402

ok = True


def out(line):
    """控制台是 GBK，♡ 这类字符打不出来：换成 ? 也要把这一行打出来。"""
    try:
        sys.stdout.write(line + "\n")
    except UnicodeEncodeError:
        sys.stdout.write(line.encode("gbk", "replace").decode("gbk") + "\n")
    sys.stdout.flush()


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    out("%-48s %s %s" % (name, "ok" if cond else "FAIL", detail))


def settle(pet, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pet.root.update()
        time.sleep(0.015)


def texts(win):
    return [b.cget("text") for b in win.option_buttons]


CFG = dp.CONFIG_PATH
BAK = CFG + ".romance_bak"
if os.path.exists(CFG):
    shutil.copy2(CFG, BAK)
try:
    if os.path.exists(CFG):
        os.remove(CFG)

    pet = dp.DesktopPet(use_ai=True, topmost=True, bubble=True)
    settle(pet, 0.4)
    pet.brain.api_key = "test"          # 只要能开窗；不发请求

    # 当前这张图 = 闷骚少年（陈瀚铭）
    pet.cfg.setdefault("personas", {})[pet.image_name] = "闷骚少年"
    pet._persona = None
    pet._apply_persona()
    pet.affection = 99
    pet.romance = False
    pet._stash_persona()

    out("=== 好感度 100 + 陈瀚铭 ===")
    pet.open_chat()
    settle(pet, 0.3)
    win = pet.chat_win
    check("聊天窗口开起来了", win is not None and win.win is not None)
    win.set_options(["嗯嗯，然后呢？", "我在听", "说下去"])
    settle(pet, 0.1)
    check("好感度 99：没有恋爱选项",
          all(win.ROMANCE_OPTION not in t for t in texts(win)), str(texts(win)))

    # 好感度在窗口开着的时候涨到 100 —— 选项要自己冒出来
    pet._apply_affection(1)
    settle(pet, 0.15)
    check("好感度到 100", pet.affection == 100, str(pet.affection))
    check("恋爱选项出现了", texts(win)[0] == win.ROMANCE_OPTION, str(texts(win)))
    check("恋爱选项可点", str(win.option_buttons[0].cget("state")) == "normal")
    check("点恋爱之前还没在一起", pet.romance is False)

    out("=== 点「♡ 恋爱」 ===")
    win._use_option(0)
    settle(pet, 0.3)
    log = win.log.get("1.0", "end")
    check("聊天记录里有告白台词", "前辈请与我交往吧" in log,
          repr(log.strip().splitlines()[-1] if log.strip() else ""))
    bubble_lines = "".join((pet.bubble._plan or {}).get("lines") or []) \
        if pet.bubble is not None else ""
    check("气泡说的也是这句", "前辈请与我交往吧" in bubble_lines, bubble_lines[:40])
    check("进入恋人状态", pet.romance is True)
    check("恋人版提示词生效", ai_client.ROMANCE_SUFFIX in pet.brain.system_prompt)
    check("恋爱选项用一次就收起来",
          all(t != win.ROMANCE_OPTION for t in texts(win)), str(texts(win)))
    saved = {}
    if os.path.exists(CFG):
        try:
            saved = json.load(open(CFG, encoding="utf-8-sig"))
        except Exception:                   # noqa: BLE001
            saved = {}
    slot = (saved.get("chats") or {}).get("闷骚少年") or {}
    check("恋爱状态写进了配置", slot.get("romance") is True, str(slot.get("romance")))

    out("=== 重开一次（从配置读回来） ===")
    pet.romance = False
    pet._persona = None
    pet._apply_persona(load=True)
    settle(pet, 0.2)
    check("启动后还是恋人", pet.romance is True)
    check("启动后提示词也是恋人版",
          ai_client.ROMANCE_SUFFIX in pet.brain.system_prompt)

    out("=== 换成人设：黄世举（不能恋爱） ===")
    pet.cfg.setdefault("personas", {})[pet.image_name] = "话痨朋友"
    pet._persona = None
    pet._apply_persona()
    settle(pet, 0.2)
    pet.affection = 100
    pet._stash_persona()
    win.refresh_romance()
    settle(pet, 0.1)
    check("黄世举：好感度满也没有恋爱选项",
          all(win.ROMANCE_OPTION not in t for t in texts(win)), str(texts(win)))
    check("黄世举：不算恋人", pet.romance is False)

    win.cancel()
    settle(pet, 0.2)
    pet.quit()
finally:
    # 用户原来的配置放回去（测试期间写的那份丢掉）
    try:
        if os.path.exists(CFG):
            os.remove(CFG)
        if os.path.exists(BAK):
            shutil.move(BAK, CFG)
    except Exception:                       # noqa: BLE001
        pass

print("RESULT:", "OK" if ok else "FAILED")
