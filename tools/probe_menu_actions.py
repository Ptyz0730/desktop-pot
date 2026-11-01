# -*- coding: utf-8 -*-
"""右键菜单「逗它玩」里的动作到底有没有生效。

走的是菜单那条路：_defer 排队 -> 下一次 tick 里 _run_pending_action 执行。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import desktop_pet as dp  # noqa: E402


def settle(pet, seconds):
    end = time.time() + seconds
    while time.time() < end:
        pet.root.update()
        time.sleep(0.01)


def snap(pet):
    return {
        "squash": round(pet.squash, 2),
        "jump": round(pet.jump, 2),
        "spin": round(pet._spin_angle, 2),
        "dodge": round(pet._dodge_until - pet._now(), 2),
        "petting": pet._pet_energy > 0,
        "petting_active": pet.petting_active(),
    }


def run():
    pet = dp.DesktopPet(use_ai=False, bubble=False)
    settle(pet, 1.0)
    print("visible=%s covered=%s topmost=%s" % (
        pet.visible, pet.check_covered(), pet.topmost))
    pet.visible = True
    pet._next_visible_check = pet._now() + 3600.0

    for kind in ("squash", "jump", "spin", "dodge", "head"):
        pet._defer(pet.do_gesture, kind)
        settle(pet, 0.5)
        print("%-7s -> %s" % (kind, snap(pet)))
        settle(pet, 1.6)

    log = os.path.join(ROOT, "pet_error.log")
    print("log bytes:", os.path.getsize(log) if os.path.exists(log) else 0)
    pet.quit()


run()
