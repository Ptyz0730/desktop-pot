"""Live gesture check: move the real cursor over the pet and expect a reaction.

不 stub `_poll_cursor`，也不手动喂轨迹 —— 走的是 exe 里真正的那条路：
每帧 GetCursorPos -> _on_mouse_move -> 判定 -> 压扁 / 跳 / 躲 / 转圈。

桌宠现在固定在最底层，前台开个最大化窗口时它就被判成"被盖住"，姿势值会被
归零（这是要修的问题之一），所以这里用 `_gesture_hits` 判断"手势有没有认出来"，
姿势动画单独在强制 visible=True 的情况下验证。
"""

import ctypes
import math
import os
import sys
import time
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import desktop_pet as dp  # noqa: E402

user32 = ctypes.windll.user32


def settle(pet, seconds):
    end = time.time() + seconds
    while time.time() < end:
        pet.root.update()
        time.sleep(0.008)


def move(x, y):
    user32.SetCursorPos(int(x), int(y))


def swipe(pet, x, y_from, y_to, steps=10, dt=0.012):
    move(x, y_from)
    settle(pet, 0.05)
    for i in range(1, steps + 1):
        move(x, y_from + (y_to - y_from) * i / float(steps))
        settle(pet, dt)


def hits(pet):
    return dict(pet._gesture_hits)


def gained(pet, before, key):
    return pet._gesture_hits[key] - before[key]


