"""压力复现：一边放动作，一边点宠物让气泡弹出来，看主线程会不会卡死。

用法（用带 Pillow 的 Python 跑）：
    python tools\\stress_bubble.py [秒数]
结果写在 stress.log；卡死超过 STALL_S 秒就把所有线程的栈 dump 出来再退出。
"""
import ctypes
import faulthandler
import os
import random
import sys
import threading
import time
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import desktop_pet as dp                      # noqa: E402

DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 40.0
STALL_S = 3.5

LOG = open(os.path.join(ROOT, "stress.log"), "w", encoding="utf-8", buffering=1)
T0 = time.monotonic()


def log(*args):
    print("[%7.3f]" % (time.monotonic() - T0), *args, file=LOG)


faulthandler.enable(file=LOG)

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                               wintypes.DWORD, ctypes.c_size_t]
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


def click(x, y):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.02)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.03)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    log("click", x, y)


def pet_rect(pet):
    r = wintypes.RECT()
    user32.GetWindowRect(pet.root.winfo_id(), ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


pet = dp.DesktopPet(use_ai=False, topmost=True,
                    style=os.environ.get("PET_STYLE", "auto"))
log("start backend=%s layered=%s image=%s scale=%.2f"
    % (pet.backend.style, pet.layered, pet.image_name, pet.scale))

state = {"stalled": False}


def watchdog():
    """主线程 tick 超过 STALL_S 没动 -> 认为卡死，dump 后退出。"""
    while not state["stalled"]:
        time.sleep(0.25)
        if not pet._alive:
            return
        gap = time.monotonic() - pet._last_tick
        if gap > STALL_S:
            state["stalled"] = True
            log("!!!! STALLED gap=%.2fs" % gap)
            faulthandler.dump_traceback(file=LOG, all_threads=True)
            time.sleep(0.3)
            os._exit(3)


threading.Thread(target=watchdog, daemon=True, name="watchdog").start()

ACTIONS = ["speak", "jump", "spin", "dodge", "squash", "head"]
if pet.danmaku_allowed():
    ACTIONS.append("shoot")


def do_action():
    if not pet._alive:
        return
    kind = random.choice(ACTIONS)
    log("action", kind)
    t0 = time.monotonic()
    try:
        if kind == "speak":
            pet.speak_random()
        elif kind == "shoot":
            pet.do_gesture("shoot")
        else:
            pet.do_gesture(kind)
    except Exception:                          # noqa: BLE001
        log("action raised", kind)
        faulthandler.dump_traceback(file=LOG)
        raise
    log("action done", kind, "%.0fms" % ((time.monotonic() - t0) * 1000))


def clicker():
    """隔一会儿点一下宠物（点在身体上，不会点空），偶尔双击。"""
    while not state["stalled"]:
        time.sleep(random.uniform(0.55, 0.95))
        if not pet._alive:
            return
        try:
            left, top, right, bottom = pet_rect(pet)
            x = (left + right) // 2
            y = bottom - max(20, (bottom - top) // 8)
            click(x, y)
            if random.random() < 0.3:
                time.sleep(0.09)
                click(x, y)
        except Exception:                      # noqa: BLE001
            faulthandler.dump_traceback(file=LOG)
            return


threading.Thread(target=clicker, daemon=True, name="clicker").start()


def handles_probe():
    """每 2 秒记一次 GDI / USER 句柄数：泄漏到一万个就是真卡死。"""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    proc = kernel32.GetCurrentProcess()
    while not state["stalled"] and pet._alive:
        time.sleep(2.0)
        try:
            gdi = user32.GetGuiResources(proc, 0)
            usr = user32.GetGuiResources(proc, 1)
            log("handles gdi=%d user=%d lanes=%s" % (gdi, usr, sorted(pet._ai_lanes)))
        except Exception:                      # noqa: BLE001
            pass


threading.Thread(target=handles_probe, daemon=True, name="handles").start()


def loop():
    if not pet._alive or state["stalled"]:
        return
    if time.monotonic() - T0 > DURATION:
        log("finished ok")
        pet.root.after(200, pet.quit)
        return
    # 动作和点击交错：先放动作，紧接着点一下，最贴近用户描述的场景
    do_action()
    pet.root.after(random.randint(260, 520), loop)


pet.root.after(500, loop)
pet.run()
time.sleep(0.4)
log("exit clean; stalled=%s" % state["stalled"])
LOG.close()
sys.exit(0 if not state["stalled"] else 4)
