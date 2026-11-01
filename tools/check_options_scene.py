# -*- coding: utf-8 -*-
"""选项是否"贴着场景、由 AI 现写"（真接口跑）。

用法：<DSH python> tools\\check_options_scene.py
"""
from __future__ import print_function

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai_client  # noqa: E402
import desktop_pet  # noqa: E402

BANNED = ("然后呢", "说下去", "我在听")


def out(line=""):
    try:
        print(line)
    except Exception:                          # noqa: BLE001  控制台编码问题
        sys.stderr.write(str(line).encode("gbk", "replace").decode("gbk") + "\n")


def check_parser():
    ok = True
    cases = [
        ('{"options": ["你刚才那球怎么投的", "少臭美了", "手有没有擦伤"]}',
         ["你刚才那球怎么投的", "少臭美了", "手有没有擦伤"]),
        ("1. 你刚才那球怎么投的\n2. 少臭美了\n3、手有没有擦伤",
         ["你刚才那球怎么投的", "少臭美了", "手有没有擦伤"]),
        ('- “别嘴硬了”\n- “我信你”', ["别嘴硬了", "我信你"]),
        ('["a", "b", "c"]', ["a", "b", "c"]),
    ]
    for raw, want in cases:
        got = ai_client._parse_options(raw, 3)
        flag = "ok" if got[:len(want)] == want else "FAIL"
        if flag != "ok":
            ok = False
        out("  parser %-4s %r -> %r" % (flag, raw[:28], got))
    return ok


def main():
    ok = check_parser()
    key = desktop_pet.BUILTIN_API_KEY
    brain = ai_client.PetBrain(api_key=key)
    brain.persona = "闷骚少年"
    brain.system_prompt = ai_client.persona_prompt("闷骚少年")
    for text, aff in (("今天训练累不累", 40), ("那你手有没有擦伤", 42)):
        reply, delta, options, err = brain.chat_with_options(text, affection=aff)
        out("\n=== 玩家: %s (好感度 %d) ===" % (text, aff))
        out("chm : %s" % reply)
        out("delta: %s  err: %s" % (delta, err))
        out("选项: %r" % (options,))
        bad = [o for o in options if any(b in o for b in BANNED)]
        if bad:
            ok = False
            out("  FAIL 出现空话: %r" % (bad,))
        if len(options) < 2:
            ok = False
            out("  FAIL 选项太少: %d" % len(options))
        if len(set(options)) != len(options):
            ok = False
            out("  FAIL 选项重复")
    out("\nRESULT: %s" % ("OK" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
