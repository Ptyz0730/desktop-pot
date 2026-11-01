# -*- coding: utf-8 -*-
"""Build a console-mode copy of the app so frozen-mode errors are visible."""
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
src = io.open(os.path.join(ROOT, "desktop_pet.spec"), encoding="utf-8").read()

dbg = (src.replace("console=False", "console=True")
          .replace("name='桌面宠物'", "name='petdbg'"))
out = os.path.join(ROOT, "build_debug.spec")
io.open(out, "w", encoding="utf-8").write(dbg)
print("wrote", out)
print("console lines:", [l.strip() for l in dbg.split("\n") if "console" in l])
print("name lines:", [l.strip() for l in dbg.split("\n") if "name=" in l])
