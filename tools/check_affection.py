# -*- coding: utf-8 -*-
"""好感度到底会不会变：真接口连聊几轮，打印每轮的 delta 和存盘结果。

用法：<DSH python> tools\\check_affection.py
"""
import io
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


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print("  %-40s %s %s" % (name, "ok" if cond else "FAIL", detail))


CFG = dp.CONFIG_PATH
BAK = CFG + ".aff_bak"
if os.path.exists(CFG):
    shutil.copy2(CFG, BAK)
try:
    if os.path.exists(CFG):
        os.remove(CFG)
    brain = ai_client.PetBrain(api_key=dp.BUILTIN_API_KEY)
    brain.persona = "闷骚少年"
    brain.system_prompt = ai_client.persona_prompt("闷骚少年")
    print("=== 直接问模型（3 轮） ===")
    affection = 30
    lines = ["今天训练累不累", "我给你带了水", "那明天一起去看电影吧"]
    deltas = []
    for text in lines:
        reply, delta, options, err = brain.chat_with_options(text, affection)
        deltas.append(delta)
        print("  user=%s" % text)
        print("  reply=%s" % reply[:40])
        print("  delta=%r options=%d err=%r" % (delta, len(options), err))
        affection = max(0, min(100, affection + int(delta)))
        print("  affection -> %d" % affection)
    check("每轮都有非 0 变化", all(int(d) != 0 for d in deltas), str(deltas))
    check("好感度确实在涨", affection > 30, "30 -> %d" % affection)

    print("=== 兜底 delta 分类 ===")
    cases = {"哦": 0, "嗯嗯": 0, "随便": 0, "滚": -2, "你真笨": -2,
             "今天训练累不累": 2}
    for text, want in cases.items():
        got = ai_client.fallback_affection_delta(text)
        check("fallback %r -> %r" % (text, want), got == want, "got %r" % got)

    print("=== 聊天窗口里的变化量提示 ===")
    pet = dp.DesktopPet(use_ai=True, topmost=False, bubble=True)
    time.sleep(0.3)
    pet.brain.api_key = dp.BUILTIN_API_KEY
    pet.cfg.setdefault("personas", {})[pet.image_name] = "闷骚少年"
    pet._persona = None
    pet._apply_persona()
    pet.open_chat()
    deadline = time.monotonic() + 3
    while pet.chat_win is None and time.monotonic() < deadline:
        pet.root.update()
        time.sleep(0.02)
    win = pet.chat_win
    check("聊天窗口开出来了", win is not None)
    pet.set_affection(100)
    win.set_affection(100, 2)
    pet.root.update()
    check("满 100 再加显示「已满」", win.aff_delta_var.get() == "已满",
          repr(win.aff_delta_var.get()))
    win.set_affection(100, -2)
    pet.root.update()
    check("掉分显示负数", win.aff_delta_var.get() == "-2",
          repr(win.aff_delta_var.get()))
    win.set_affection(50, 3)
    pet.root.update()
    check("加分显示 +3", win.aff_delta_var.get() == "+3",
          repr(win.aff_delta_var.get()))
    end = time.monotonic() + 2.5
    while time.monotonic() < end:
        pet.root.update()
        time.sleep(0.05)
    check("1.6 秒后自己消失", win.aff_delta_var.get() == "",
          repr(win.aff_delta_var.get()))

    print("=== 满 100 时真聊一轮（不涨也不出错） ===")
    pet.set_affection(100)
    before = pet.affection
    pet.ask_ai("今天训练累不累")
    end = time.monotonic() + 40
    while "chat" in pet._ai_lanes and time.monotonic() < end:
        pet.root.update()
        time.sleep(0.02)
    time.sleep(0.5)
    pet.root.update()
    check("满 100 聊天不掉不涨", pet.affection >= before - 5,
          "%d -> %d" % (before, pet.affection))
    check("窗口数字跟上", win.affection_var.get() == str(pet.affection),
          "%r vs %r" % (win.affection_var.get(), pet.affection))

    print("=== 桌面宠物里走一遍（含存盘） ===")
    pet.set_affection(30)
    before = pet.affection
    pet.ask_ai("在吗，今天怎么样")
    end = time.monotonic() + 40
    while "chat" in pet._ai_lanes and time.monotonic() < end:
        pet.root.update()
        time.sleep(0.02)
    time.sleep(0.5)
    pet.root.update()
    after = pet.affection
    print("  affection %d -> %d" % (before, after))
    check("桌面宠物里会变", after != before, "%d -> %d" % (before, after))
    pet._save_config()
    cfg = json.load(io.open(CFG, encoding="utf-8-sig"))
    slot = (cfg.get("chats") or {}).get(pet._persona) or {}
    print("  saved top=%r slot=%r" % (cfg.get("affection"), slot.get("affection")))
    check("存盘跟内存一致", cfg.get("affection") == pet.affection,
          "%r vs %r" % (cfg.get("affection"), pet.affection))
    check("人设槽也一致", slot.get("affection") == pet.affection,
          "%r vs %r" % (slot.get("affection"), pet.affection))
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
