# -*- coding: utf-8 -*-
"""复现用户描述：下滑之后图像是不是一直瘪着、上划跳不跳得起来。"""
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import desktop_pet as dp  # noqa: E402

u = dp._user32


def settle(pet, seconds):
    end = time.time() + seconds
    while time.time() < end:
        pet.root.update()
        time.sleep(0.01)


def show(pet, tag):
    print("%-14s squash=%.2f jump=%.2f dodge=%.2f angle=%.2f vis=%s hits=%s"
          % (tag, pet.squash, pet.jump, pet._dodge_dx, pet._spin_angle,
             pet.visible, pet._gesture_hits))


def move_to(pet, x, y):
    u.SetCursorPos(int(x), int(y))
    settle(pet, 0.012)


def run():
    cfg = dp.CONFIG_PATH
    cfg_backup = None
    if os.path.exists(cfg):
        cfg_backup = cfg + ".probe_bak"
        try:
            os.replace(cfg, cfg_backup)
        except OSError:
            cfg_backup = None
    pet = None
    try:
        pet = dp.DesktopPet(use_ai=False, bubble=False)
        settle(pet, 1.2)
        # 这台机器前台是最大化窗口，宠物永远"被盖住"；测试里强制当作露在外面，
        # 才能看到压扁/跳跃的动画过程
        pet.visible = True
        pet._next_visible_check = pet._now() + 3600.0
        print("win=%s visible=%s covered=%s" % (
            (pet.win_x, pet.win_y, pet.win_w, pet.win_h),
            pet.visible, pet.check_covered()))

        x = pet.win_x + pet.win_w // 2
        top = pet.win_y + pet.headroom + 12
        bottom = pet.win_y + pet.win_h - 24
        # 先离开宠物，避免把"从远处甩过来"那一段也算进划动
        u.SetCursorPos(int(x), int(top) - 160)
        settle(pet, 0.3)
        for i in range(11):
            move_to(pet, x, top + (bottom - top) * i / 10.0)
        show(pet, "swipe down")
        for k in range(6):
            settle(pet, 0.1)
            show(pet, "  +%.1fs" % ((k + 1) * 0.1))
        for i in range(11):
            move_to(pet, x, bottom + (top - bottom) * i / 10.0)
        show(pet, "swipe up")
        for k in range(6):
            settle(pet, 0.1)
            show(pet, "  +%.1fs" % ((k + 1) * 0.1))

        # 身体上快速横划 -> 躲一下（先歇够冷却）
        settle(pet, 1.0)
        body_y = pet.win_y + pet.headroom + int(pet.sh * pet.scale * 0.55)
        left = pet.win_x - 60
        right = pet.win_x + pet.win_w + 60
        u.SetCursorPos(int(left), int(body_y))
        settle(pet, 0.35)
        for i in range(11):
            move_to(pet, left + (right - left) * i / 10.0, body_y)
        show(pet, "body swipe")

        # 绕宠物转一圈 -> 转晕（先歇 1.6 秒，让上一个动作的冷却过去）
        settle(pet, 1.6)
        cx = pet.win_x + pet.win_w / 2.0
        cy = pet.win_y + pet.win_h - pet.sh * pet.scale * 0.46
        radius = pet.win_w * 0.55
        trace = {"samples": 0, "max_total": 0.0, "rmin": 1e9, "rmax": 0.0,
                 "clear": 0, "calls": 0}
        orig_tc = pet._track_circle

        def traced(now, x, y):
            trace["calls"] += 1
            r = math.hypot(x - cx, y - cy)
            trace["rmin"] = min(trace["rmin"], r)
            trace["rmax"] = max(trace["rmax"], r)
            before = len(pet._circle_track)
            orig_tc(now, x, y)
            if pet._circle_track and before and len(pet._circle_track) < before:
                trace["clear"] += 1
            trace["samples"] = max(trace["samples"], len(pet._circle_track))
            tot, _span = pet._circle_progress()
            trace["max_total"] = max(trace["max_total"], abs(tot))
        pet._track_circle = traced
        for i in range(37):
            ang = math.tau * i / 36.0
            move_to(pet, cx + radius * math.cos(ang), cy + radius * math.sin(ang))
        pet._track_circle = orig_tc
        print("circle trace:", trace)
        show(pet, "circle")

        try:
            pet._circle_track = []
            pet._last_extra_gesture = 0.0
            t0 = pet._now()
            hits0 = pet._gesture_hits["spin"]
            for i in range(40):
                ang = math.tau * i / 36.0
                pet._track_circle(t0 + i * 0.02,
                                  cx + radius * math.cos(ang),
                                  cy + radius * math.sin(ang))
            print("synthetic circle: spin+%d track=%d" % (
                pet._gesture_hits["spin"] - hits0, len(pet._circle_track)))
        except Exception as exc:
            print("synthetic circle failed:", exc)

        # 心跳：动作之后主循环还得在跑
        before = pet._last_tick
        settle(pet, 0.25)
        print("heartbeat advanced: %s (%.3fs)" % (
            pet._last_tick > before, pet._last_tick - before))
        log = os.path.join(ROOT, "pet_error.log")
        print("pet_error.log bytes:", os.path.getsize(log) if os.path.exists(log) else "n/a")
    finally:
        if pet is not None:
            try:
                pet.quit()
            except Exception:
                pass
        if cfg_backup:
            try:
                os.replace(cfg_backup, cfg)
            except OSError:
                pass


run()
