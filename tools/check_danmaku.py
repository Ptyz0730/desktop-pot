# -*- coding: utf-8 -*-
"""摸头弹幕自检：文字跟着头顶走、贴屏幕边也不偏、消失后窗口收起来。

分两段：
  [几何] 用假 pet 直接驱动 DanmakuFX（不受"窗口被盖住就不冒"的干扰）；
  [集成] 真 DesktopPet，把 visible 钉成 True、petting_until 设到未来，
        看它到底冒不冒、以及连续摸头最多几条。

跑法：python tools\\check_danmaku.py
"""
import os
import sys
import time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import desktop_pet as dp

OK = []


def check(name, cond, detail=""):
    OK.append(bool(cond))
    print(("ok   - " if cond else "FAIL - ") + name +
          ("" if cond else "   | " + str(detail)))


def settle(pet, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pet.root.update()
        time.sleep(0.01)


class FakePet(object):
    """DanmakuFX 只用到这几样：root / scale / win_w / win_h / 台词。"""

    def __init__(self, root):
        self.root = root
        self.scale = 0.5
        self.win_w = 196
        self.win_h = 362

    def danmaku_phrases(self):
        return dp.DANMAKU_PHRASES


def pump(fx, anchor, frames=20, dt=0.05, active=True):
    now = time.time()
    for _ in range(frames):
        fx.update(dt, anchor, active, now)
        now += dt
        fx.pet.root.update()
        time.sleep(0.008)


def item_center(fx):
    if not fx.items or fx.rect is None:
        return None
    item = fx.items[0]
    return (fx.rect[0] + item.x + item.img.width / 2.0,
            fx.rect[1] + item.y + item.img.height)


def geometry_tests(root):
    print("\n[几何]")
    fx = dp.DanmakuFX(FakePet(root))
    fx.max_items = fx.MAX_ITEMS
    anchor = (640, 500)
    pump(fx, anchor, frames=6)
    check("摸头会冒弹幕", fx.active(), len(fx.items))
    center = item_center(fx)
    check("弹幕出现在头顶正上方", center is not None and
          abs(center[0] - anchor[0]) < 45 and abs(center[1] - anchor[1]) < 60,
          (anchor, center))

    before = tuple(fx.rect)
    moved = (anchor[0] + 180, anchor[1] - 60)
    pump(fx, moved, frames=2)
    after = tuple(fx.rect)
    check("宠物移动后窗口跟着挪", before[0] != after[0] or before[1] != after[1],
          (before, after))
    center2 = item_center(fx)
    check("移动后仍在头顶上方", center2 is not None and
          abs(center2[0] - moved[0]) < 60 and abs(center2[1] - moved[1]) < 70,
          (moved, center2))

    # 贴屏幕左边：矩形会被 work_area 夹住，文字不能跟着跑偏
    fx.clear()
    edge = (12, anchor[1])
    pump(fx, edge, frames=6)
    center3 = item_center(fx)
    check("贴屏幕左边也不偏", center3 is not None and abs(center3[0] - edge[0]) < 60,
          (edge, center3, fx.rect))

    # 同时最多两条
    fx.clear()
    pump(fx, anchor, frames=90, dt=0.2)
    check("同时最多两条", len(fx.items) <= fx.MAX_ITEMS, len(fx.items))

    # 不再摸之后，字飘完窗口收起来
    fx.clear()
    pump(fx, anchor, frames=4)
    check("停止摸头前还有字", fx.active())
    pump(fx, anchor, frames=80, active=False, dt=0.1)
    check("字飘完后收起来了", not fx.active() and not fx.shown,
          (fx.active(), fx.shown))

    # 窗口被屏幕边缘夹住时：垂直不出屏，水平允许探出去一部分（字才对得准头顶）
    fx.clear()
    pump(fx, (2, 2), frames=4)
    left, top, right, bottom = dp.work_area(root)
    x0, y0, w, h = fx.rect
    on_screen = min(right, x0 + w) - max(left, x0)
    check("至少有一截留在屏幕里", on_screen >= 60, (fx.rect, on_screen))
    check("垂直不越界", y0 >= top - 1 and y0 + h <= bottom + 1, fx.rect)
    fx.destroy()


def integration_tests():
    print("\n[集成]")
    cfg = dp.CONFIG_PATH
    bak = cfg + ".danmaku_bak"
    had = os.path.isfile(cfg)
    if had:
        import shutil
        shutil.copy2(cfg, bak)
    try:
        if had:
            os.remove(cfg)
        pet = dp.DesktopPet(use_ai=False, topmost=True, bubble=False, style="colorkey")
        pet.set_image("郑迪隆.png")
        pet.set_persona("骚话少年")
        settle(pet, 0.5)
        check("这个形象允许弹幕", pet.danmaku_allowed())

        # visible 是每帧根据"有没有被盖住"算的；自检时钉住，petting 拉长
        pet.visible = True
        pet.check_covered = lambda: False
        pet.petting_until = time.time() + 5.0
        now = time.time()
        for _ in range(30):
            pet.visible = True
            pet.danmaku.update(0.05, pet.head_anchor(), True, now)
            now += 0.05
            pet.root.update()
            time.sleep(0.01)
        check("真桌宠摸头也冒弹幕", pet.danmaku.active(), len(pet.danmaku.items))

        # 宠物挪位置后弹幕继续跟着
        pet.danmaku.clear()
        first = None
        for i in range(24):
            pet.visible = True
            if i == 8:
                pet.win_x = max(10, pet.win_x - 120)
            pet.danmaku.update(0.05, pet.head_anchor(), True, now)
            now += 0.05
            pet.root.update()
            time.sleep(0.01)
            if i == 6:
                first = tuple(pet.danmaku.rect or ())
        check("挪位置后弹幕窗口也换地方", first and
              tuple(pet.danmaku.rect or ()) != first, (first, pet.danmaku.rect))

        pet.set_image("中性灰.png")
        pet.set_persona("话痨朋友")
        settle(pet, 0.4)
        check("普通形象没有弹幕", not pet.danmaku_allowed())
        pet.quit()
    finally:
        if had:
            import shutil
            shutil.move(bak, cfg)
        elif os.path.isfile(cfg):
            os.remove(cfg)


def main():
    root = tk.Tk()
    root.withdraw()
    try:
        geometry_tests(root)
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass
    integration_tests()
    print("\nRESULT:", "OK" if all(OK) else "FAILED (%d/%d)" % (OK.count(False), len(OK)))
    return 0 if all(OK) else 1


if __name__ == "__main__":
    sys.exit(main())
