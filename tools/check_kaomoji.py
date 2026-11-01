# -*- coding: utf-8 -*-
"""颜文字系统自检：词库、心情映射、装饰逻辑、桌宠里的开关与气泡。"""
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import desktop_pet as dp  # noqa: E402
import kaomoji  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print("  %-42s %s %s" % (name, "ok" if cond else "FAIL", detail))


def bubble_text(pet):
    try:
        return "".join((pet.bubble._plan or {}).get("lines") or [])
    except Exception:                       # noqa: BLE001
        return ""


CFG = dp.CONFIG_PATH
BAK = CFG + ".kao_bak"
if os.path.exists(CFG):
    shutil.copy2(CFG, BAK)
try:
    print("=== 词库 ===")
    for mood, group in kaomoji.GROUPS.items():
        check("心情 %s 有词" % mood, len(group) >= 5, "%d 个" % len(group))
    every = kaomoji.all_kaomoji()
    check("没有超长的", all(len(k) <= 26 for k in every),
          max(every, key=len))
    check("首尾没空格", all(k == k.strip() for k in every))
    check("括号配平", all(k.count("(") == k.count(")") or
                          k.count("（") == k.count("）") for k in every),
          [k for k in every if k.count("(") != k.count(")")][:3])

    print("=== 心情映射 ===")
    check("好感度 10 -> 生气", kaomoji.mood_for_affection(10) == "生气")
    check("好感度 30 -> 无语", kaomoji.mood_for_affection(30) == "无语")
    check("好感度 50 -> 得意", kaomoji.mood_for_affection(50) == "得意")
    check("好感度 70 -> 开心", kaomoji.mood_for_affection(70) == "开心")
    check("好感度 90 -> 害羞", kaomoji.mood_for_affection(90) == "害羞")
    check("摸头 -> 害羞", kaomoji.mood_for_gesture("head") == "害羞")

    print("=== 装饰逻辑 ===")
    one = kaomoji.decorate("今天练球有点累")
    check("会贴在后面", one != "今天练球有点累" and len(one) > 6, one)
    check("已有就不重复", kaomoji.decorate(one) == one, kaomoji.decorate(one))
    check("括号表情能认出来", kaomoji.has_kaomoji("好的 (￣▽￣)"))
    check("普通句子不算", not kaomoji.has_kaomoji("我在听"))
    check("rate=0 不贴", kaomoji.decorate("我在听", rate=0.0) == "我在听")

    print("=== 桌宠里 ===")
    if os.path.exists(CFG):
        os.remove(CFG)
    pet = dp.DesktopPet(use_ai=False, topmost=False, bubble=True)
    for _ in range(6):
        pet.root.update()
        time.sleep(0.05)
    check("默认开着", pet.kaomoji_enabled)
    pet.speak_random()
    pet.root.update()
    said = bubble_text(pet)
    print("  气泡:", said)
    check("气泡里有颜文字", kaomoji.has_kaomoji(said) or
          any(k in said for k in kaomoji.all_kaomoji()), said[:40])
    pet.say_kaomoji()
    pet.root.update()
    said = bubble_text(pet)
    print("  来一个:", said)
    check("「来一个颜文字」有效", any(k in said for k in kaomoji.all_kaomoji()),
          said[:40])

    # 菜单里的开关已经挪进设置窗口，这里直接走统一入口
    pet.set_kaomoji_enabled(False, quiet=True)
    pet.root.update()
    check("关掉之后状态为关", not pet.kaomoji_enabled)
    pet.speak_random()
    pet.root.update()
    said = bubble_text(pet)
    check("关掉之后不带颜文字", not any(k in said for k in kaomoji.all_kaomoji()),
          said[:40])
    cfg = json.load(open(CFG, encoding="utf-8-sig"))
    check("存档记了开关", cfg.get("kaomoji") is False, str(cfg.get("kaomoji")))
    pet.set_kaomoji_enabled(True, quiet=True)
    check("再开回来", pet.kaomoji_enabled)

    # 聊天回复那条路径
    line = pet._kaomoji_line("行吧，那就这样", rate=1.0)
    check("聊天回复也能贴", kaomoji.has_kaomoji(line), line)

    pet.reset_all()
    pet.root.update()
    check("重置后恢复默认开", pet.kaomoji_enabled)
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
