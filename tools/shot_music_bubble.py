# -*- coding: utf-8 -*-
"""截一张"放歌时的常驻气泡"（歌名 + 三个按钮）。"""
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import desktop_pet as dp  # noqa: E402
import pet_music  # noqa: E402
from PIL import ImageGrab  # noqa: E402

CFG = dp.CONFIG_PATH
BAK = CFG + ".musicbubble"
if os.path.exists(CFG):
    shutil.copy2(CFG, BAK)

pet = None
try:
    if os.path.exists(CFG):
        os.remove(CFG)
    pet = dp.DesktopPet(use_ai=False, topmost=True, bubble=True)
    for _ in range(50):
        pet.root.update()
        time.sleep(0.05)
    pet.move(110, 110)
    for _ in range(20):
        pet.root.update()
        time.sleep(0.05)
    songs = pet_music.scan_music(dp.MUSIC_DIR)
    pet.play_music(songs[1][1] if len(songs) > 1 else songs[0][1])
    for _ in range(20):
        pet.root.update()
        time.sleep(0.05)
    win = pet.bubble.win
    win.update_idletasks()
    im = ImageGrab.grab(all_screens=True)
    sc = im.size[0] / float(pet.root.winfo_screenwidth())
    bx, by = win.winfo_rootx(), win.winfo_rooty()
    bw, bh = win.winfo_width(), win.winfo_height()
    box = (max(0, int((bx - 20) * sc)), max(0, int((by - 20) * sc)),
           int((bx + bw + 20) * sc), int((by + bh + 20) * sc))
    im.crop(box).save(os.path.join(ROOT, "music_bubble_preview.png"))
    print("saved", box, "buttons", len(pet.bubble._buttons),
          "persistent", pet.bubble.persistent())
    pet.stop_music()
finally:
    try:
        if pet is not None:
            pet.quit()
    except Exception:                       # noqa: BLE001
        pass
    if os.path.exists(CFG):
        os.remove(CFG)
    if os.path.exists(BAK):
        shutil.move(BAK, CFG)
