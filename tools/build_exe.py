# -*- coding: utf-8 -*-
"""重新打包 + 部署 + 验收（只做目录版，不做单文件版）。

用法（在项目根目录）：
    <DSH python> tools\\build_exe.py

做两件事：
  1. 构建目录版到临时目录，然后**覆盖** dist\\桌面宠物（保留用户的 image\\ 和
     pet_config.json）。如果正跑着宠物、有文件被占用，就装到
     dist\\桌面宠物（最新版）\\ 并把快捷方式指过去 —— 不会去动正在运行的实例。
  2. 顺手验收：用"捧花少年 + 50%"启动一次，检查窗口尺寸、任务栏/托盘入口、
     从任务栏关闭 = 退出、日志是否干净，然后恢复用户配置。
"""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# DSH 运行时是原来的构建环境；换机器/运行时被清理后就用当前解释器兜底，
# 避免 build_exe.py 因为一个写死的路径直接跑不起来。
PY = os.path.join(os.environ["USERPROFILE"], ".dsh", "dsh-runtimes",
                  "dsh-primary-runtime", "dependencies", "python", "python.exe")
if not os.path.exists(PY):
    PY = sys.executable
ASSETS = os.path.join(ROOT, "assets")
DST = os.path.join(ROOT, "dist", "桌面宠物")
SIDE = os.path.join(ROOT, "dist", "桌面宠物（最新版）")
TMP = os.path.join(os.environ["TEMP"], "pet_dist_build")
IMAGES = ("中性灰.png", "浅色桌面.png", "深色桌面.png", "chm_love_me.png")


def run(args, **kw):
    # PyInstaller 是手动解到 pylibs\ 的（pip 在本机写盘会被拦），子进程必须
    # 带着这个 PYTHONPATH，不然 `-m PyInstaller` 直接 ModuleNotFoundError，
    # 然后就会拿上一次留在 TEMP 里的旧构建凑数 —— 打出来的 exe 还是旧版。
    env = os.environ.copy()
    pylibs = os.path.join(ROOT, "pylibs")
    if os.path.isdir(pylibs):
        env["PYTHONPATH"] = pylibs + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONIOENCODING"] = "utf-8"
    kw.setdefault("env", env)
    return subprocess.run(args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **kw)


def copy_tree(src, dst, skip=("image", "pet_config.json", "pet_error.log",
                            "pet_stderr.log")):
    """把 src 覆盖到 dst，返回被占用（拷不动）的文件名列表。

    pet_config.json 必须跳过：那是用户存档（形象/好感度/聊天记录），
    构建目录里那份只是构建时的样子，拷过去会把用户数据冲掉。
    """
    failed = []
    for name in os.listdir(src):
        if name in skip:
            continue
        s, d = os.path.join(src, name), os.path.join(dst, name)
        if os.path.isdir(s):
            for dirpath, _dirs, files in os.walk(s):
                rel = os.path.relpath(dirpath, s)
                td = os.path.join(d, rel) if rel != "." else d
                os.makedirs(td, exist_ok=True)
                for fn in files:
                    try:
                        shutil.copy2(os.path.join(dirpath, fn), os.path.join(td, fn))
                    except OSError:
                        failed.append(os.path.join(rel, fn))
        else:
            try:
                shutil.copy2(s, d)
            except OSError:
                failed.append(name)
    return failed


def sync_music(dst):
    """把项目 music/ 里的歌补到目标目录（不覆盖、不删目标里多出来的歌）。"""
    src = os.path.join(ROOT, "music")
    if not os.path.isdir(src):
        return 0
    out = os.path.join(dst, "music")
    os.makedirs(out, exist_ok=True)
    copied = 0
    for name in os.listdir(src):
        s_path = os.path.join(src, name)
        d_path = os.path.join(out, name)
        if os.path.isfile(s_path) and not os.path.exists(d_path):
            try:
                shutil.copy2(s_path, d_path)
                copied += 1
            except OSError:
                pass
    return copied


