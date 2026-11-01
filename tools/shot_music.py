# -*- coding: utf-8 -*-
"""截一张"点歌后头顶气泡报歌名"的图：music_preview.png。"""
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import desktop_pet as dp  # noqa: E402
from PIL import ImageGrab  # noqa: E402

CFG = dp.CONFIG_PATH
BAK = CFG + ".shot_bak"
if os.path.exists(CFG):
    shutil.copy2(CFG, BAK)

pet = None
try:
    if os.path.exists(CFG):
        os.remove(CFG)
    pet = dp.DesktopPet(use_ai=False, topmost=True, bubble=True)
    songs = pet.music_files
    print("songs:", [t for t, _p in songs])
    for _ in range(40):
        pet.root.update()
        time.sleep(0.05)
    pet.play_music(songs[0][1])
    for _ in range(30):
        pet.root.update()
        time.sleep(0.05)
    win = pet.bubble.win
    win.update_idletasks()
    shot = ImageGrab.grab(all_screens=True)
    sc = shot.size[0] / float(pet.root.winfo_screenwidth())
    bx, by = win.winfo_rootx(), win.winfo_rooty()
    bw, bh = win.winfo_width(), win.winfo_height()
    print("bubble rect", bx, by, bw, bh, "scale", sc)
    box = (max(0, int((bx - 24) * sc)), max(0, int((by - 24) * sc)),
           int((bx + bw + 24) * sc), int((by + bh + 24) * sc))
    shot.crop(box).save(os.path.join(ROOT, "music_preview.png"))
    print("saved", box)
    pet.music.close()
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
