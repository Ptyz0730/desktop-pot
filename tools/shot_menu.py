# -*- coding: utf-8 -*-
"""把右键菜单弹出来截一张图。

Windows 上 tk_popup 会进入自己的模态循环（直到菜单被关掉才返回），
所以截图动作得用 after 排进那个循环里，截完 unpost 让它退出来。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import desktop_pet as dp                                    # noqa: E402
from PIL import ImageGrab                                   # noqa: E402


def settle(pet, seconds):
    end = time.time() + seconds
    while time.time() < end:
        pet.root.update()
        time.sleep(0.015)


def main():
    cfg = dp.CONFIG_PATH
    backup = cfg + ".menu.bak"
    if os.path.exists(cfg):
        os.replace(cfg, backup)
    pet = None
    try:
        pet = dp.DesktopPet(use_ai=False, bubble=False)
        settle(pet, 0.8)
        pet.root.update_idletasks()
        x = int(pet.win_x) + 40
        y = 60

        def snap():
            try:
                root = pet.root
                shot = ImageGrab.grab(all_screens=True)
                scale = shot.size[0] / max(1, root.winfo_screenwidth())
                w, h = 430, 620
                box = (int(x * scale) - 12, int(y * scale) - 12,
                       int((x + w) * scale), int((y + h) * scale))
                out = os.path.join(ROOT, "menu_preview.png")
                shot.crop(box).save(out)
                print("shot ->", out, shot.crop(box).size)
            except Exception as exc:                        # noqa: BLE001
                print("snap failed:", exc)
            finally:
                try:
                    pet.menu.unpost()
                except Exception:                           # noqa: BLE001
                    pass

        pet.root.after(600, snap)
        pet.menu.tk_popup(x, y)
        settle(pet, 0.3)
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
