"""自检：卡死时看门狗真的能把它救回来。

做法：故意让主线程 sleep 10.5 秒（不跑 Tk 循环 = 典型的"卡住"），
看门狗线程应该在 9 秒时自己动手（藏气泡 + 排一次刷新），
主线程醒来后 _tick 执行刷新，宠物仍然活着、气泡还能用。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import desktop_pet as dp                                     # noqa: E402


def settle(pet, seconds):
    end = time.time() + seconds
    while time.time() < end:
        pet.root.update()
        time.sleep(0.015)


def main():
    backup = os.path.join(ROOT, "pet_config.watchdog_backup.json")
    cfg = dp.CONFIG_PATH
    if os.path.exists(cfg):
        os.replace(cfg, backup)
    pet = None
    try:
        pet = dp.DesktopPet(use_ai=False, topmost=True, bubble=True)
        settle(pet, 0.6)
        pet.speak("我先说一句话，等会儿会卡住。")
        settle(pet, 0.6)
        bubble_hwnd = pet.bubble.hwnd

        # 主线程装死 10.5 秒：9 秒时看门狗应该已经出手
        time.sleep(10.5)
        print("rescued at: %.2f  refresh_requested=%s"
              % (pet._rescue_at, pet._refresh_requested))
        assert pet._rescue_at > 0, "watchdog never fired"
        assert pet._refresh_requested, "watchdog did not request a refresh"

        # 醒来后跑一会儿，让 _tick 把刷新做完
        settle(pet, 1.5)
        assert pet._alive, "pet died during rescue"
        assert pet.bubble is not None, "bubble missing after rescue"
        assert not pet._refresh_requested, "refresh flag should be cleared"
        print("watchdog end-to-end ok, bubble hwnd was", hex(bubble_hwnd or 0))

        # 关掉手势之后，动画和 tick 不能跟着停
        pet.set_gestures_enabled(False)
        settle(pet, 0.3)
        mark = pet._last_tick
        settle(pet, 0.8)
        assert pet._last_tick > mark, "tick stopped when gestures disabled"
        pet.set_gestures_enabled(True)
        print("gestures off keeps ticking ok")
        return 0
    finally:
        if pet is not None:
            try:
                pet.quit()
            except Exception:                               # noqa: BLE001
                pass
        if os.path.exists(backup):
            os.replace(backup, cfg)


if __name__ == "__main__":
    sys.exit(main())
