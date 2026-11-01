# -*- coding: utf-8 -*-
"""Print where the frozen app thinks its files live (run through the debug exe)."""
import os
import sys

FROZEN = bool(getattr(sys, "frozen", False))
ROOT = os.path.dirname(os.path.abspath(sys.executable if FROZEN else __file__))
print("frozen      :", FROZEN)
print("sys.executable:", sys.executable)
print("sys._MEIPASS:", getattr(sys, "_MEIPASS", None))
print("__file__    :", __file__)
print("ROOT        :", ROOT)
print("local cfg   :", os.path.join(ROOT, "pet_config.json"))
print("exists      :", os.path.exists(os.path.join(ROOT, "pet_config.json")))
base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
target = os.path.join(base, "DesktopPet")
print("LOCALAPPDATA:", base)
print("target dir  :", target)
try:
    os.makedirs(target, exist_ok=True)
    probe = os.path.join(target, "probe.txt")
    with open(probe, "w", encoding="utf-8") as fh:
        fh.write("ok")
    print("write test  : OK")
    os.remove(probe)
except OSError as exc:
    print("write test  : FAILED", exc)
