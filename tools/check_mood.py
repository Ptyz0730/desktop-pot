# -*- coding: utf-8 -*-
"""情绪机制自检：吃醋 / 冷战 / 嘴硬心软 / 旁白。

用法：<DSH python> tools\\check_mood.py
前半段是纯状态机单测（不联网、不开窗口），后半段把假回复接到真的
DesktopPet 上走一遍聊天流程。检查项用英文名，详情尽量 ASCII。
"""
import os
import random
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import pet_mood as pm  # noqa: E402
import ai_client  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print("  %-46s %s %s" % (name, "ok" if cond else "FAIL", detail))


# ---------------------------------------------------------------- 状态机
def play(seq, step=60.0, t0=1000.0):
    """按顺序喂一串话（每句间隔 step 秒），返回 (状态机, 事件列表)。"""
    eng = pm.MoodEngine()
    t = t0
    events = []
    for text in seq:
        events.append(eng.observe(text, now=t))
        t += step
    return eng, events


def unit_tests():
    print("=== triggers ===")
    for text, want in (("哦", pm.COLD), ("嗯", pm.COLD), ("随便", pm.COLD),
                       ("随便你吧", pm.JEALOUS), ("他好帅啊", pm.JEALOUS),
                       ("刚跟同学吃完饭回来", pm.JEALOUS),
                       ("你比不上他", pm.COLD), ("你骗我", pm.COLD),
                       ("滚", pm.COLD), ("你好", pm.NORMAL),
                       ("你比他厉害多了", pm.NORMAL), ("他好烦", pm.NORMAL),
                       # 不针对它的脏话/闲聊不能误伤
                       ("这游戏真垃圾", pm.NORMAL), ("他好久没来了", pm.NORMAL),
                       ("你真没用", pm.COLD),
                       # 嫌他嘴碎 / 当众拆穿他嘴硬（用户设定里都算冷战）
                       ("你话真多", pm.COLD), ("你也太嘴碎了", pm.COLD),
                       ("当众拆穿你嘴硬", pm.COLD), ("别装了", pm.COLD),
                       ("装什么酷啊", pm.NORMAL)):
        eng, _ = play([text])
        check("trigger %s" % text.encode("unicode_escape").decode(),
              eng.state == want, eng.state)

    print("=== transitions ===")
    eng, ev = play(["他好帅", "嗯"])
    check("jealous + lukewarm -> cold", eng.state == pm.COLD,
          "%s/%s" % (eng.state, ev[-1]["reason"]))
    eng, ev = play(["他好帅", "你好", "在吗"])
    check("2 turns un-coaxed -> cold",
          eng.state == pm.COLD and ev[-1]["reason"] == "ignored",
          "%s/%s" % (eng.state, ev[-1]["reason"]))
    eng, ev = play(["他好帅", "对不起我错了"])
    check("coax -> back to normal", eng.state == pm.NORMAL
          and ev[-1]["kind"] == "resolve_jealous", ev[-1]["kind"])
    eng, ev = play(["你烦不烦", "怎么了", "我错了"])
    check("cold asks, then coax resolves",
          eng.state == pm.NORMAL and ev[1]["asking"]
          and ev[-1]["kind"] == "resolve_cold", ev[1]["kind"])
    eng = pm.MoodEngine()
    eng.observe("你烦不烦", now=1000.0)
    ev = eng.observe("在吗", now=1000.0 + 25 * 3600)
    check("24h silence -> calm", eng.state == pm.NORMAL
          and ev["kind"] == "calm", ev["kind"])
    eng = pm.MoodEngine()
    eng.observe("你好", now=1000.0)
    ev = eng.observe("在干嘛", now=1000.0 + 15 * 60)
    check("slow reply -> jealous", eng.state == pm.JEALOUS
          and ev["reason"] == "slow", ev["reason"])

    print("=== shaping ===")
    eng, _ = play(["你烦不烦"])
    long_reply = "（他把手机往桌上一扣）不想聊了，你自己玩吧，我先去写作业"
    check("cold long reply -> short line",
          eng.shape(long_reply, {"kind": "stay_cold"}) in pm.COLD_LINES, "")
    check("cold asking -> 没事/你想多了",
          eng.shape(long_reply, {"kind": "stay_cold", "asking": True})
          in pm.COLD_ASK, "")
    eng2, _ = play(["他好帅"])
    out = eng2.shape("（别过脸）他谁啊？你跟我说这个是想干嘛呢我都懒得问", None)
    check("jealous reply trimmed", len(out) <= 20, "len=%d" % len(out))
    check("cold delta clamped", eng.clamp_delta(3) <= 0, str(eng.clamp_delta(3)))
    check("jealous delta clamped", eng2.clamp_delta(3) <= 1,
          str(eng2.clamp_delta(3)))
    check("normal delta untouched", pm.MoodEngine().clamp_delta(3) == 3, "")
    # 哄好那一下要给得出台阶（「明天有训练，爱来不来」），但也不能长篇
    out = eng.shape("嗯……明天有训练，爱来不来，你自己看着办吧",
                    {"kind": "resolve_cold"})
    check("cold resolve -> step-down line", out in pm.COLD_SOFT,
          out.encode("unicode_escape").decode())

    print("=== persona prompt ===")
    prompt = ai_client.persona_prompt("闷骚少年")
    for needle in ("陈瀚铭", "I'm goat", "我的 MVP", "经理", "基操勿六",
                   "怎么回夸", "吃药没", "三分 10 中 7", "手滑", "GOAT 能有什么事"):
        check("prompt has %s" % needle.encode("unicode_escape").decode(),
              needle in prompt, "")
    check("stage rules appended once", prompt.count("【表演规则】") == 1, "")
    check("prompt stays bounded", len(prompt) < 4000, "len=%d" % len(prompt))
    for value, needle in ((5, "观众"), (30, "经理"), (50, "朋友期"),
                          (70, "我的经理"), (90, "我的 MVP")):
        tone = ai_client.affection_tone(value, "闷骚少年")
        check("tone %d has %s" % (value, needle.encode("unicode_escape").decode()),
              needle in tone, "")

    print("=== dump / load ===")
    eng, _ = play(["你烦不烦"])
    data = eng.dump()
    back = pm.MoodEngine.load(data)
    check("roundtrip keeps state", back.dump() == data, str(data))
    check("junk load -> normal", pm.MoodEngine.load("nonsense").state
          == pm.NORMAL, "")
    check("old config (no mood key) -> normal",
          pm.MoodEngine.load(None).state == pm.NORMAL, "")

    print("=== theater ===")
    eng, _ = play(["你烦不烦"])
    seen = set()
    for seed in range(30):
        e = pm.MoodEngine.load(eng.dump())
        seen.add(e.theater({"kind": "stay_cold"}, rng=random.Random(seed)))
    check("theater yields withdraw/like/None",
          {"withdraw", "like"} <= seen and None in seen, str(sorted(
              str(x) for x in seen)))
    check("no theater when not cold",
          pm.MoodEngine().theater({"kind": "enter_jealous"}) is None, "")


