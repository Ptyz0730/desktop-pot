# -*- coding: utf-8 -*-
"""把打包好的目录版安装到桌面以外的地方（管控软件不允许从桌面调用托盘 API），
迁移用户配置，建/改快捷方式，并从新位置验收托盘图标。"""
import ctypes
import json
import os
import shutil
import subprocess
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "dist", "桌面宠物")
INSTALL = "C:\\桌面宠物"
PROJ_LNK = os.path.join(ROOT, "桌面宠物（exe）.lnk")
DESK_LNK = os.path.join(os.environ["USERPROFILE"], "Desktop", "桌面宠物.lnk")
IMAGES = ("中性灰.png", "浅色桌面.png", "深色桌面.png", "chm_love_me.png")


def run(args, **kw):
    return subprocess.run(args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **kw)


def make_lnk(path, target, workdir):
    return run(["powershell", "-NoProfile", "-Command",
                "$w=New-Object -ComObject WScript.Shell;$l=$w.CreateShortcut('%s');"
                "$l.TargetPath='%s';$l.WorkingDirectory='%s';$l.IconLocation='%s';"
                "$l.Description='桌面宠物';$l.Save()" % (path, target, workdir, target)])


print("=== 1) 安装到 %s ===" % INSTALL)
if os.path.isdir(INSTALL):
    # 只更新程序文件，保留用户的 image/ 和配置
    for name in os.listdir(SRC):
        s = os.path.join(SRC, name)
        d = os.path.join(INSTALL, name)
        if name == "image":
            continue
        if os.path.isdir(s):
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
            shutil.copytree(s, d)
        else:
            try:
                shutil.copy2(s, d)
            except OSError as exc:
                print("   跳过 %s: %s" % (name, exc))
    print("   已更新（保留 image/ 和配置）")
else:
    shutil.copytree(SRC, INSTALL)
    print("   已全新安装")
os.makedirs(os.path.join(INSTALL, "image"), exist_ok=True)
for n in IMAGES:
    s = os.path.join(ROOT, "image", n)
    if os.path.exists(s):
        shutil.copy2(s, os.path.join(INSTALL, "image", n))
# 迁移用户配置（人设/好感度/大小等）
proj_cfg = os.path.join(SRC, "pet_config.json")
inst_cfg = os.path.join(INSTALL, "pet_config.json")
if os.path.exists(proj_cfg) and not os.path.exists(inst_cfg):
    shutil.copy2(proj_cfg, inst_cfg)
    print("   已迁移配置:", json.load(open(inst_cfg, encoding="utf-8-sig")))
for n in ("pet_error.log", "pet_stderr.log"):
    p = os.path.join(INSTALL, n)
    if os.path.exists(p):
        os.remove(p)

exe = os.path.join(INSTALL, "桌面宠物.exe")
print("=== 2) 快捷方式（项目里 + 桌面上）===")
print("   ", make_lnk(PROJ_LNK, exe, INSTALL).returncode,
      make_lnk(DESK_LNK, exe, INSTALL).returncode)

print("=== 3) 从新位置启动，验收托盘 ===")
u = ctypes.windll.user32


class RECT(ctypes.Structure):
    _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                ("r", ctypes.c_long), ("b", ctypes.c_long)]


EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
p = subprocess.Popen([exe, "--topmost"], cwd=INSTALL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(6)
found = []


def cb(hwnd, _):
    wpid = wintypes.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
    if wpid.value == p.pid:
        r = RECT()
        u.GetWindowRect(hwnd, ctypes.byref(r))
        if 60 < r.r - r.l < 900 and 60 < r.b - r.t < 900:
            ex = u.GetWindowLongW(hwnd, -20)
            found.append(((r.r - r.l, r.b - r.t), hex(ex), bool(ex & 0x80)))
    return True


u.EnumWindows(EnumProc(cb), 0)
print("   窗口:", found, "（应该只有宠物本体一个：工具窗口=True；"
      "如果多出一个 17x40 的就是退回方案，说明托盘仍被拒）")
log = os.path.join(INSTALL, "pet_stderr.log")
if os.path.exists(log):
    text = open(log, "rb").read().decode("utf-8", "replace").strip()
    print("   pet_stderr.log:", "".join(ch if 32 <= ord(ch) < 127 else "."
                                       for ch in text)[:200] or "(空)")
else:
    print("   pet_stderr.log: 没生成（托盘没有报错 = 成功）")
p.terminate()
time.sleep(1)
for n in ("pet_error.log", "pet_stderr.log"):
    fp = os.path.join(INSTALL, n)
    if os.path.exists(fp):
        os.remove(fp)
print("DONE install=%s" % INSTALL)
