"""Soak test: hammer the pet the way a bored user would, watch for stalls.

点气泡、拖、双击、手势、换形象、开关设置窗口 —— 连续 15 秒，同时盯着
`pet._last_tick` 的心跳间隔。任何一步卡住，间隔都会立刻掉下去。
"""

import math
import os
import sys
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import desktop_pet as dp  # noqa: E402


def settle(pet, seconds):
    end = time.time() + seconds
    while time.time() < end:
        pet.root.update()
        time.sleep(0.01)


def fake_event(x, y):
    return types.SimpleNamespace(x=x, y=y, x_root=x, y_root=y,
                                 num=1, delta=0, widget=None)


LINES = ["我在这儿。", "今天也辛苦啦。", "要不要休息一下？",
         "这个气泡是故意很长的，用来测试排版会不会把主线程拖住。",
         "嗯。", "再点一下试试？"]


def swipe_synth(pet, x, y0, y1, steps=10):
    """直接用采样喂手势（等价于真光标快速划过），复现"做动作卡不卡"。"""
    for step in range(steps + 1):
        pet._on_mouse_move(x, y0 + (y1 - y0) * step / float(steps))
        settle(pet, 0.012)


def main():
    pet = dp.DesktopPet(use_ai=False, bubble=True)
    pet._poll_cursor = lambda: None
    pet.visible = True
    pet._next_visible_check = time.time() + 3600
    settle(pet, 0.5)

    base = pet._last_tick
    worst = 0.0
    tests = 0
    end = time.time() + 15.0
    while time.time() < end:
        tests += 1
        i = tests % 10
        if i == 0:
            pet.speak(LINES[tests % len(LINES)])
        elif i == 1:
            pet._on_press(fake_event(pet.win_x + 40, pet.win_y + 120))
            pet._on_release(fake_event(pet.win_x + 40, pet.win_y + 120))
        elif i == 2:
            pet._on_press(fake_event(pet.win_x + 40, pet.win_y + 120))
            for step in range(6):
                pet._on_drag(fake_event(pet.win_x + 40 + step * 9,
                                        pet.win_y + 120 - step * 4))
                settle(pet, 0.01)
            pet._on_release(fake_event(pet.win_x + 90, pet.win_y + 100))
        elif i == 3:
            pet._on_double(fake_event(pet.win_x + 40, pet.win_y + 120))
        elif i == 4:
            pet.do_gesture("spin")
        elif i == 5:
            pet.do_gesture("jump")
        elif i == 6:
            pet.speak_random()
        elif i == 7:
            pet.bubble.hide()
        elif i == 8:
            # 快速下滑压扁（用户报"动作卡死"就发生在这类路径上）
            cx = pet.win_x + pet.win_w // 2
            swipe_synth(pet, cx, pet.win_y + pet.headroom + 20,
                        pet.win_y + pet.win_h - 20)
        else:
            # 快速上划跳一下
            cx = pet.win_x + pet.win_w // 2
            swipe_synth(pet, cx, pet.win_y + pet.win_h - 20,
                        pet.win_y + pet.headroom + 20)
        settle(pet, 0.08)
        now = time.monotonic()
        gap = now - pet._last_tick
        worst = max(worst, gap)
        if not pet._alive:
            print("pet died at test %d" % tests)
            return 1

    # 气泡/窗口没泄漏：连着说 30 句也不该攒出一堆 Toplevel
    wins_before = len(pet.root.winfo_children())
    for n in range(30):
        pet.speak("第 %d 句，检查窗口有没有越积越多。" % n)
        settle(pet, 0.03)
    wins_after = len(pet.root.winfo_children())

    settle(pet, 0.6)
    squash_left = pet.squash
    print("tests=%d worst_heartbeat_gap=%.2fs squash_after=%.2f"
          % (tests, worst, squash_left))
    print("children before=%d after=%d" % (wins_before, wins_after))
    log = os.path.join(ROOT, "pet_error.log")
    size = os.path.getsize(log) if os.path.exists(log) else 0
    print("pet_error.log bytes:", size)
    ok = (worst < 2.0 and pet._alive and wins_after <= wins_before + 1
          and size == 0 and squash_left < 0.05)
    pet.quit()
    print("SOAK OK" if ok else "SOAK FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    # 上一次（比如 check_watchdog）故意写进去的告警不算这次的锅，先清掉
    log = os.path.join(ROOT, "pet_error.log")
    try:
        if os.path.exists(log):
            os.remove(log)
    except OSError:
        pass
    sys.exit(main())
