"""自检：桌宠是不是真的贴在窗口最底层。

跑法：
    python tools/check_bottom.py [--shot]

验证：
  1. 启动后宠物不会浮在别的窗口上面（check_covered 和"手动沿 Z 序往上找"
     的结论一致）；
  2. 在宠物位置上开一个普通窗口，必须能把它盖住（visible -> False、
     气泡收起）；
  3. 那个窗口关掉后，宠物的可见性和 Z 序重新对上。
"""
import ctypes
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import desktop_pet as dp                                    # noqa: E402
from PIL import ImageGrab                                   # noqa: E402

SHOT = "--shot" in sys.argv


def settle(pet, seconds):
    end = time.time() + seconds
    while time.time() < end:
        try:
            pet.root.update()
        except Exception:                                   # noqa: BLE001
            return
        time.sleep(0.015)


def win_rect(hwnd):
    rect = ctypes.wintypes.RECT()
    dp._user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def walrus_covered(pet):
    """测试自己的参照实现：无上限地沿 Z 序往上找包住宠物的窗口。"""
    hwnd = dp._hwnd_of(pet.root)
    x0, y0, x1, y1 = win_rect(hwnd)
    skip = set(pet._fx_hwnds())
    h = dp._user32.GetWindow(hwnd, 3)
    guard = 0
    while h and guard < 2000:
        guard += 1
        if h not in skip and dp._user32.IsWindowVisible(h) \
                and not dp._user32.IsIconic(h):
            a, b, c, d = win_rect(h)
            if a <= x0 and b <= y0 and c >= x1 and d >= y1:
                return True
        h = dp._user32.GetWindow(h, 3)
    return False


def grab_area(pet, box, path):
    pet.root.update()
    time.sleep(0.2)
    left, top, right, bottom = box
    shot = ImageGrab.grab(all_screens=True)
    scale = shot.size[0] / max(1, pet.root.winfo_screenwidth())
    pad = 40
    crop = (max(0, int((left - pad) * scale)), max(0, int((top - pad) * scale)),
            int((right + pad) * scale), int((bottom + pad) * scale))
    shot.crop(crop).save(path)
    print("shot ->", path, shot.crop(crop).size)


def main():
    backup = os.path.join(ROOT, "pet_config.check_backup.json")
    cfg = dp.CONFIG_PATH
    if os.path.exists(cfg):
        os.replace(cfg, backup)
    pet = None
    try:
        pet = dp.DesktopPet(use_ai=False, bubble=True)
        settle(pet, 1.2)
        print("pet rect", win_rect(dp._hwnd_of(pet.root)))
        expect = walrus_covered(pet)
        print("z-order says covered=%s ; pet.visible=%s" % (expect, pet.visible))
        assert pet.check_covered() == expect, "check_covered disagrees with z-order"
        assert pet.visible == (not expect), "visible flag out of sync"
        assert pet.topmost is False, "pet must never be topmost"

        # 自己在宠物上方开一个普通窗口，必须能把它盖住
        x, y, w, h = pet.win_x, pet.win_y, pet.win_w, pet.win_h
        cover = dp.tk.Toplevel(pet.root)
        cover.title("cover test")
        cover.geometry("%dx%d+%d+%d" % (max(320, w + 80), max(240, h + 80),
                                        max(0, x - 40), max(0, y - 40)))
        cover.configure(bg="#ff8fa3")
        cover.update()
        cover.lift()
        settle(pet, 1.8)
        print("with cover window: covered=%s visible=%s"
              % (pet.check_covered(), pet.visible))
        assert pet.check_covered(), "a normal window on top should cover the pet"
        assert pet.visible is False, "pet should mark itself covered"
        assert pet.bubble is not None and not pet.bubble.visible()
        if SHOT:
            grab_area(pet, (max(0, x - 40), max(0, y - 40), x + w + 40, y + h + 40),
                      os.path.join(ROOT, "pet_covered_preview.png"))

        cover.destroy()
        settle(pet, 1.8)
        expect = walrus_covered(pet)
        print("after cover close: z-order covered=%s visible=%s"
              % (expect, pet.visible))
        assert pet.check_covered() == expect
        assert pet.visible == (not expect)
        if SHOT and not expect:
            grab_area(pet, win_rect(dp._hwnd_of(pet.root)),
                      os.path.join(ROOT, "pet_bottom_preview.png"))
        assert pet._fs_paused is False
        print("bottom layer ok")
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
