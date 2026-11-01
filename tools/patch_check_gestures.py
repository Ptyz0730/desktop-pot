# -*- coding: utf-8 -*-
"""给 check_gestures_live.py 追加：摇一摇 / 摇一摇刷新 / 双下滑弹跳 / 长按摸头。"""
import io

P = 'tools/check_gestures_live.py'
s = io.open(P, encoding='utf-8').read()

old = '''    pet.quit()
    ok = ok_squash and ok_relax and ok_jump and ok_dodge and ok_spin and ok_covered
    print("GESTURE LIVE OK" if ok else "GESTURE LIVE FAILED")
    return 0 if ok else 1'''

new = '''    def shake_it():
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
    return 0 if ok else 1'''

assert old in s
s = s.replace(old, new, 1)
io.open(P, 'w', encoding='utf-8', newline='').write(s)
print('gesture live test extended')
