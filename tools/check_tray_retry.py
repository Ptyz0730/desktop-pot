# -*- coding: utf-8 -*-
"""验证托盘注册的"定时重试"：前 6 次故意失败（超过初始 4 次），后面成功。

注意：现在托盘失败**不再**在任务栏建占位窗口（用户只要右下角「^」里的图标），
所以这里除了断言"重试最终成功"，还要断言"没有偷偷冒出一个任务栏按钮"。
"""
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import desktop_pet as dp  # noqa: E402

ok = True


def check(label, cond, extra=""):
    global ok
    print(("  ok  " if cond else "  FAIL") + " " + label + (("  " + extra) if extra else ""))
    if not cond:
        ok = False


def settle(pet, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pet.root.update()
        time.sleep(0.02)


CFG = dp.CONFIG_PATH
BAK = CFG + ".tray_bak"
if os.path.exists(CFG):
    shutil.copy2(CFG, BAK)
try:
    if os.path.exists(CFG):
        os.remove(CFG)
    calls = {"n": 0}
    real_add = dp.TrayIcon._add

    def flaky_add(self):
        calls["n"] += 1
        if calls["n"] <= 6:
            return False
        return real_add(self)

    dp.TrayIcon._add = flaky_add
    pet = dp.DesktopPet(use_ai=False, bubble=False)
    settle(pet, 0.4)
    tray = getattr(pet, "tray", None)
    check("构造时 4 次失败 -> tray 对象仍在（后台继续重试）", tray is not None)
    check("失败时不在任务栏建按钮", getattr(pet, "taskbar_win", None) is None)
    t0 = time.monotonic()
    while tray is not None and not tray.ok and time.monotonic() - t0 < 15:
        settle(pet, 0.25)
    check("定时重试后注册成功", bool(tray is not None and tray.ok),
          "calls=%d 用了 %.1fs" % (calls["n"], time.monotonic() - t0))
    settle(pet, 0.6)
    check("仍然没有任务栏按钮", getattr(pet, "taskbar_win", None) is None)
    dp.TrayIcon._add = real_add
    pet.quit()
finally:
    try:
        if os.path.exists(CFG):
            os.remove(CFG)
        if os.path.exists(BAK):
            shutil.move(BAK, CFG)
    except Exception:                       # noqa: BLE001
        pass

print("TRAY RETRY OK" if ok else "TRAY RETRY FAILED")
sys.exit(0 if ok else 1)
