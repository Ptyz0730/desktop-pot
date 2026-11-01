# -*- coding: utf-8 -*-
"""调试：绕圈为什么没触发转圈。"""
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import desktop_pet as dp                                    # noqa: E402
import ctypes                                               # noqa: E402

user32 = ctypes.windll.user32


def settle(pet, seconds):
    end = time.time() + seconds
    while time.time() < end:
        pet.root.update()
        time.sleep(0.008)


def main():
    pet = dp.DesktopPet(use_ai=False, bubble=False)
    pet.visible = True
    pet._next_visible_check = pet._now() + 3600.0
    settle(pet, 0.8)
    pet._last_extra_gesture = 0.0
    pet._circle_track = []
    pet._circle_last_seen = 0.0
    cx = pet.win_x + pet.win_w / 2.0
    cy = pet.win_y + pet.win_h - pet.sh * pet.scale * 0.46
    radius = pet.win_w * 0.55
    print("center", round(cx), round(cy), "radius", round(radius),
          "body zone y range",
          round(pet.win_y + pet.headroom + pet.sh * pet.scale * 0.30),
          round(pet.win_y + pet.win_h))
    for i in range(46):
        ang = math.tau * i / 45.0
        x, y = cx + radius * math.cos(ang), cy + radius * math.sin(ang)
        user32.SetCursorPos(int(x), int(y))
        settle(pet, 0.028)
        total, span = pet._circle_progress()
        cx2 = pet.win_x + pet.win_w / 2.0
        cy2 = pet.win_y + pet.win_h - pet.sh * pet.scale * 0.46
        r = math.hypot(x - cx2, y - cy2)
        print("%2d track=%2d total=%5.2f span=%4.2f r=%5.1f min_r=%5.1f hits=%d rev=%d"
              % (i, len(pet._circle_track), total, span, r,
                 max(28.0, pet.win_w * 0.34), pet._gesture_hits["spin"],
                 pet._shake_rev))
        if pet._gesture_hits["spin"]:
            break
    pet.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