def main():
    pet = dp.DesktopPet(use_ai=False, bubble=True)
    pet.visible = True
    pet._next_visible_check = pet._now() + 3600.0
    settle(pet, 0.8)
    print("rect", pet.win_x, pet.win_y, pet.win_w, pet.win_h,
          "gestures=", pet.gestures_enabled)

    x = pet.win_x + pet.win_w // 2
    top = pet.win_y + pet.headroom + 20
    bottom = pet.win_y + pet.win_h - 20
    base = hits(pet)

    # 1) 从屏幕别处甩过来，落在宠物身上再往下压（用户最常见的划法）
    move(200, 200)
    settle(pet, 0.3)
    pet.squash = 0.0
    swipe(pet, x, top, bottom)
    down = gained(pet, base, "squash")
    print("swipe down : squash hits +%d squash=%.2f" % (down, pet.squash))
    ok_squash = down >= 1 and pet.squash > 0.15

    # 2) 压扁必须自己回正（用户报的"一直变瘪"就是这里坏掉）
    settle(pet, 0.9)
    pet.visible = True
    pet._next_visible_check = pet._now() + 3600.0
    settle(pet, 0.2)
    print("relax      : squash=%.2f" % pet.squash)
    ok_relax = pet.squash < 0.05

    # 3) 上划 -> 跳
    settle(pet, 0.5)
    pet.jump = 0.0
    base = hits(pet)
    swipe(pet, x, bottom, top)
    up = gained(pet, base, "jump")
    print("swipe up   : jump hits +%d jump=%.2f" % (up, pet.jump))
    ok_jump = up >= 1

    # 4) 身体快速横划 -> 躲
    settle(pet, 1.0)
    pet._last_extra_gesture = 0.0
    pet._body_track = []
    pet._circle_track = []
    base = hits(pet)
    y = pet.win_y + pet.win_h - 50
    move(x - 100, y)
    settle(pet, 0.05)
    for i in range(1, 11):
        move(x - 100 + i * 24, y)
        settle(pet, 0.012)
    dodge = gained(pet, base, "dodge")
    print("body swipe : dodge hits +%d dodge_dx=%.1f" % (dodge, pet._dodge_dx))
    ok_dodge = dodge >= 1

    # 5) 绕宠物转一圈 -> 转晕
    settle(pet, 1.6)
    pet._last_extra_gesture = 0.0
    pet._circle_track = []
    base = hits(pet)
    cx = pet.win_x + pet.win_w / 2.0
    cy = pet.win_y + pet.win_h - pet.sh * pet.scale * 0.46
    radius = pet.win_w * 0.55
    pet._circle_track = []
    pet._circle_last_seen = 0.0
    for i in range(46):
        ang = math.tau * i / 45.0
        move(cx + radius * math.cos(ang), cy + radius * math.sin(ang))
        settle(pet, 0.028)
    spin = gained(pet, base, "spin")
    print("circle     : spin hits +%d angle=%.2f" % (spin, pet._spin_angle))
    ok_spin = spin >= 1

    # 6) 被窗口盖住（visible=False）时手势仍然要认得出来
    cover = tk.Toplevel(pet.root)
    cover.overrideredirect(True)
    cover.configure(bg="#000000")
    cover.geometry("%dx%d+%d+%d" % (pet.win_w + 80, pet.win_h + 80,
                                    pet.win_x - 40, pet.win_y - 40))
    cover.attributes("-topmost", True)
    cover.update()
    # 让主循环重新自己判可见性（前面为了看动画把轮询推迟了）
    pet._next_visible_check = 0.0
    settle(pet, 1.2)
    print("covered    : visible=", pet.visible, "covered=", pet.check_covered())
    base = hits(pet)
    swipe(pet, x, top, bottom)
    covered = gained(pet, base, "squash")
    settle(pet, 0.9)                     # 动作状态照常衰减，不该停在半路
    print("covered swipe: squash hits +%d squash=%.2f visible=%s"
          % (covered, pet.squash, pet.visible))
    ok_covered = covered >= 1 and pet.squash < 0.05
    cover.destroy()
    settle(pet, 0.2)

    def shake_it():
        """在身体上来回摇：6 段、每段 5 步、步长 16px。"""
        cx = pet.win_x + pet.win_w // 2
        y_body = pet.win_y + pet.win_h - 70
        pet._shake_track = []
        pet._shake_rev = 0
        pet._shake_ready_at = 0.0
        for seg in range(6):
            direction = 1 if seg % 2 == 0 else -1
            for i in range(1, 6):
                move(cx + direction * i * 16, y_body)
                settle(pet, 0.012)

    # 7) 摇一摇 -> 摇头（默认不刷新）
    settle(pet, 1.4)
    pet._body_track = []
    pet._last_extra_gesture = 0.0
    base = hits(pet)
    shake_it()
    shake = gained(pet, base, "shake")
    shaking = pet._shake_head_until > pet._now()
    print("shake head : shake hits +%d shaking=%s" % (shake, shaking))
    ok_shake = shake >= 1 and shaking

    # 8) 摇一摇 -> 刷新（设置打开以后）
    settle(pet, 1.4)
    pet.set_shake_refresh(True, quiet=True)
    calls = []
    orig_refresh = pet.refresh_pet

    def counting_refresh():
        calls.append(1)
        orig_refresh()

    pet.refresh_pet = counting_refresh
    try:
        pet._body_track = []
        pet._last_extra_gesture = 0.0
        base = hits(pet)
        shake_it()
        settle(pet, 0.5)
        shake_refresh = gained(pet, base, "shake")
        print("shake fresh: shake hits +%d refresh calls=%d"
              % (shake_refresh, len(calls)))
        ok_shake_refresh = shake_refresh >= 1 and bool(calls)
    finally:
        pet.refresh_pet = orig_refresh
        pet.set_shake_refresh(False, quiet=True)

    # 9) 0.9 秒内连着下滑两次 -> 弹一下
    settle(pet, 1.2)
    pet.visible = True
    pet._next_visible_check = pet._now() + 3600.0
    pet._last_squash_at = 0.0
    pet.jump = 0.0
    base = hits(pet)
    swipe(pet, x, top, bottom)
    swipe(pet, x, top, bottom)
    bounce = gained(pet, base, "bounce")
    print("double down: bounce hits +%d jump=%.2f" % (bounce, pet.jump))
    ok_bounce = bounce >= 1

    # 10) 按住头顶不动一秒 -> 摸头
    settle(pet, 1.2)
    pet.visible = True
    pet._next_visible_check = pet._now() + 3600.0
    hx, hy = pet.head_anchor()
    pet._pet_energy = 0.0
    pet.petting_until = 0.0
    pet.press_pos = (int(hx), int(hy), pet.win_x, pet.win_y)
    pet.moved = False
    pet._hold_petted = False
    pet._press_at = pet._now() - 1.2
    base = hits(pet)
    settle(pet, 0.3)
    hold = gained(pet, base, "hold")
    print("hold head  : hold hits +%d petting_until-now=%.2f"
          % (hold, pet.petting_until - pet._now()))
    ok_hold = hold >= 1 and pet.petting_until > pet._now()
    pet.press_pos = None
    pet.moved = False
    pet._hold_petted = False

    pet.quit()
    ok = (ok_squash and ok_relax and ok_jump and ok_dodge and ok_spin
          and ok_covered and ok_shake and ok_shake_refresh and ok_bounce
          and ok_hold)
    print("GESTURE LIVE OK" if ok else "GESTURE LIVE FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
