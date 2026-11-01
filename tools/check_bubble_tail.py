# -*- coding: utf-8 -*-
"""单独复现"移动到左上角后气泡尾巴和头错开 23px"这一条。"""
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import desktop_pet as dp  # noqa: E402


def settle(pet, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pet.root.update()
        time.sleep(0.015)


CFG = dp.CONFIG_PATH
BAK = CFG + ".tail_bak"
if os.path.exists(CFG):
    shutil.copy2(CFG, BAK)
try:
    if os.path.exists(CFG):
        os.remove(CFG)
    pet = dp.DesktopPet(style="colorkey", use_ai=False, topmost=True, bubble=True)
    settle(pet, 0.4)
    pet.speak("尾巴对齐测试，测一下移动到角落里之后尾巴还指不指着头。")
    settle(pet, 0.4)

    def state(tag):
        b = pet.bubble
        ax, ay = pet.head_anchor()
        plan = b._plan
        print("%-10s pet=(%d,%d) win=(%d,%d) head=(%.1f,%.1f) below=%s "
              "tail_x=%.1f card_x=%.1f win_x=%d card_w=%d"
              % (tag, pet.win_x, pet.win_y, b.win.winfo_x(), b.win.winfo_y(),
                 ax, ay, b._below, plan["tail_x"],
                 plan["tail_x"] * 0 + (b.win.winfo_x() + plan["tail_x"]),
                 b.win.winfo_x(), plan["w"]))
        print("           gap=%.1f dx=%.1f"
              % ((b.win.winfo_y() - ay) if b._below
                 else (ay - (b.win.winfo_y() + plan["card_bottom"])),
                 abs(b.win.winfo_x() + plan["tail_x"] - ax)))

    state("initial")
    target = pet.clamp_pos(pet.win_x - 250, pet.win_y - 120)
    pet.move(*target)
    settle(pet, 0.6)
    state("moved")
    pet.quit()
finally:
    try:
        if os.path.exists(CFG):
            os.remove(CFG)
        if os.path.exists(BAK):
            shutil.move(BAK, CFG)
    except Exception:                       # noqa: BLE001
        pass
