# -*- coding: utf-8 -*-
"""郑迪隆（骚话少年）自检：人设 / 暗号 / 日语翻译 / 立绘 / 特效。

用法：<DSH python> tools\\check_zdl.py
纯逻辑部分不联网；最后一段用真的 DesktopPet + 假回复走一遍聊天/特效。
"""
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import ai_client  # noqa: E402
import jp_gloss  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print("  %-46s %s %s" % (name, "ok" if cond else "FAIL", detail))


KEY = "骚话少年"


def unit_tests():
    print("=== persona ===")
    p = ai_client.PERSONA_PROMPTS.get(KEY, "")
    check("prompt registered", bool(p), "%d chars" % len(p))
    check("display name", ai_client.persona_display_name(KEY) == "郑迪隆",
          ai_client.persona_display_name(KEY))
    for needle in ("郑迪隆", "2011 年 10 月 11 日", "九年七班", "気持ちいい",
                   "月色真美", "君のこと、好きだよ", "敲两下", "我的同桌",
                   "MVP", "寂しい", "记忆", "好感度"):
        check("prompt has %s" % needle.encode("unicode_escape").decode(),
              needle in p, "")
    # 乒乓球只能出现在"禁止"那一句里；不能带上别人的口头禅原文
    check("乒乓球 only in the ban", p.count("乒乓球") == 1, "")
    check("no I'm goat", "I'm goat" not in p, "")
    check("stage rules appended once",
          ai_client.persona_prompt(KEY).count("【表演规则】") == 1, "")
    check("hint registered", "郑迪隆" in ai_client.persona_hint(KEY), "")
    check("romance persona", KEY in ai_client.ROMANCE_PERSONAS, "")
    check("romance line", ai_client.romance_line(KEY) == "月色真美",
          ai_client.romance_line(KEY))
    check("romance prompt",
          "恋人关系" in ai_client.persona_prompt(KEY, romance=True), "")

    print("=== 5 affection tiers ===")
    marks = ((95, "MVP"), (70, "我的同桌"), (50, "小笨蛋"), (30, "笨蛋"),
             (5, "同学"))
    seen = []
    for value, mark in marks:
        tone = ai_client.affection_tone(value, KEY)
        seen.append(tone)
        check("affection %d -> %s" % (value, mark.encode("ascii", "ignore").decode()),
              mark in tone, tone[:18])
    check("tiers are distinct", len(set(seen)) == 5, "")
    # 别人的语气表没被带歪
    check("chm keeps its tone", "MVP" in ai_client.affection_tone(95, "闷骚少年"),
          ai_client.affection_tone(95, "闷骚少年")[:18])

    print("=== japanese gloss ===")
    cases = (
        ("気持ちいい", "気持ちいい\n（好舒服啊）"),
        ("気持ちいい（好舒服啊）", "気持ちいい\n（好舒服啊）"),
        ("（敲了两下桌子）気持ちいい", "（敲了两下桌子）気持ちいい\n（好舒服啊）"),
        ("月色真美", "月色真美"),                 # 中文暗号不翻译
        ("おはようございます", "おはようございます"),  # 没登记的日语不乱翻
        ("バカ", "バカ\n（笨蛋）"),
    )
    for src, want in cases:
        got = jp_gloss.add_gloss(src)
        check("gloss %s" % src.encode("unicode_escape").decode(), got == want,
              got.encode("unicode_escape").decode()[:40])
    once = jp_gloss.add_gloss("気持ちいい")
    check("gloss is idempotent", jp_gloss.add_gloss(once) == once, "")
    check("already-inline not doubled",
          jp_gloss.add_gloss("気持ちいい 好舒服啊") == "気持ちいい 好舒服啊", "")


def settle(pet, seconds):
    end = time.time() + seconds
    while time.time() < end:
        try:
            pet.root.update()
        except Exception:                   # noqa: BLE001 - 窗口已销毁
            return
        time.sleep(0.015)


