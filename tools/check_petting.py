# -*- coding: utf-8 -*-
"""摸头自检：手势判定、动画状态、爱心粒子、截图。

用临时配置启动，不会碰用户的 pet_config.json。
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import desktop_pet as dp  # noqa: E402


def settle(pet, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pet.root.update()
        time.sleep(0.01)


def main():
    cfg = os.path.join(tempfile.gettempdir(), "pet_petting_check.json")
    with open(cfg, "w", encoding="utf-8") as fh:
        fh.write('{"image": "chm_love_me.png", "scale": 0.5, "bubble": false,'
                 ' "ai": false, "style": "colorkey"}')
    dp.CONFIG_PATH = cfg
    pet = dp.DesktopPet(style="colorkey", topmost=True, bubble=False, use_ai=False)
    ok = True
    settle(pet, 0.5)
    if pet._mouse_hook:
        pet._mouse_hook.remove()
        pet._mouse_hook = None
    # 只喂本测试自己的鼠标轨迹；否则真实光标刚好停在宠物头上会让状态续期
    pet._poll_cursor = lambda: None
    # 桌宠现在固定待在桌面层（顶栏不再置顶），这台机器前台是最大化的浏览器，
    # 宠物会被判成 covered —— _tick_body 在可见性检查那步就 return，摸头的
    # 动画/粒子全都不跑。测试里直接认定"露在桌面上"，别让环境决定结果。
    pet.visible = True
    pet._next_visible_check = time.time() + 3600

    sprite_top = pet.win_y + pet.headroom
    print("win=(%d,%d) sprite=%s head_zone_y=%.0f..%.0f"
          % (pet.win_x, pet.win_y, pet.sprite.size,
             sprite_top - max(6, int(round(10 * pet.scale))),
             sprite_top + pet.sh * 0.34))

    # 1) 单次横着划过去（没有回头）不该触发
    cx = pet.win_x + pet.win_w // 2
    cy = pet.win_y + pet.headroom + max(4, int(pet.sh * 0.12))
    pet._pet_reset_gesture()
    pet._pet_last_seen = 0
    for i in range(9):
        pet._on_mouse_move(cx - 80 + i * 20, cy)
        time.sleep(0.04)
    print("单次横划: 触发次数=%d（应为 0）" % pet.petting_count)
    if pet.petting_count:
        ok = False

    # 2) 左右蹭 -> 触发
    pet._pet_reset_gesture()
    fired = pet.simulate_pet_head(cycles=3, duration=0.6)
    settle(pet, 0.14)
    kinds = {}
    for p in pet.hearts.particles:
        kinds[p.kind] = kinds.get(p.kind, 0) + 1
    print("左右蹭: fired=%s count=%d active=%s energy=%.2f particles=%s ripples=%d"
          % (fired, pet.petting_count, pet.petting_active(),
             pet._pet_energy, kinds, len(pet.hearts.ripples)))
    if not fired or not pet.petting_active():
        print("  FAIL: 左右蹭没有触发摸头")
        ok = False
    if not pet.hearts.particles:
        print("  FAIL: 没有爱心粒子")
        ok = False
    if not kinds.get("sparkle"):
        print("  FAIL: 没有小星星粒子")
        ok = False
    if not pet.hearts.ripples:
        print("  FAIL: 没有拍头扩散圈")
        ok = False
    if pet.hearts.win is not None:
        ex = dp._user32.GetWindowLongW(dp._hwnd_of(pet.hearts.win), -20)
        print("  hearts window shown=%s rect=%s state=%s exstyle=%s"
              % (pet.hearts.shown, pet.hearts.rect,
                 pet.hearts.win.state(), hex(ex)))
        if not (ex & dp.WS_EX_TRANSPARENT):
            print("  FAIL: 爱心窗口没有鼠标穿透")
            ok = False

    # 2.5) chm 专属摸头弹幕：中日双语、会移动、鼠标穿透
    print("弹幕: allowed=%s items=%d shown=%s rect=%s phrases=%s"
          % (pet.danmaku_allowed(), len(pet.danmaku.items),
             pet.danmaku.shown, pet.danmaku.rect,
             [(i.jp, i.cn) for i in pet.danmaku.items]))
    if not pet.danmaku_allowed():
        print("  FAIL: chm 图没有启用弹幕")
        ok = False
    if not pet.danmaku.items:
        print("  FAIL: 摸头没有弹出弹幕")
        ok = False
    else:
        jp, cn = pet.danmaku.items[0].jp, pet.danmaku.items[0].cn
        if "きもちいい" not in jp:
            print("  FAIL: 日语不是 きもちいい")
            ok = False
        if "好舒服" not in cn:
            print("  FAIL: 中文不是 好舒服")
            ok = False
    if pet.danmaku.win is not None and dp._user32 is not None:
        ex = dp._user32.GetWindowLongW(dp._hwnd_of(pet.danmaku.win), -20)
        if not (ex & dp.WS_EX_TRANSPARENT):
            print("  FAIL: 弹幕窗口没有鼠标穿透")
            ok = False
    y_before = pet.danmaku.items[0].y if pet.danmaku.items else None
    settle(pet, 0.3)
    if pet.danmaku.items and y_before is not None:
        if not pet.danmaku.items[0].y < y_before:
            print("  FAIL: 弹幕没有往上漂")
            ok = False

    # 3) 动画确实在动（连续几帧的 pet_dy / 渲染尺寸）
    samples = []
    for _ in range(10):
        pet.root.update()
        samples.append((round(pet._pet_dx, 2), round(pet._pet_dy, 2),
                        round(pet._pet_angle, 2), pet._squash_factor()))
        time.sleep(0.03)
    print("动画采样:", samples)
    if len({s[1] for s in samples}) < 2:
        print("  FAIL: 摸头位移没有变化")
        ok = False
    if max(abs(s[1]) for s in samples) < 3.0:
        print("  FAIL: 下压幅度太小，看不出来")
        ok = False
    if max(abs(s[2]) for s in samples) < 0.4:
        print("  FAIL: 身体没有倾斜")
        ok = False

    # 4) 截图（宠物 + 头顶爱心 + 弹幕）
    try:
        from PIL import ImageGrab
        left = max(0, pet.win_x - 720)
        top = max(0, pet.win_y - 240)
        if pet.danmaku.rect:
            top = min(top, max(0, pet.danmaku.rect[1] - 10))
        right = min(1920, pet.win_x + pet.win_w + 80)
        bottom = min(1080, pet.win_y + pet.win_h + 20)
        shot = os.path.join(tempfile.gettempdir(), "pet_petting_check.png")
        ImageGrab.grab(bbox=(left, top, right, bottom)).save(shot)
        print("截图:", shot)
    except Exception as exc:                    # noqa: BLE001
        print("截图失败:", exc)

    # 5) 收手后爱心飘完、状态收掉
    settle(pet, 3.2)
    print("收手后: active=%s particles=%d energy=%.3f shown=%s"
          % (pet.petting_active(), len(pet.hearts.particles),
             pet._pet_energy, pet.hearts.shown))
    if pet.hearts.particles:
        print("  FAIL: 爱心没有飘完")
        ok = False
    if pet.hearts.shown:
        print("  FAIL: 爱心窗口没有隐藏")
        ok = False
    if pet.danmaku.items or pet.danmaku.shown:
        print("  FAIL: 弹幕没有收干净")
        ok = False

    # 6) 换一张非 chm 的图：摸头照常，但不能有弹幕
    pet.set_image("中性灰.png")
    settle(pet, 0.35)
    pet.danmaku.clear()
    pet._pet_reset_gesture()
    pet.simulate_pet_head(cycles=3, duration=0.55)
    settle(pet, 0.3)
    print("非 chm: allowed=%s items=%d count=%d"
          % (pet.danmaku_allowed(), len(pet.danmaku.items),
             pet.petting_count))
    if pet.danmaku_allowed() or pet.danmaku.items:
        print("  FAIL: 非 chm 图也弹了摸头弹幕")
        ok = False

    pet.quit()
    settle(pet, 0.05)
    print("PETTING CHECK %s" % ("OK" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
