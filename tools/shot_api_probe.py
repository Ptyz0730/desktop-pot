# -*- coding: utf-8 -*-
"""证明打包后的 exe 用的是新 API key：--ask 让它真的说一句 AI 回复，截图。

用法：<DSH python> tools/shot_api_probe.py
输出：api_probe.png（整屏裁剪，宠物附近）
"""
import io
import os
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = r"C:\桌面宠物\桌面宠物.exe"


def main():
    t0 = time.time()
    proc = subprocess.Popen([EXE, "--ask", "在吗"],
                            cwd=os.path.dirname(EXE))
    try:
        time.sleep(12)
        from PIL import ImageGrab
        shot = ImageGrab.grab(all_screens=True)
        sw, sh = shot.size
        box = (int(sw * 0.55), int(sh * 0.35), sw, sh)
        crop = shot.crop(box)
        out = os.path.join(ROOT, "api_probe.png")
        crop.save(out)
        print("saved", out, crop.size)
    finally:
        if proc.poll() is None:
            proc.kill()
        print("elapsed %.1fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
