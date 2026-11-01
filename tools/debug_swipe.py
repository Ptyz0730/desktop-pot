# -*- coding: utf-8 -*-
"""调试：直接喂合成采样，看下滑为什么没触发。"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import desktop_pet as dp  # noqa: E402


def run():
    pet = dp.DesktopPet(use_ai=False, bubble=False)
    for _ in range(40):
        pet.root.update()
        time.sleep(0.01)
    pet.visible = True
    pet._next_visible_check = pet._now() + 3600
    x = pet.win_x + pet.win_w // 2
    top = pet.win_y + pet.headroom + 10
    bottom = pet.win_y + pet.win_h - 20
    print("rect", pet.win_x, pet.win_y, pet.win_w, pet.win_h,
          "top", top, "bottom", bottom)
    pet._swipe = []
    pet._circle_track = []
    pet.squash = 0.0
    now = pet._now()
    for i in range(12):
        now += 0.04
        y = top + (bottom - top) * i / 11.0
        pet._on_mouse_move(x, y, now)
        total, span = pet._circle_progress()
        print("i=%2d y=%4d dy_from_first=%.0f circle=(%.2f,%.2f) hits=%s squash=%.2f"
              % (i, y, y - top, total, span, pet._gesture_hits, pet.squash))
    pet.quit()


run()
