# -*- coding: utf-8 -*-
"""Controlled live probe: place the pet at a known spot, settle, then screenshot.

Runs the real app in-process so the window state is exactly what the user gets.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from PIL import Image, ImageGrab  # noqa: E402
import desktop_pet as dp  # noqa: E402


def settle(pet, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pet.root.update()
        time.sleep(0.02)


def main():
    style = sys.argv[1] if len(sys.argv) > 1 else "colorkey"
    image = sys.argv[2] if len(sys.argv) > 2 else None
    pet = dp.DesktopPet(image=image, bubble=False, style=style, use_ai=False,
                        topmost=True)
    print("backend:", pet.backend.style, "image:", pet.image_name)
    pet.move(700, 300)
    settle(pet, 1.2)

    shot = os.path.join(ROOT, "assets", "probe_%s.png" % pet.backend.style)
    img = ImageGrab.grab()
    img.save(shot)
    print("full screen ->", shot, img.size)

    # 裁宠物窗口那一块（别写死坐标，换分辨率/换大小就不准了）
    box = (max(0, pet.win_x - 20), max(0, pet.win_y - 20),
           min(img.size[0], pet.win_x + pet.win_w + 20),
           min(img.size[1], pet.win_y + pet.win_h + 20))
    crop = img.crop(box)
    crop_path = os.path.join(ROOT, "assets", "probe_%s_crop.png" % pet.backend.style)
    crop.save(crop_path)

    # how much of the crop differs from the most common colour?
    small = crop.convert("RGB")
    colors = small.getcolors(small.size[0] * small.size[1])
    colors.sort(reverse=True)
    top = colors[0]
    print("dominant colour %s covers %.1f%% of crop" %
          (top[1], 100.0 * top[0] / (small.size[0] * small.size[1])))

    pet.quit()
    print("crop ->", crop_path)


if __name__ == "__main__":
    main()