def main():
    print("=== 构建目录版 ===")
    # 旧构建目录必须先清掉：构建失败时它还在，后面的代码会把旧版本当成功
    shutil.rmtree(TMP, ignore_errors=True)
    r = run([PY, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
             "--distpath", TMP, "--workpath",
             os.path.join(os.environ["TEMP"], "pet_build_build"),
             "desktop_pet.spec"], cwd=ROOT)
    built = os.path.join(TMP, "桌面宠物")
    if r.returncode != 0:
        print("   构建失败 rc=%s" % r.returncode)
        print("   " + (r.stderr or r.stdout or "")[-800:])
        return 1
    if not os.path.isdir(built):
        print("   构建失败:", (r.stderr or r.stdout or "")[-400:])
        return 1
    print("   rc=%s 文件数=%d" % (r.returncode,
                                sum(len(f) for _x, _y, f in os.walk(built))))

    print("=== 覆盖 dist\\桌面宠物 ===")
    failed = copy_tree(built, DST)
    target = DST
    if failed:
        print("   有 %d 个文件被占用（宠物正在运行），改装到侧边目录" % len(failed))
        shutil.rmtree(SIDE, ignore_errors=True)
        shutil.copytree(built, SIDE)
        os.makedirs(os.path.join(SIDE, "image"), exist_ok=True)
        for n in IMAGES:
            s = os.path.join(ROOT, "image", n)
            if os.path.exists(s):
                shutil.copy2(s, os.path.join(SIDE, "image", n))
        for n in ("pet_config.json", "pet_error.log", "pet_stderr.log"):
            p = os.path.join(SIDE, n)
            if os.path.exists(p):
                os.remove(p)
        target = SIDE
    else:
        shutil.rmtree(SIDE, ignore_errors=True)
        print("   完成（保留了 image\\ 和配置）")
    n = sync_music(target)
    print("   music/ 补了 %d 首" % n)


    print("=== 快捷方式 -> %s ===" % target)
    exe = os.path.join(target, "桌面宠物.exe")
    lnk = os.path.join(ROOT, "桌面宠物（exe）.lnk")
    run(["powershell", "-NoProfile", "-Command",
         "$w=New-Object -ComObject WScript.Shell;$l=$w.CreateShortcut('%s');"
         "$l.TargetPath='%s';$l.WorkingDirectory='%s';$l.IconLocation='%s';"
         "$l.Description='start desktop pet';$l.Save()" % (lnk, exe, target, exe)])

    print("=== 验收（在临时副本里跑，绝不碰你的配置）===")
    import tempfile
    verify_dir = os.path.join(tempfile.gettempdir(), "pet_verify_copy")
    shutil.rmtree(verify_dir, ignore_errors=True)
    shutil.copytree(target, verify_dir)
    os.makedirs(os.path.join(verify_dir, "image"), exist_ok=True)
    for n in IMAGES:
        s = os.path.join(ROOT, "image", n)
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(verify_dir, "image", n))
    cfg = os.path.join(verify_dir, "pet_config.json")
    json.dump({"image": "chm_love_me.png", "scale": 0.5, "bubble": False, "ai": False},
              open(cfg, "w", encoding="utf-8"), ensure_ascii=False)
    # 清掉拷过来的旧日志，否则会把上次的报错当成这次的结果
    for n in ("pet_error.log", "pet_stderr.log"):
        p = os.path.join(verify_dir, n)
        if os.path.exists(p):
            os.remove(p)
    exe = os.path.join(verify_dir, "桌面宠物.exe")

    u = ctypes.windll.user32

    class RECT(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                    ("r", ctypes.c_long), ("b", ctypes.c_long)]

    EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                           ctypes.POINTER(wintypes.DWORD)]
    u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    p = subprocess.Popen([exe, "--topmost"], cwd=verify_dir,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(5)
    seen = []

    def cb(hwnd, _):
        wpid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == p.pid:
            r = RECT()
            u.GetWindowRect(hwnd, ctypes.byref(r))
            buf = ctypes.create_unicode_buffer(64)
            u.GetClassNameW(hwnd, buf, 64)
            ex = u.GetWindowLongW(hwnd, -20)
            if buf.value == "TkTopLevel":
                seen.append({"size": (r.r - r.l, r.b - r.t), "ex": hex(ex),
                             "tool": bool(ex & 0x80)})
            # 只关自己的窗口！以前这里没包在 pid 判断里，会把系统里所有
            # 尺寸合适的窗口都发一遍 WM_CLOSE（浏览器都可能被关掉）。
            if 60 < r.r - r.l < 900 and 60 < r.b - r.t < 900:
                u.PostMessageW(hwnd, 0x0010, 0, 0)      # WM_CLOSE
        return True

    u.EnumWindows(EnumProc(cb), 0)
    time.sleep(3)
    for item in seen:
        print("   ", item)
    print("   发 WM_CLOSE 后进程还在吗:", p.poll() is None, "（False = 能直接关掉）")
    for n in ("pet_error.log", "pet_stderr.log"):
        fp = os.path.join(verify_dir, n)
        size = os.path.getsize(fp) if os.path.exists(fp) else -1
        print("   %s: %s" % (n, size))
        if size and size > 0:
            raw = open(fp, "rb").read()
            text = raw.decode("utf-8", "replace")
            print("   >>", "".join(ch if 32 <= ord(ch) < 127 else "."
                                   for ch in text)[:300])
    if p.poll() is None:
        p.terminate()
    time.sleep(1)
    shutil.rmtree(verify_dir, ignore_errors=True)

    # 如果装在 C:\桌面宠物 这种"非桌面"目录（托盘才不被管控软件拦），顺手更新它。
    # 运行中绝不能覆盖：文件被占用会拷一半，装出一份混合的坏安装。
    live = "C:\\桌面宠物"
    if os.path.isdir(live):
        busy = run(["tasklist", "/FI", "IMAGENAME eq 桌面宠物.exe",
                    "/FO", "CSV"]).stdout
        if busy.count("桌面宠物.exe") > 1:
            print("=== 跳过同步到 %s：宠物正在运行（先右键托盘退出再重跑）===" % live)
        else:
            print("=== 同步到已安装目录 %s（保留 image/ 和配置）===" % live)
            failed = copy_tree(target, live)
            print("   被占用 %d 个" % len(failed))
            for n in IMAGES:
                s = os.path.join(ROOT, "image", n)
                if os.path.exists(s):
                    shutil.copy2(s, os.path.join(live, "image", n))
            print("   music/ 补了 %d 首" % sync_music(live))
    print("DONE target=%s" % target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