# ---------------------------------------------------------------- 真窗口
def settle(pet, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pet.root.update()
        time.sleep(0.015)


def bubble_text(pet):
    plan = getattr(pet.bubble, "_plan", None) or {}
    return "".join(str(x) for x in (plan.get("lines") or []))


def log_text(win):
    return win.log.get("1.0", "end")


def integration_tests():
    import desktop_pet as dp

    cfg = dp.CONFIG_PATH
    bak = cfg + ".mood_bak"
    if os.path.exists(cfg):
        shutil.copy2(cfg, bak)
    try:
        if os.path.exists(cfg):
            os.remove(cfg)
        pet = dp.DesktopPet(use_ai=True, topmost=True, bubble=True)
        settle(pet, 0.3)
        pet.cfg.setdefault("personas", {})[pet.image_name] = "闷骚少年"
        pet._persona = None
        pet._apply_persona()
        pet.brain.chat_with_options = (
            lambda text, affection=0: ("（他把手机扣在桌上）随便吧，你说什么就是什么",
                                       3, ["一", "二", "三"], None))
        pet.open_chat()
        settle(pet, 0.4)
        win = pet.chat_win

        print("=== jealous through the real chat flow ===")
        before = pet.affection
        win._send("他好帅啊")
        settle(pet, 0.9)
        check("state is jealous", pet.mood.state == pm.JEALOUS, pet.mood.state)
        # 颜文字会补在后面，所以按"后半句被剪掉"判断
        body = bubble_text(pet)
        check("reply shaped", "就是什么" not in body and "随便吧" in body,
              repr(body))
        check("delta clamped to +1", pet.affection - before <= 1,
              "+%d" % (pet.affection - before))
        check("hint pushed to brain", "吃醋" in pet.brain.mood_hint, "")
        check("option hint pushed", bool(pet.brain.mood_options_hint), "")
        check("options still shown",
              any(b.winfo_ismapped() for b in win.option_buttons), "")

        print("=== coax it back ===")
        win._send("对不起嘛，我就随口一说，你最帅")
        settle(pet, 0.9)
        check("coax -> normal", pet.mood.state == pm.NORMAL, pet.mood.state)
        check("soft line, <= 2 sentences", "\n" not in bubble_text(pet), "")

        print("=== cold war ===")
        win._send("哦")
        settle(pet, 0.9)
        check("lukewarm -> cold", pet.mood.state == pm.COLD, pet.mood.state)
        text = bubble_text(pet)
        check("cold reply is a stub", text.strip() in pm.COLD_LINES
              or len(text) <= 8, repr(text))
        check("no kaomoji in cold", "(" not in text and "（" not in text,
              repr(text))
        check("hint says cold", "冷战" in pet.brain.mood_hint, "")

        print("=== cold: no initiative, no prefetch ===")
        # 启动时那次待机用语请求可能还没落地，先等它结束再测
        for _ in range(40):
            if "chatter" not in pet._ai_lanes:
                break
            settle(pet, 0.1)
        pet.prefetched = "攒好的一句"
        pet.speak_random()
        settle(pet, 0.2)
        check("tap gives idle stub", bubble_text(pet).strip()
              in pm.COLD_IDLE or len(bubble_text(pet)) <= 4,
              repr(bubble_text(pet)))
        check("prefetched dropped", pet.prefetched is None, "")
        lanes = set(pet._ai_lanes)
        pet._prefetch_chatter()
        check("prefetch skipped in cold",
              set(pet._ai_lanes) == lanes and pet.prefetched is None,
              str(sorted(pet._ai_lanes)))

        print("=== cold theater: withdraw ===")
        win.add_reply("（他把脸别过去）这条一会儿就撤回")
        settle(pet, 0.1)
        win.withdraw_last(delay_ms=0)
        settle(pet, 0.5)
        body = log_text(win)
        check("withdraw note in log", "撤回" in body, "")
        check("withdrawn line removed", "一会儿就撤回" not in body, "")

        print("=== mood follows the persona ===")
        win._send("你烦不烦")
        settle(pet, 0.9)
        check("still cold", pet.mood.state == pm.COLD, pet.mood.state)
        pet.set_persona("话痨朋友")
        settle(pet, 0.2)
        check("other persona starts normal", pet.mood.state == pm.NORMAL,
              pet.mood.state)
        pet.set_persona("闷骚少年")
        settle(pet, 0.2)
        check("cold kept per persona", pet.mood.state == pm.COLD,
              pet.mood.state)

        print("=== persisted in config ===")
        pet._stash_persona()
        state = pet._persona_state()
        check("cfg carries mood", isinstance(state.get("mood"), dict)
              and state["mood"].get("state") == pm.COLD, str(state.get("mood")))

        print("=== forget chat clears the mood ===")
        pet.forget_chat()
        settle(pet, 0.2)
        check("mood reset", pet.mood.state == pm.NORMAL
              and pet.brain.mood_hint == "", pet.mood.state)

        pet.quit()
    finally:
        try:
            if os.path.exists(cfg):
                os.remove(cfg)
            if os.path.exists(bak):
                shutil.move(bak, cfg)
        except Exception:                   # noqa: BLE001
            pass


if __name__ == "__main__":
    unit_tests()
    integration_tests()
    print("RESULT:", "OK" if ok else "FAILED")
    sys.exit(0 if ok else 1)