def bubble_text(pet):
    plan = getattr(pet.bubble, "_plan", None) or {}
    # 气泡是按行画的：用换行拼回来，才看得出"翻译有没有另起一行"
    return "\n".join(str(x) for x in (plan.get("lines") or []))


def integration_tests():
    import desktop_pet as dp

    print("=== image -> persona ===")
    check("mapped in IMAGE_PERSONAS",
          dp.IMAGE_PERSONAS.get("郑迪隆.png") == KEY,
          str(dp.IMAGE_PERSONAS.get("郑迪隆.png")))
    check("sprite exists", os.path.exists(os.path.join(dp.IMAGE_DIR, "郑迪隆.png")),
          "")
    check("persona_key_for", dp.persona_key_for("郑迪隆.png", {"personas": {}}) == KEY,
          "")

    cfg = dp.CONFIG_PATH
    bak = cfg + ".zdl_bak"
    if os.path.exists(cfg):
        shutil.copy2(cfg, bak)
    try:
        if os.path.exists(cfg):
            os.remove(cfg)
        pet = dp.DesktopPet(use_ai=True, topmost=True, bubble=True)
        settle(pet, 0.3)
        pet.set_image("郑迪隆.png")
        settle(pet, 0.4)
        check("persona follows image", pet._persona == KEY, str(pet._persona))
        check("window title", "郑迪隆" in pet.chat_win.win.title()
              if pet.chat_win else True, "")

        print("=== special effect: 打飞机 + 摸头弹幕 ===")
        check("has_special_skill", pet.has_special_skill(), "")
        check("danmaku_allowed", pet.danmaku_allowed(), "")
        phrases = pet.danmaku_phrases()
        check("danmaku phrases are his", phrases is dp.DANMAKU_PHRASES_BY_PERSONA[KEY]
              and len(phrases) >= 3, "%d lines" % len(phrases))
        check("phrases carry translations",
              all(jp_gloss.has_kana(jp) and cn for jp, cn in phrases), "")
        pet.trigger_shooting()
        settle(pet, 0.4)
        check("shooting starts", pet.shooting_active(), "")
        pet.shooting_until = 0.0
        pet.shoot_fx.stop() if hasattr(pet.shoot_fx, "stop") else None
        settle(pet, 0.3)

        print("=== japanese reply shows the translation below ===")
        pet.brain.chat_with_options = (
            lambda text, affection=0: ("（他手指在桌上敲了两下）気持ちいい", 2,
                                       ["一", "二", "三"], None))
        pet.open_chat()
        settle(pet, 0.4)
        win = pet.chat_win
        win._send("你在干嘛")
        settle(pet, 0.9)
        body = bubble_text(pet)
        check("bubble has translation", "好舒服啊" in body, repr(body))
        check("translation on its own line", "\n" in body, repr(body))
        log = win.log.get("1.0", "end")
        check("chat log has translation", "好舒服啊" in log, "")
        check("japanese kept", "気持ちいい" in log, "")

        print("=== 不是这条人设就没有特技 ===")
        pet.set_persona("话痨朋友")
        settle(pet, 0.2)
        check("no skill for 话痨朋友", not pet.has_special_skill(), "")
        pet.shooting_until = 0.0
        pet.trigger_shooting()
        settle(pet, 0.2)
        check("refusal mentions both", "郑迪隆" in bubble_text(pet), "")

        print("=== romance line ===")
        pet.set_persona(KEY)
        settle(pet, 0.2)
        pet.set_affection(100)
        settle(pet, 0.2)
        check("romance available", pet.romance_available(), "")
        pet.trigger_romance()
        settle(pet, 0.3)
        check("confession line spoken", "月色真美" in bubble_text(pet),
              repr(bubble_text(pet)))
    finally:
        if os.path.exists(bak):
            shutil.copy2(bak, cfg)
            os.remove(bak)
        elif os.path.exists(cfg):
            os.remove(cfg)


def main():
    unit_tests()
    integration_tests()
    print("\nRESULT: %s" % ("OK" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
