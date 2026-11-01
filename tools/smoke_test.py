# -*- coding: utf-8 -*-
"""Drive the pet through its states without a human, for both backends."""
import os
import sys
import time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import desktop_pet as dp  # noqa: E402


def settle(pet, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pet.root.update()
        time.sleep(0.015)


def exercise(style):
    """colorkey 是默认且在本机可渲染的路径，断言要全过；
    layered 在本机不被 DWM 合成，只保证不抛异常地跑完。

    测试里用 topmost=True：默认模式（贴桌面）会被浏览器这种全屏窗口盖住，
    按设计就该暂停动画，那样位置类的断言没法稳定测量。覆盖检测本身单独测。
    """
    rendered = style == "colorkey"
    pet = dp.DesktopPet(bubble=True, style=style, topmost=True)
    ok = True
    print("[%s] backend=%s win=%s sprite=%s image=%s"
          % (style, pet.backend.style, (pet.win_w, pet.win_h), pet.sprite.size,
             pet.image_name))
    settle(pet, 0.4)
    if not pet.visible:
        print("  FAIL: pet should stay visible in topmost mode")
        ok = False

    # bubble layout: long text must wrap inside the card
    pet.speak("测试气泡：这一句比较长，用来验证自动换行和卡片高度是否正确，"
              "并且不应该有任何字符被卡片裁掉。")
    settle(pet, 0.3)
    p = pet.bubble._plan
    f = pet.bubble._tkfont
    widest = max(f.measure(ln) for ln in p["lines"])
    print("  bubble %dx%d lines=%d widest=%d max=%d"
          % (p["w"], p["h"], len(p["lines"]), widest, dp.SpeechBubble.MAX_W))
    if widest > dp.SpeechBubble.MAX_W:
        print("  FAIL: a line is wider than the wrap limit")
        ok = False
    if p["h"] < len(p["lines"]) * p["line_h"]:
        print("  FAIL: card too short for its lines")
        ok = False

    # the tail must stay glued to the head while the pet moves
    def tail_gap():
        b = pet.bubble
        ax, ay = pet.head_anchor()
        tip = b.win.winfo_y() if b._below else b.win.winfo_y() + b._plan["card_bottom"]
        return ((tip - ay) if b._below else (ay - tip),
                abs(b.win.winfo_x() + b._plan["tail_x"] - ax))

    gap, dx = tail_gap()
    # 移动时用 clamp_pos 保证还留在屏幕里：默认生成位置在右上角，
    # 直接减 120 会把宠物推到屏幕外面，气泡只能贴边，尾巴自然跟不上
    pet.move(*pet.clamp_pos(pet.win_x - 250, pet.win_y - 120))
    settle(pet, 0.5)
    gap2, dx2 = tail_gap()
    print("  tail gap: before=%.0f after=%.0f  head dx: %.0f/%.0f" % (gap, gap2, dx, dx2))
    # 贴着屏幕边缘时 tail_x 会被夹在卡片内（有意为之），移动后允许偏移；
    # layered 在本机不渲染，几何值不可信，那一轮不校验这一条。
    if rendered and style == "colorkey" and not (0 <= gap <= 6
                                                and 0 <= gap2 <= 6
                                                and dx <= 2 and dx2 <= 40):
        print("  FAIL: bubble tail detached from the head while tracking")
        ok = False

    # dragging (clamped)
    class E(object):
        pass
    e = E()
    e.x_root, e.y_root = pet.win_x + 40, pet.win_y + 40
    pet._on_press(e)
    e.x_root, e.y_root = e.x_root - 120, e.y_root - 160
    pet._on_drag(e)
    pet._on_release(e)
    settle(pet, 0.2)
    print("  after drag: pos=%s" % (pet.pos,))

    # work area must exclude the taskbar
    wa = dp.work_area(pet.root)
    pet.reset_position()
    settle(pet, 0.3)
    print("  work area=%s reset pos=%s (bottom %d)" % (wa, pet.pos, pet.win_y + pet.win_h))
    if rendered and pet.win_y + pet.win_h > wa[3] + 1:
        print("  FAIL: pet stands behind the taskbar")
        ok = False

    # 每一张立绘都要能加载并重新设定抠底色（这条路径以前崩过）
    names = [im.name for im in pet.images]
    pet.bubble_var.set(False)
    pet.toggle_bubble()
    for name in names:
        pet.set_image(name)
        settle(pet, 0.15)
    pet.bubble_var.set(True)
    pet.toggle_bubble()
    settle(pet, 0.2)
    print("  立绘轮换 %d 张 OK（过程中关/开气泡），当前=%s" % (len(names), pet.image_name))

    # bubble flip near the top of the screen
    pet.move(pet.win_x, 0)
    settle(pet, 0.2)
    pet.speak("贴到屏幕最上面时，气泡应该翻到宠物下面。")
    settle(pet, 0.2)
    if not pet.bubble._below:
        print("  FAIL: bubble did not flip below at screen top")
        ok = False
    else:
        print("  top flip ok (bubble below the head)")

    # animation must actually move (one breath cycle takes ~4 s at 40 ms/frame)
    moves = set()
    end = time.monotonic() + 2.5
    while time.monotonic() < end:
        pet.root.update()
        time.sleep(0.02)
        moves.add(pet._frame_for_phase()[1])
    print("  animation frames seen: %s" % sorted(moves))
    if len(moves) < 2:
        print("  FAIL: breathing animation is static")
        ok = False

    # feature toggles
    pet.ct_var.set(True)
    pet.toggle_click_through()
    pet.ct_var.set(False)
    pet.toggle_click_through()
    pet.reset_position()
    settle(pet, 0.2)
    print("  toggles + reset ok")

    pet.quit()
    settle(pet, 0.05)
    return ok


def exercise_ai(use_network):
    """对话链路自检：不联网时只验证接线，联网时真发一轮请求。

    在线/离线都跑不了的路径（真正的对话框需要人手输入）用直接调用 ask_ai 覆盖。
    """
    import desktop_pet as dp

    ok = True
    # 显式要气泡：这条用例靠读气泡内容判断，不能受 pet_config.json 里
    # "显示气泡" 关没关的影响
    pet = dp.DesktopPet(style="colorkey", use_ai=use_network, topmost=True, bubble=True)
    settle(pet, 0.3)
    print("[ai] enabled=%s brain=%s model=%s" %
          (pet.ai_enabled, pet.brain.enabled, pet.brain.model))

    if not use_network:
        # 关掉 AI 时必须回退到内置话术，不能卡在省略号上
        pet.speak_random()
        settle(pet, 0.3)
        lines = pet.bubble._plan["lines"] if pet.bubble._plan else []
        print("  offline fallback bubble: %r" % (lines,))
        if not lines or lines[0] == dp.PENDING_TEXT:
            print("  FAIL: no fallback line when AI is off")
            ok = False
        pet.quit()
        return ok

    if not pet.brain.api_key:
        print("  skip: 本机没有 API key（菜单里可以设置，或用环境变量 "
              "DESKTOP_PET_API_KEY），跳过联网对话这一项")
        pet.quit()
        return ok

    turns_before = pet.brain.turns
    pet.ask_ai("用一句话介绍你自己")
    started = time.monotonic()
    got = None
    while time.monotonic() - started < 30:
        pet.root.update()
        time.sleep(0.05)
        if pet.brain.turns > turns_before and not pet.user_busy:
            got = pet.bubble._plan["lines"] if pet.bubble._plan else None
            break
    took = time.monotonic() - started
    print("  chat roundtrip %.1fs -> %r (error=%s)" % (took, got, pet.brain.last_error))
    if not got or dp.PENDING_TEXT in "".join(got):
        print("  FAIL: AI reply never reached the bubble")
        ok = False
    if pet.brain.last_error:
        print("  note: API reported %s" % pet.brain.last_error)
    # 这轮对话必须进历史、并且能存进配置
    if pet.brain.turns <= turns_before:
        print("  FAIL: conversation history was not recorded")
        ok = False
    pet._save_config()
    if not pet.cfg.get("brain"):
        print("  FAIL: brain state not persisted")
        ok = False
    pet.quit()
    return ok


def exercise_zorder(use_network):
    """层级与暂停：默认模式要压在窗口下面，被完全盖住时要暂停。"""
    ok = True
    pet = dp.DesktopPet(use_ai=False)
    settle(pet, 0.6)
    print("[zorder] topmost=%-5s visible=%-5s covered=%s"
          % (pet.topmost, pet.visible, pet.check_covered()))
    if pet.topmost:
        print("  FAIL: default should not be topmost")
        ok = False
    # 默认模式下宠物在窗口下面：如果测试时前面确实有全屏窗口，就应该判定被盖住
    covered = pet.check_covered()
    if covered and pet.visible:
        print("  FAIL: covered but still marked visible")
        ok = False
    if not covered and not pet.visible:
        print("  FAIL: not covered but marked invisible")
        ok = False
    # 被盖住时不该有动画/气泡
    before = pet._frame_for_phase()[1]
    settle(pet, 1.0)
    after = pet._frame_for_phase()[1]
    if covered:
        if before != after:
            print("  FAIL: animation kept running while covered")
            ok = False
        else:
            print("  paused while covered: ok")
    # 切到置顶 -> 立刻恢复
    pet.z_var.set(True)
    pet.toggle_topmost()
    settle(pet, 0.8)
    print("  after topmost: visible=%s" % pet.visible)
    if not pet.visible:
        print("  FAIL: did not resume after becoming visible")
        ok = False
    pet.quit()
    return ok


def exercise_swipe():
    """快速下滑 -> 压扁 -> 回弹；慢速/向上/离得远都不该触发。

    检测靠 _tick 里按帧轮询光标（GetCursorPos），所以测试直接用 SetCursorPos
    造真实的鼠标移动，走的是和用户一样的代码路径。
    """
    import ctypes
    from ctypes import wintypes

    ok = True
    pet = dp.DesktopPet(use_ai=False, topmost=True)
    settle(pet, 0.4)
    hook_ok = bool(pet._mouse_hook and pet._mouse_hook.ok)
    print("[swipe] 检测方式: 按帧轮询光标（全局钩子%s）"
          % ("可用，作为加速器" if hook_ok else "在本机收不到回调，已忽略"))
    if pet._mouse_hook:                     # 测试里只喂自己的动作，别让真实鼠标干扰
        pet._mouse_hook.remove()
        pet._mouse_hook = None

    u = ctypes.windll.user32
    pt = wintypes.POINT()
    u.GetCursorPos(ctypes.byref(pt))
    origin = (pt.x, pt.y)

    def real_swipe(delay, dist, upward=False):
        """真实移动光标划一次，返回这一次的过程里有没有被压扁。

        判定必须看"过程中出现过没有"：触发后 squash 每帧 -0.11，12 帧的
        循环里就会衰减回 0，只看循环结束那一刻的话，机器稍慢就必然漏判。
        """
        pet.squash = 0.0
        pet._swipe = []
        fired = False
        cx = pet.win_x + pet.win_w // 2
        base = pet.win_y - 60
        for i in range(12):
            y = base - i * (dist // 11) if upward else base + i * (dist // 11)
            u.SetCursorPos(cx, y)
            pet.root.update()               # 这一帧 _poll_cursor 会读到位移
            fired = fired or pet.squash > 0
            time.sleep(delay)
        return fired

    # 这台机器上有管控软件，合成鼠标事件可能被拦掉（SetCursorPos 返回 False、
    # 光标一动不动）。那样"真实划过"这条路根本没法验证：如实说明并跳过，
    # 不算失败 —— 压扁的几何、回弹、误触发这些下面照测。
    u.SetCursorPos(origin[0], origin[1] + 8)
    probe = wintypes.POINT()
    u.GetCursorPos(ctypes.byref(probe))
    can_move = probe.y == origin[1] + 8
    u.SetCursorPos(origin[0], origin[1])

    try:
        normal_h = pet._sprite_img().size[1]
        if can_move:
            fired = real_swipe(0.02, 240)
            squashed_h = pet._sprite_img().size[1]
            print("  真实快速下滑: 触发=%s  高度 %d -> %d" % (fired, normal_h, squashed_h))
            if not fired:
                print("  FAIL: 快速下滑没有触发压扁")
                ok = False
            if squashed_h >= normal_h * 0.8:
                print("  FAIL: 压扁幅度不够")
                ok = False
        else:
            print("  跳过真实光标划过：本会话不允许合成鼠标事件"
                  "（SetCursorPos 返回 False，光标不动）")

        # 底部要钉住（站在地上），只从上面压下来
        pet.squash = 1.0
        pet._render_squash_frame()
        gap = pet._squash_pos()
        print("  压扁时顶部下沉 %d px（底部不动）" % gap)
        if gap <= 0:
            print("  FAIL: 压扁没有从顶部下沉")
            ok = False
        if (pet.backend.style == "colorkey"
                and pet.backend._pil is not None
                and pet.backend._pil.size[1] >= normal_h):
            print("  FAIL: colorkey 后端没有把压扁后的图贴上去（set_frame 只挪坐标）")
            ok = False

        for _ in range(14):
            pet.root.update()
            time.sleep(0.04)
        print("  回弹后 squash=%.2f 高度=%d" % (pet.squash, pet._sprite_img().size[1]))
        if pet.squash > 0.001 or pet._sprite_img().size[1] != normal_h:
            print("  FAIL: 没有回弹到原样")
            ok = False

        if can_move:
            for name, kwargs in (("慢速拖动", {"delay": 0.12, "dist": 240}),
                                 ("向上划", {"delay": 0.02, "dist": 240, "upward": True}),
                                 ("位移太小", {"delay": 0.02, "dist": 40})):
                if real_swipe(**kwargs):
                    print("  FAIL: %s 不该触发" % name)
                    ok = False
            print("  慢速/向上/过短 均未触发: ok")
        else:
            print("  跳过误触发检查（同上，光标动不了）")
    finally:
        u.SetCursorPos(origin[0], origin[1])
    pet.quit()
    return ok


def exercise_petting():
    """在头顶左右蹭 -> 摸头状态 + 下压/摆动/倾斜 + 爱心/星星/拍头圈；单次横划不该触发。"""
    ok = True
    pet = dp.DesktopPet(use_ai=False, topmost=True)
    settle(pet, 0.4)
    if pet._mouse_hook:
        pet._mouse_hook.remove()
        pet._mouse_hook = None
    # 隔离真实光标：否则它刚好停在宠物头上时会把摸头状态一直续下去
    pet._poll_cursor = lambda: None
    # 启动那 0.4 秒里真实光标可能已经在头顶攒了半笔，先清掉再测"单次横划"
    pet._pet_reset_gesture()

    cx = pet.win_x + pet.win_w // 2
    cy = pet.win_y + pet.headroom + max(4, int(pet.sh * 0.12))
    for i in range(9):
        pet._on_mouse_move(cx - 80 + i * 20, cy)
        time.sleep(0.04)
    print("[petting] 单次横划触发次数=%d（应为 0）" % pet.petting_count)
    if pet.petting_count:
        print("  FAIL: 没有回头的单次横划误触发了摸头")
        ok = False

    pet._pet_reset_gesture()
    fired = pet.simulate_pet_head(cycles=3, duration=0.6)
    settle(pet, 0.14)
    kinds = {}
    for p in pet.hearts.particles:
        kinds[p.kind] = kinds.get(p.kind, 0) + 1
    print("  左右蹭 fired=%s count=%d active=%s energy=%.2f particles=%s ripples=%d"
          % (fired, pet.petting_count, pet.petting_active(), pet._pet_energy,
             kinds, len(pet.hearts.ripples)))
    if not fired or not pet.petting_active():
        print("  FAIL: 左右蹭没有触发摸头")
        ok = False
    if not kinds.get("heart"):
        print("  FAIL: 摸头没有冒爱心")
        ok = False
    if not kinds.get("sparkle"):
        print("  FAIL: 摸头没有小星星")
        ok = False
    if not pet.hearts.ripples:
        print("  FAIL: 摸头没有拍头扩散圈")
        ok = False
    if pet.hearts.win is not None and dp._user32 is not None:
        ex = dp._user32.GetWindowLongW(dp._hwnd_of(pet.hearts.win), -20)
        if not (ex & dp.WS_EX_TRANSPARENT):
            print("  FAIL: 爱心窗口没有鼠标穿透（会挡住点击）")
            ok = False
        else:
            print("  爱心窗口：鼠标穿透 ok")

    # 动画不是静止的：连续采样的下压/摆动/倾角必须有明显变化
    moves = []
    for _ in range(10):
        pet.root.update()
        moves.append((round(pet._pet_dx, 2), round(pet._pet_dy, 2),
                      round(pet._pet_angle, 2)))
        time.sleep(0.03)
    print("  摸头动画采样: %s" % moves)
    if len(set(moves)) < 3:
        print("  FAIL: 摸头动画几乎是静止的")
        ok = False
    if max(abs(m[1]) for m in moves) < 3.0:
        print("  FAIL: 下压幅度太小")
        ok = False
    if max(abs(m[2]) for m in moves) < 0.4:
        print("  FAIL: 身体倾斜太小")
        ok = False

    # 收手后：状态收掉、爱心飘完、窗口隐藏
    settle(pet, 3.2)
    print("  收手后 active=%s hearts=%d energy=%.3f shown=%s"
          % (pet.petting_active(), len(pet.hearts.particles),
             pet._pet_energy, pet.hearts.shown))
    if pet.petting_active() or pet.hearts.particles or pet.hearts.shown:
        print("  FAIL: 收手后摸头状态/爱心没有收干净")
        ok = False

    pet.quit()
    return ok


def exercise_gestures():
    """上划跳、身体横划躲、绕圈转晕、右键菜单手势、打飞机。"""
    import math

    ok = True
    pet = dp.DesktopPet(image="chm_love_me.png", use_ai=False, topmost=True)
    settle(pet, 0.4)
    if pet._mouse_hook:
        pet._mouse_hook.remove()
        pet._mouse_hook = None
    pet._poll_cursor = lambda: None
    pet.reset_position()
    settle(pet, 0.2)

    cx = pet.win_x + pet.win_w // 2
    base = pet.win_y + pet.headroom + 80
    pet.jump = 0.0
    pet._last_extra_gesture = 0.0
    pet._swipe = []
    for i in range(9):
        pet._on_mouse_move(cx, base - i * 22)
        time.sleep(0.02)
    settle(pet, 0.1)
    print("[gestures] 上划 jump=%.2f" % pet.jump)
    if pet.jump <= 0:
        print("  FAIL: 上划没有跳")
        ok = False

    pet._last_extra_gesture = 0.0
    pet._dodge_until = 0.0
    pet._body_track = []
    by = pet.win_y + pet.win_h - 55
    for i in range(9):
        pet._on_mouse_move(pet.win_x + 20 + i * 25, by)
        time.sleep(0.02)
    settle(pet, 0.1)
    print("  身体横划 dodge_dx=%.1f dir=%d" % (pet._dodge_dx, pet._dodge_dir))
    if pet._dodge_until <= pet._now() or pet._dodge_dx == 0:
        print("  FAIL: 身体横划没有躲")
        ok = False

    pet._last_extra_gesture = 0.0
    pet._circle_track = []
    ccx = pet.win_x + pet.win_w // 2
    ccy = pet.win_y + pet.win_h - pet.sh * pet.scale * 0.46
    radius = max(60, pet.win_w * 0.42)
    before_spin = pet.spin_count
    for i in range(34):
        ang = -math.pi / 2 + i * (math.tau * 1.15 / 34)
        pet._on_mouse_move(ccx + radius * math.cos(ang),
                           ccy + radius * math.sin(ang))
        time.sleep(0.02)
    settle(pet, 0.1)
    print("  绕圈 spin=%d angle=%.1f" % (pet.spin_count, pet._spin_angle))
    if pet.spin_count <= before_spin:
        print("  FAIL: 绕圈没有转晕")
        ok = False

    labels = []
    for i in range(pet._play_menu.index("end") + 1):
        try:
            labels.append(pet._play_menu.entrycget(i, "label"))
        except tk.TclError:
            labels.append("---")
    print("  右键菜单: %s" % labels)
    if "打飞机（chm）" not in labels:
        print("  FAIL: 右键菜单里没有打飞机")
        ok = False

    pet.trigger_shooting()
    home_x = getattr(pet, "_shoot_home_x", pet.win_x)
    # 把所有飞机挪到左边，确保能测到"追过去锁飞机"
    for _p in pet.shoot_fx.planes:
        _p.x = home_x + pet.win_w / 2.0 - 150
    settle(pet, 0.45)
    planes = len(pet.shoot_fx.planes)
    bullets = len(pet.shoot_fx.bullets)
    factor = pet._squash_factor()
    wide = pet._wide_factor()
    print("  打飞机 planes=%d bullets=%d factor=%.2f wide=%.2f shown=%s moved=%d"
          % (planes, bullets, factor, wide, pet.shoot_fx.shown,
             pet.win_x - home_x))
    if not planes or not bullets:
        print("  FAIL: 打飞机没有飞机/子弹")
        ok = False
    if factor < 1.08 or wide > 0.94:
        print("  FAIL: chm 没有明显拉长变扁")
        ok = False
    if not pet.shoot_fx.shown:
        print("  FAIL: 打飞机窗口没有显示")
        ok = False
    if abs(pet.win_x - home_x) < 2:
        print("  FAIL: chm 没有自己移动去锁飞机")
        ok = False

    settle(pet, 6.0)
    print("  结束后 shooting=%s fx_active=%s energy=%.3f back_home=%s"
          % (pet.shooting_active(), pet.shoot_fx.active(), pet._shoot_energy,
             abs(pet.win_x - home_x) <= 3))
    if pet.shooting_active() or pet.shoot_fx.active():
        print("  FAIL: 打飞机结束后没有收干净")
        ok = False
    if abs(pet.win_x - home_x) > 3:
        print("  FAIL: 打飞机结束后没有滑回原位")
        ok = False

    pet.quit()
    return ok


def exercise_modifier():
    """修改器：密码圆点、错误密码拒绝、正确密码后可改好感度。"""
    ok = True
    pet = dp.DesktopPet(image="chm_love_me.png", use_ai=False, topmost=True)
    settle(pet, 0.4)
    old = pet.affection
    dlg = dp.ModifierDialog(pet)
    dlg._build()
    settle(pet, 0.1)
    print("[modifier] show=%r unlocked=%s" % (dlg.entry.cget("show"), dlg.unlocked))
    if dlg.entry.cget("show") != "●":
        print("  FAIL: 密码框没有变成圆点")
        ok = False
    dlg.entry.insert(0, "wrong")
    dlg._unlock()
    if dlg.unlocked:
        print("  FAIL: 错误密码也解锁了")
        ok = False
    dlg.entry.delete(0, "end")
    dlg.entry.insert(0, dp.MODIFIER_PASSWORD)
    dlg._unlock()
    print("  正确密码 unlocked=%s" % dlg.unlocked)
    if not dlg.unlocked:
        print("  FAIL: 正确密码没有解锁")
        ok = False
    dlg.value_var.set(37)
    dlg._apply()
    settle(pet, 0.1)
    print("  好感度 -> %d" % pet.affection)
    if pet.affection != 37:
        print("  FAIL: 好感度没有改成 37")
        ok = False
    dlg._close()
    pet.set_affection(old)
    pet.quit()
    return ok


def exercise_ime():
    """对话框要能拿到 IME：窗口可见、输入框拿到焦点、且能成为前台窗口。

    注意：本机这个会话完全禁止前台激活（连记事本都拿不到 GetFocus），
    所以"抢到前台"这步在这里无法验证，只作为环境说明报告，不算失败。
    """
    ok = True
    pet = dp.DesktopPet(use_ai=False, topmost=True)
    settle(pet, 0.4)
    dlg = dp.ChatDialog(pet)
    done = {"v": False}

    def probe(_e=None):
        nonlocal ok
        if done["v"]:
            return
        done["v"] = True
        for _ in range(20):
            pet.root.update()
        import ctypes
        u = ctypes.windll.user32
        top = dlg.win.winfo_id()
        ent = dlg.entry.winfo_id()
        focus = u.GetFocus()
        fg = u.GetForegroundWindow()
        visible = bool(u.IsWindowVisible(top))
        # 当前前台窗口属于哪个进程：如果不是我们，说明外部程序占着前台，
        # 抢前台的结果无法断言（Windows 也不允许后台进程随便抢）
        pid = ctypes.c_ulong()
        u.GetWindowThreadProcessId(fg, ctypes.byref(pid))
        ours = pid.value == os.getpid()
        print("  对话框可见=%s  输入框有焦点=%s  前台属于本进程=%s"
              % (visible, focus == ent, ours))
        if not visible:
            print("  FAIL: 对话框不可见")
            ok = False
        if not ours:
            print("  环境说明: 前台被别的进程占着（PID %d），抢前台的结果无法断言；"
                  "真实使用时点一下对话框即可" % pid.value)
        try:
            imm = ctypes.windll.imm32
        except OSError:
            imm = None
        ctx = imm.ImmGetContext(ent) if imm else 0
        if not ctx:
            print("  FAIL: 输入框拿不到 IME 上下文")
            ok = False
        else:
            print("  IME 上下文可用, OpenStatus=%s" % imm.ImmGetOpenStatus(ctx))
            imm.ImmReleaseContext(ent, ctx)
        dlg.win.after(120, dlg.cancel)

    _orig = dlg._place

    def arm():
        _orig()
        dlg.win.bind("<Map>", lambda e: dlg.win.after(250, probe), add="+")

    dlg._place = arm
    pet.root.after(5000, pet.quit)
    dlg.ask()
    pet.quit()
    return ok


def main():
    online = "--offline" not in sys.argv
    results = [exercise(s) for s in ("colorkey", "layered")]
    results.append(exercise_zorder(online))
    results.append(exercise_swipe())
    results.append(exercise_petting())
    results.append(exercise_gestures())
    results.append(exercise_modifier())
    results.append(exercise_ime())
    results.append(exercise_ai(online))
    print("SMOKE TEST %s" % ("OK" if all(results) else "FAILED"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
