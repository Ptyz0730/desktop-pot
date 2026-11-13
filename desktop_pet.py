#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面宠物 (Desktop Pet) — Tkinter + Pillow + Win32 + DeepSeek

把一张人物抠图变成会站在桌面上的小伙伴：

  * 无边框、置顶、可拖动
  * 待机时缓慢呼吸，偶尔换重心；双击会跳一下
  * 手势：下划压扁 / 上划跳 / 头顶左右蹭摸头 / 身体横划躲 / 绕圈转晕
  * 右键「逗它玩」可以手动触发手势；chm 还能打飞机（拉长变窄、头顶发射子弹）
  * 单击 / 双击 / 定时 -> 气泡说话
  * 接 DeepSeek：待机的话由 AI 生成，右键「对话…」可以真的聊天
  * 拖到屏幕底部就"站"在任务栏上方，贴边时气泡会自动换边
  * 右键菜单：形象 / 大小 / 对话… / AI 设置 / 说点什么 / 显示气泡 /
           点击穿透 / 浮在所有窗口上面 / 回到右下角 / 打开图片文件夹 / 退出

渲染有两种后端，启动时自动选：

  colorkey 默认。Tk 的 -transparentcolor 一位透明 + 纯色抠底，
           在所有 Windows 会话里都验证过
  layered  Win32 UpdateLayeredWindow 逐像素 alpha，边缘更好，但某些被管控的
           机器上 DWM 不合成这一层，所以只作为选项

重新生成素材：tools/build_assets.py；重新打包：pyinstaller desktop_pet.spec

用法:
    python desktop_pet.py [--image 中性灰.png] [--style colorkey|layered]
                          [--scale 0.5] [--no-bubble] [--no-ai]
                          [--api-key sk-...] [--selftest 毫秒] [--where]
"""

import argparse
import gc
import json
import math
import os
import collections
import contextlib
import queue
import random
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageTk
except ImportError:  # pragma: no cover
    sys.exit("需要 Pillow: <python> -m pip install pillow")

import ai_client
import jp_gloss
import kaomoji
import pet_games
import pet_mood
import pet_music
import pet_persona
import pet_radio

APP_NAME = "桌面宠物"

FROZEN = bool(getattr(sys, "frozen", False))
# 冻结后 __file__ 指向 _internal 里面，不是 exe 所在目录，得用 sys.executable
ROOT = os.path.dirname(os.path.abspath(sys.executable if FROZEN else __file__))
ASSETS = os.path.join(ROOT, "assets")


CONFIG_NAME = "pet_config.json"

# 内置的 DeepSeek key：开箱即用。多个 key 会轮换使用，分担并发/额度压力。
# 想换成自己的，改 pet_config.json 里的 "api_key"（可以写多个，逗号分隔），
# 或者设环境变量 DESKTOP_PET_API_KEY，或者用 --api-key 传。
BUILTIN_API_KEYS = (
    "sk-0eababa2743b46a8b23e909a73d4fafc",
    "sk-9b84129e3a604acc9118f300843b52ca",
)
BUILTIN_API_KEY = BUILTIN_API_KEYS[0]     # 兼容旧代码/旧配置
DEFAULT_MODEL = "deepseek-chat"

PENDING_TEXT = "……"      # 等 AI 回复时气泡上的占位
PENDING_MS = 15000       # 占位气泡多留一会儿，别在回复回来前就消失
AI_REPLY_MS = 11000      # AI 回复比内置话术多显示一会儿（长一点，要读）

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")
TARGET_H = 232           # 检测用的缩略高度（内置素材 50% 时的高度）
_BUILTIN_SPRITE_H = None # 内置立绘实际高度，见 builtin_sprite_height()
MAX_SIDE = 2048          # 单边上限，防止有人丢一张超大的图进来
VISIBLE_POLL_MS = 600    # 被窗口盖住时多久检查一次是否重新可见
GC_EVERY_S = 5.0         # 多久在主线程里手动回收一次垃圾（见 _tick_body）
SPAWN_MARGIN = 48        # 第一次运行时，宠物离屏幕右边留多少像素（右下角）
OPACITY_MIN = 0.20       # 不透明度下限
OPACITY_STEP = 0.10      # 菜单里的档位间隔
OPACITY_WHEEL_STEP = 0.05   # Ctrl+滚轮 每格
OPACITY_STEPS = tuple(round(1.0 - i * OPACITY_STEP, 2)
                      for i in range(int((1.0 - OPACITY_MIN) / OPACITY_STEP) + 1))
AFFECTION_START = 10     # 好感度初始值（0-100），清空记忆时回到这里
AFFECTION_HINT_STEP = 60 # 跨过这个值时说一句"它好像更喜欢你了"

# 每个形象一套 AI 人设：文件名 -> 人设名（提示词在 ai_client.PERSONA_PROMPTS）
# 想给别的图指定人设：右键 -> AI 设置 -> 人设，或者直接改 pet_config.json 里的
# "personas": { "你的图.png": "闷骚少年" }
IMAGE_PERSONAS = {
    "捧花少年.png": "闷骚少年",
    "chm_love_me.png": "闷骚少年",     # 用户自己放的陈瀚铭立绘
    "郑迪隆.png": "骚话少年",           # 郑迪隆立绘（tools/make_photo_sprite.py 抠的）
    "中性灰.png": "话痨朋友",
    "浅色桌面.png": "话痨朋友",
    "深色桌面.png": "话痨朋友",
}
DEFAULT_PERSONA = "话痨朋友"


def persona_key_for(image_name, cfg=None):
    """这个形象用哪套人设：配置里能改，其次看内置表，最后用默认。"""
    custom = (cfg or {}).get("personas")
    if isinstance(custom, dict) and isinstance(custom.get(image_name), str):
        name = custom[image_name].strip()
        if name:
            return name
    return IMAGE_PERSONAS.get(image_name, DEFAULT_PERSONA)

# 内置素材：已经压平到对应抠底色上，直接按固定 key 加载（不用猜）
BUILTIN_IMAGES = [
    ("中性灰.png", "pet_gray_flat.png", "#787e88", "中性灰抠底（深浅桌面通用）"),
    ("浅色桌面.png", "pet_white_flat.png", "#ffffff", "浅色桌面（白底抠图）"),
    ("深色桌面.png", "pet_black_flat.png", "#000000", "深色桌面（黑底抠图）"),
]
BUILTIN_RGBA = {
    "中性灰.png": "pet_gray_rgba.png",
    "浅色桌面.png": "pet_white_rgba.png",
    "深色桌面.png": "pet_black_rgba.png",
}


def _writable(path):
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write_test")
        with open(probe, "w") as fh:
            fh.write("1")
        os.remove(probe)
        return True
    except OSError:
        return False


def _log_exception(exc_info=None):
    """把异常堆栈写进程序目录下的 pet_error.log（并限制日志大小）。

    GUI 里漏出来的异常默认只进 stderr，而打包后的 exe / pythonw 没有控制台，
    所以必须自己落盘。日志封顶 256KB：万一某帧开始每帧都炸，也不会把磁盘写满。
    """
    import traceback
    try:
        text = "".join(traceback.format_exception(*(exc_info or sys.exc_info())))
        path = os.path.join(ROOT, "pet_error.log")
        if os.path.exists(path) and os.path.getsize(path) > 256 * 1024:
            os.remove(path)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("----- %s\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
            fh.write(text if text.endswith("\n") else text + "\n")
    except Exception:
        pass


def defer_photo_free(obj):
    """把要丢掉的 Tk 图片对象攒起来，等主线程下一次 tick 再释放。

    Tkinter 图片在工作线程里被回收时，会去调 Tcl 删 Tk 图片，而那时主线程
    不在 Tcl 里 —— 轻则 "main thread is not in main loop"（Tk 图片泄漏），
    重则 Tcl_Panic 直接 abort 进程（pythonw 下看不到任何提示，事件日志里
    只有 ucrtbase 的 0xc0000409）。统一让主线程丢最后一个引用就绕开了。
    """
    if obj is not None:
        _pending_free.append(obj)


def flush_pending_free():
    """只在主线程调用：真正把攒下的 Tk 对象释放掉。"""
    if _pending_free:
        _pending_free.clear()


_pending_free = []


def install_crash_diagnostics():
    """把 pythonw 看不到的崩溃信息落盘。

    实测（Windows 事件日志）：进程是**硬崩**的 ——
        pythonw.exe / ucrtbase.dll / 0xc0000409 / BEX64
    0xc0000409 的 P9=7 = FAST_FAIL_FATAL_APP_EXIT，也就是**进程调了 abort()**。
    Python 的 Py_FatalError、Tcl 的 Tcl_Panic 都会先往 **C 层 stderr** 打一行
    再 abort，而 pythonw 根本没有控制台，那行字就永远看不到了。这里做两件事：

      1. 把文件描述符 2 重定向到 pet_stderr.log —— 复制 fd 而不是换 sys.stderr，
         所以 C 层（fprintf(stderr)）的输出也能抓到；
      2. 打开 faulthandler：真收到 SIGSEGV/SIGABRT 时把**所有线程**的 Python
         栈写进 pet_error.log。
    """
    global _stderr_log
    try:
        path = os.path.join(ROOT, "pet_stderr.log")
        if os.path.exists(path) and os.path.getsize(path) > 256 * 1024:
            os.remove(path)
        _stderr_log = open(path, "a", encoding="utf-8", errors="replace", buffering=1)
        try:
            os.dup2(_stderr_log.fileno(), 2)
        except OSError:
            pass
        # pythonw 下 sys.stdout / sys.stderr 都是 None：任何 print() 都会抛
        # RuntimeError("lost sys.stdout")。只有它们确实是 None 时才接到文件上，
        # 控制台运行（python.exe）时保持原样，--where 之类的输出还能看见。
        if sys.stdout is None:
            sys.stdout = _stderr_log
        if sys.stderr is None:
            sys.stderr = _stderr_log
    except Exception:
        pass
    try:
        import faulthandler
        fh = open(os.path.join(ROOT, "pet_error.log"), "a",
                  encoding="utf-8", errors="replace", buffering=1)
        faulthandler.enable(file=fh, all_threads=True)
        _fault_log = fh
    except Exception:
        pass


_stderr_log = None
_fault_log = None


def _config_dir():
    """配置放哪：边上的目录能写就放边上（绿色版），否则退到用户目录。

    不看 sys.frozen —— 冻结后 __file__ 在 _internal 里面，判断会出错，直接试写
    最实在。exe 放在 Program Files 之类没写权限的地方时自动退到用户目录。
    """
    candidates = []
    if not FROZEN:
        candidates.append(ROOT)                      # 开发时就在项目里
    candidates.append(ROOT)                          # 绿色版：exe 旁边
    base = os.environ.get("LOCALAPPDATA")
    if base:
        candidates.append(os.path.join(base, "DesktopPet"))
    base = os.environ.get("APPDATA")
    if base:
        candidates.append(os.path.join(base, "DesktopPet"))
    candidates.append(os.path.expanduser("~"))
    for path in candidates:
        if os.path.exists(os.path.join(path, CONFIG_NAME)) or _writable(path):
            return path
    return ROOT


CONFIG_PATH = os.path.join(_config_dir(), CONFIG_NAME)

# 立绘来自 image/ 文件夹，右键菜单里按文件名切换。
IMAGE_DIR = os.path.join(ROOT, "image")
DEFAULT_IMAGE = "中性灰.png"

# 歌放在 music/ 里，右键菜单里挑（mp3/wav/m4a/flac/ogg/wma）
MUSIC_DIR = os.path.join(ROOT, "music")
# 右键「打开网页」里的站点（用系统默认浏览器打开）
WEB_LINKS = (
    ("Bilibili", "https://www.bilibili.com"),
    ("GitHub", "https://github.com"),
    ("DeepSeek", "https://chat.deepseek.com"),
    ("豆包", "https://www.doubao.com"),
    ("知乎", "https://www.zhihu.com"),
    ("微博", "https://weibo.com"),
    ("YouTube", "https://www.youtube.com"),
    ("百度", "https://www.baidu.com"),
)
DEFAULT_WEB_LINKS = list(WEB_LINKS)


def normalize_url(text):
    """把用户填的网址整理成能直接打开的样子；不像网址就返回空串。"""
    url = (text or "").strip()
    if not url:
        return ""
    url = url.replace(" ", "")
    if url.lower().startswith(("http://", "https://")):
        pass
    elif "://" in url:                      # ftp:// 之类也放行
        pass
    else:
        url = "https://" + url
    rest = url.split("://", 1)[-1]
    if not rest or "." not in rest.split("/", 1)[0]:
        return ""
    return url


PHRASES = [
    "大家好，我是你的桌面小助手。",
    "记得喝水，别一直盯着屏幕。",
    "这个需求……我建议再想想。",
    "坐直一点，肩颈会舒服很多。",
    "代码能跑就别动它。",
    "我已经在这儿站了很久了。",
    "要不要先写个 TODO 再动手？",
    "摸鱼一时爽，一直摸鱼一直爽。",
    "检测到你已经很久没眨眼了。",
    "今天的 bug 是明天的 feature。",
    "需要我帮你记一下吗？",
    "别急，先复现一遍。",
    "辛苦了，休息五分钟吧。",
    "麦克风已就位，可以发言了。",
]

FONT_FAMILY = "Microsoft YaHei UI"
FONT_SIZE = 10

# --------------------------------------------------------------- 可选 Win32
try:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _gdi32 = ctypes.windll.gdi32
except Exception:  # pragma: no cover - 非 Windows
    ctypes = None
    wintypes = None
    _user32 = None
    _gdi32 = None

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CAPTION = 0x00C00000
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01


class BLENDFUNCTION(ctypes.Structure if ctypes else object):
    _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                ("SourceConstantAlpha", ctypes.c_byte), ("AlphaFormat", ctypes.c_byte)]


class BITMAPINFOHEADER(ctypes.Structure if ctypes else object):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]


class BITMAPINFO(ctypes.Structure if ctypes else object):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER),
                ("bmiColors", ctypes.c_uint32 * 3)]


class _RECT(ctypes.Structure if ctypes else object):
    _fields_ = [("left", ctypes.c_int), ("top", ctypes.c_int),
                ("right", ctypes.c_int), ("bottom", ctypes.c_int)]


class _MONITORINFO(ctypes.Structure if ctypes else object):
    _fields_ = [("cbSize", ctypes.c_uint32), ("rcMonitor", _RECT),
                ("rcWork", _RECT), ("dwFlags", ctypes.c_uint32)]


class GUITHREADINFO(ctypes.Structure if ctypes else object):
    """GetGUIThreadInfo 的结果：系统眼里"谁的窗口是活动的、焦点在谁那"。

    这是判断"按键到底会送到哪"的唯一可靠依据：Tk 的 focus_get() 只反映 Tk
    自己的模型，SetFocus 也可能静默失败（前台被别的进程占着的时候）。
    """
    _fields_ = [("cbSize", ctypes.c_uint32), ("flags", ctypes.c_uint32),
                ("hwndActive", ctypes.c_void_p), ("hwndFocus", ctypes.c_void_p),
                ("hwndCapture", ctypes.c_void_p), ("hwndMenuOwner", ctypes.c_void_p),
                ("hwndMoveSize", ctypes.c_void_p), ("hwndCaret", ctypes.c_void_p),
                ("rcCaret", ctypes.c_int * 4)]


GUI_INMENUMODE = 0x00000004
GUI_POPUPMENUMODE = 0x00000010
GUI_SYSTEMMENUMODE = 0x00000008


def _declare_win32():
    """显式声明用到的 Win32 原型（句柄/指针必须按 64 位声明）。

    ctypes 默认把返回值当 32 位 int：**本机实测 GetDC 返回 0x4501173F、
    CreateCompatibleDC 返回负数**，也就是真实句柄超过了 2^31。不声明的话
    这个被截断的值会原样传回 GDI/User32（参数默认也按 c_int 转换），对方
    拿到的是一个非法句柄 —— 表现就是 layered 后端一帧都画不出来（一直以为
    是 DWM 不合成），严重时还会让 GDI 内部踩到坏指针直接崩掉进程。
    """
    if _user32 is None:
        return
    L = ctypes
    HWND, UINT, DWORD, BOOL, LONG = (wintypes.HWND, wintypes.UINT, wintypes.DWORD,
                                     wintypes.BOOL, wintypes.LONG)
    _user32.GetParent.restype = HWND
    _user32.GetParent.argtypes = [HWND]
    _user32.GetWindow.restype = HWND
    _user32.GetWindow.argtypes = [HWND, UINT]
    _user32.GetAncestor.restype = HWND
    _user32.GetAncestor.argtypes = [HWND, UINT]
    _user32.GetForegroundWindow.restype = HWND
    _user32.GetFocus.restype = HWND
    _user32.GetCapture.restype = HWND
    _user32.SetActiveWindow.restype = HWND
    _user32.SetActiveWindow.argtypes = [HWND]
    _user32.SwitchToThisWindow.argtypes = [HWND, BOOL]
    _user32.GetGUIThreadInfo.restype = BOOL
    _user32.GetGUIThreadInfo.argtypes = [DWORD, ctypes.POINTER(GUITHREADINFO)]
    _user32.SendMessageTimeoutW.restype = wintypes.LPARAM
    _user32.SendMessageTimeoutW.argtypes = [HWND, UINT, wintypes.WPARAM,
                                            wintypes.LPARAM, UINT, UINT,
                                            ctypes.POINTER(ctypes.c_size_t)]
    _user32.SetFocus.argtypes = [HWND]
    _user32.SetForegroundWindow.argtypes = [HWND]
    _user32.GetWindowLongW.restype = LONG
    _user32.GetWindowLongW.argtypes = [HWND, ctypes.c_int]
    _user32.SetWindowLongW.restype = LONG
    _user32.SetWindowLongW.argtypes = [HWND, ctypes.c_int, LONG]
    _user32.GetWindowRect.argtypes = [HWND, L.POINTER(wintypes.RECT)]
    _user32.GetWindowRect.restype = BOOL
    _user32.IsWindowVisible.argtypes = [HWND]
    _user32.IsIconic.argtypes = [HWND]
    _user32.IsZoomed.argtypes = [HWND]
    _user32.IsZoomed.restype = BOOL
    # 全屏检测：前台窗口的类名 + 它所在显示器的矩形
    _user32.GetClassNameW.argtypes = [HWND, ctypes.c_wchar_p, ctypes.c_int]
    _user32.GetClassNameW.restype = ctypes.c_int
    _user32.MonitorFromWindow.restype = ctypes.c_void_p
    _user32.MonitorFromWindow.argtypes = [HWND, DWORD]
    _user32.GetMonitorInfoW.restype = BOOL
    _user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p,
                                        ctypes.POINTER(_MONITORINFO)]
    _user32.SetWindowPos.argtypes = [HWND, HWND, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, UINT]
    _user32.GetCursorPos.argtypes = [L.POINTER(wintypes.POINT)]
    _user32.SystemParametersInfoW.argtypes = [UINT, UINT, L.c_void_p, UINT]
    _user32.AttachThreadInput.argtypes = [DWORD, DWORD, BOOL]
    _user32.GetWindowThreadProcessId.restype = DWORD
    _user32.GetWindowThreadProcessId.argtypes = [HWND, L.POINTER(DWORD)]
    _user32.SendMessageW.argtypes = [HWND, UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.SendMessageW.restype = ctypes.c_ssize_t
    _user32.PostMessageW.argtypes = [HWND, UINT, wintypes.WPARAM, wintypes.LPARAM]
    # 看门狗线程要能直接把卡住的气泡窗口藏掉（只传 HWND，别让 64 位句柄被截断）
    _user32.ShowWindow.argtypes = [HWND, ctypes.c_int]
    _user32.ShowWindow.restype = BOOL
    _user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, DWORD, L.c_void_p]
    _user32.GetKeyboardLayoutList.restype = ctypes.c_int
    _user32.GetKeyboardLayoutList.argtypes = [ctypes.c_int, L.POINTER(wintypes.HKL)]
    _user32.GetDC.restype = wintypes.HDC
    _user32.GetDC.argtypes = [HWND]
    _user32.ReleaseDC.argtypes = [HWND, wintypes.HDC]
    _user32.UpdateLayeredWindow.argtypes = [
        HWND, wintypes.HDC, L.POINTER(wintypes.POINT), L.POINTER(wintypes.SIZE),
        wintypes.HDC, L.POINTER(wintypes.POINT), DWORD,
        L.POINTER(BLENDFUNCTION), DWORD]
    _user32.UpdateLayeredWindow.restype = BOOL

    _gdi32.CreateCompatibleDC.restype = wintypes.HDC
    _gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    _gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    _gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    _gdi32.SelectObject.restype = wintypes.HGDIOBJ
    _gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    _gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    _gdi32.DeleteDC.argtypes = [wintypes.HDC]
    _gdi32.SetDIBits.restype = ctypes.c_int
    _gdi32.SetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, UINT, UINT,
                                 L.c_void_p, L.POINTER(BITMAPINFO), UINT]


_declare_win32()


SPI_GETWORKAREA = 0x0030


def work_area(root):
    """(left, top, right, bottom)：不含任务栏的可用桌面区域。

    Tk 的 winfo_vroot* 是**整个**虚拟桌面（多显示器、含任务栏），本机实测
    vrootheight=1080 而真正的可用高度只有 1032，用它会把宠物站到任务栏下面，
    所以这里问系统要 SPI_GETWORKAREA。
    """
    if _user32 is not None:
        rect = wintypes.RECT()
        if _user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
            return rect.left, rect.top, rect.right, rect.bottom
    left = -root.winfo_vrootx()
    top = -root.winfo_vrooty()
    return left, top, left + root.winfo_vrootwidth(), top + root.winfo_vrootheight()


def _rect_hit(x, y, w, h, rect):
    """(x, y, w, h) 和 rect=(x0, y0, x1, y1) 有没有重叠。"""
    x0, y0, x1, y1 = rect
    return not (x + w <= x0 or x >= x1 or y + h <= y0 or y >= y1)


DEFAULT_APP_CLASSES = ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd")


def _class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    try:
        n = _user32.GetClassNameW(hwnd, buf, 256)
    except Exception:                           # noqa: BLE001
        return ""
    return buf.value if n else ""


def foreground_fullscreen(ignore=()):
    """前台窗口是不是"全屏"（盖住它所在的那一整块显示器）。

    判定：窗口可见、没最小化、不是桌宠自己/它的气泡/设置窗口，窗口矩形完全
    盖住所在显示器，**并且**没有标题栏（真正全屏的窗口会去掉 WS_CAPTION；
    普通"最大化"窗口的矩形虽然也盖满整屏，但它还带着标题栏和边框）。
    是的话返回那个窗口的 hwnd，否则返回 0。

    ignore 里放自己的句柄，避免"设置窗口最大化"被当成全屏。
    """
    if _user32 is None:
        return 0
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd or hwnd in ignore:
            return 0
        if not _user32.IsWindowVisible(hwnd) or _user32.IsIconic(hwnd):
            return 0
        if _user32.IsZoomed(hwnd):
            return 0
        if _class_name(hwnd) in DEFAULT_APP_CLASSES:
            return 0
        style = _user32.GetWindowLongW(hwnd, GWL_STYLE)
        if style & WS_CAPTION:
            return 0
        rect = wintypes.RECT()
        if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return 0
        mon = _MONITORINFO()
        mon.cbSize = ctypes.sizeof(_MONITORINFO)
        hmon = _user32.MonitorFromWindow(hwnd, 2)   # MONITOR_DEFAULTTONEAREST
        if not hmon or not _user32.GetMonitorInfoW(hmon, ctypes.byref(mon)):
            return 0
    except Exception:                           # noqa: BLE001
        return 0
    m = mon.rcMonitor
    if (rect.left <= m.left and rect.top <= m.top
            and rect.right >= m.right and rect.bottom >= m.bottom):
        return hwnd
    return 0


def _hwnd_of(win):
    return _user32.GetParent(win.winfo_id()) or win.winfo_id()


def _hide_from_alt_tab(win):
    try:
        hwnd = _hwnd_of(win)
        style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | 0x00000080)  # TOOLWINDOW
    except Exception:
        pass


def set_taskbar_button(win, on=True):
    """让 overrideredirect 的宠物窗口出现在（或不出现在）任务栏里。

    Tk 的 overrideredirect 窗口带 WS_EX_TOOLWINDOW，任务栏和 Alt+Tab 里都看不到，
    所以之前只能从右键菜单退出。改成 WS_EX_APPWINDOW 并去掉 TOOLWINDOW，任务栏
    就有图标了 —— 右键任务栏图标 ->「关闭窗口」会发 WM_CLOSE，Tk 会转到
    WM_DELETE_WINDOW（我们已经绑到 quit），于是能直接退出。

    改完要 SetWindowPos(SWP_FRAMECHANGED) 让外壳重新登记这个窗口。
    """
    if _user32 is None:
        return
    try:
        hwnd = _hwnd_of(win)
        style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if not style:
            return
        if on:
            new = (style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
        else:
            new = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
        if new == style:
            return
        _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new)
        SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = (
            0x1, 0x2, 0x4, 0x10, 0x20)
        _user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                             SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER
                             | SWP_NOACTIVATE | SWP_FRAMECHANGED)
    except Exception:
        pass


def has_taskbar_button(win):
    """检查窗口当前是不是"任务栏可见"（给自检用）。"""
    if _user32 is None:
        return False
    try:
        hwnd = _hwnd_of(win)
        style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        return bool(style & WS_EX_APPWINDOW) and not (style & 0x00000080)
    except Exception:
        return False


# ------------------------------------------------------------------ 系统托盘
# 托盘图标（右下角"隐藏的图标"小箭头里面那排）用 Shell_NotifyIconW 实现。
# 它必须在**自己的线程**里跑消息循环 + 一个隐藏窗口：
#   * 不能用 Tk 的窗口 —— 那样得子类化 Tk 的窗口过程，在 Tk 的消息循环里重入
#     Tk 很容易出怪问题（这个项目里已经踩过一次重入的坑）；
#   * 托盘线程绝不碰 Tk，菜单动作统一 post 回主线程执行（_main_thread）。
WM_APP = 0x8000
WM_TRAY = WM_APP + 1
WM_TIMER = 0x0113
RETRY_TIMER_ID = 0x7A11
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_NULL = 0x0000
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x1, 0x2, 0x4
IMAGE_ICON = 1
LR_LOADFROMFILE, LR_DEFAULTSIZE = 0x10, 0x40
MF_STRING = 0x0
TPM_RETURNCMD, TPM_RIGHTBUTTON, TPM_NONOTIFY = 0x100, 0x2, 0x80
SM_CXSMICON, SM_CYSMICON = 49, 50
IDI_APPLICATION = 32512
WS_POPUP = 0x80000000
HWND_MESSAGE = -3


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uID", ctypes.c_uint), ("uFlags", ctypes.c_uint),
                ("uCallbackMessage", ctypes.c_uint), ("hIcon", wintypes.HICON),
                ("szTip", ctypes.c_wchar * 128), ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD), ("szInfo", ctypes.c_wchar * 256),
                ("uVersion", ctypes.c_uint),
                ("szInfoTitle", ctypes.c_wchar * 64),
                ("dwInfoFlags", wintypes.DWORD),
                # Win7 之后的两个尾部字段。少了它们 cbSize 只有 952，Win11 上
                # Shell_NotifyIcon 会直接返回 FALSE（GetLastError=5 看着像"没权限"），
                # 结果就是托盘图标怎么都加不上。
                ("guidItem", ctypes.c_byte * 16),
                ("hBalloonIcon", wintypes.HICON)]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", ctypes.c_uint), ("lpfnWndProc", ctypes.c_void_p),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR)]


_tray_declared = False
_tray_shell32 = None


def _declare_tray_win32():
    """声明托盘用到的那批 Win32 签名。

    不声明的话，64 位下句柄会被当成 32 位 int 处理 —— 实测
    CreateWindowExW 直接抛 OverflowError: int too long to convert（hInstance
    是 64 位句柄）。这个项目和这个坑打过好几次交道了。
    """
    global _tray_declared, _tray_shell32
    if _tray_declared:
        return
    _tray_declared = True
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        # use_last_error=True：不然 GetLastError 拿不到真实错误码
        _tray_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        shell32 = _tray_shell32
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        user32.RegisterClassW.restype = ctypes.c_ushort
        user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, ctypes.c_void_p, ctypes.c_void_p]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint,
                                          wintypes.WPARAM, wintypes.LPARAM]
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadImageW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                      ctypes.c_uint, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_uint]
        user32.LoadIconW.restype = wintypes.HANDLE
        user32.LoadIconW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.RegisterWindowMessageW.restype = ctypes.c_uint
        user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
        user32.CreatePopupMenu.restype = wintypes.HMENU
        user32.AppendMenuW.argtypes = [wintypes.HMENU, ctypes.c_uint,
                                       ctypes.c_size_t, wintypes.LPCWSTR]
        user32.TrackPopupMenu.restype = ctypes.c_int
        user32.TrackPopupMenu.argtypes = [wintypes.HMENU, ctypes.c_uint,
                                         ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                         wintypes.HWND, ctypes.c_void_p]
        user32.DestroyMenu.argtypes = [wintypes.HMENU]
        user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                       ctypes.c_uint, ctypes.c_uint]
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint,
                                        wintypes.WPARAM, wintypes.LPARAM]
        user32.PostQuitMessage.argtypes = [ctypes.c_int]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        shell32.Shell_NotifyIconW.restype = wintypes.BOOL
        shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD,
                                              ctypes.POINTER(NOTIFYICONDATAW)]
    except Exception:                           # noqa: BLE001
        _log_exception()


class TrayIcon:
    """系统托盘图标：右键弹菜单（对话 / 说话 / 退出），左键让宠物跳一下。

    在独立线程里跑；`on_event` 会在那个线程里被调用，调用方负责 post 回主线程。
    """

    _seq = 0

    def __init__(self, tooltip, icon_path, commands, on_event,
                 on_ready=None):
        TrayIcon._seq += 1
        self.on_ready = on_ready
        self.class_name = "DesktopPetTray%d" % TrayIcon._seq
        self.tooltip = (tooltip or "")[:127]
        self.icon_path = icon_path
        self.commands = list(commands)      # [(id, 文案), ...]
        self.on_event = on_event
        self.ok = False
        self.err = 0
        self._add_tries = 0
        self._hwnd = None
        self._thread = None
        self._ready = threading.Event()
        self._wndproc = None                # 必须留引用，否则回调会被 GC
        self._hicon = None
        self._taskbar_msg = None

    # ------------------------------------------------------------ 对外
    def start(self):
        self._thread = threading.Thread(target=self._run, name="pet-tray", daemon=True)
        self._thread.start()
        self._ready.wait(3.0)
        return self.ok

    def stop(self):
        try:
            if self._hwnd and _user32 is not None:
                _user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
        except Exception:                   # noqa: BLE001
            pass

    # ------------------------------------------------------------ 线程里
    def _run(self):
        try:
            _declare_tray_win32()
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND,
                                         ctypes.c_uint, wintypes.WPARAM,
                                         wintypes.LPARAM)
            self._taskbar_msg = user32.RegisterWindowMessageW("TaskbarCreated")

            def wndproc(hwnd, msg, wparam, lparam):
                try:
                    if msg == WM_TRAY:
                        event = lparam & 0xFFFF
                        if event in (WM_RBUTTONUP, 0x007B):        # 右键/上下文
                            self._popup(hwnd)
                        elif event == WM_LBUTTONUP:
                            self.on_event("jump")
                    elif msg == WM_TIMER and wparam == RETRY_TIMER_ID:
                        self._retry_add(hwnd)
                    elif self._taskbar_msg and msg == self._taskbar_msg:
                        self._add()                                # explorer 重启了
                    elif msg == WM_CLOSE:
                        self._delete()
                        user32.DestroyWindow(hwnd)
                        return 0
                    elif msg == WM_DESTROY:
                        user32.PostQuitMessage(0)
                        return 0
                except Exception:                       # noqa: BLE001
                    pass
                return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

            self._wndproc = WNDPROC(wndproc)
            wc = WNDCLASSW()
            wc.lpfnWndProc = ctypes.cast(self._wndproc, ctypes.c_void_p)
            wc.hInstance = kernel32.GetModuleHandleW(None)
            wc.lpszClassName = self.class_name
            if not user32.RegisterClassW(ctypes.byref(wc)):
                self._ready.set()
                return
            # 托盘宿主窗口：先用"隐藏的普通 popup 窗口"（WS_POPUP +
            # WS_EX_TOOLWINDOW，从不 ShowWindow，任务栏/Alt+Tab 都看不见）。
            # 不要一上来就用 HWND_MESSAGE：Win11 上 Shell_NotifyIcon(NIM_ADD)
            # 对 message-only 窗口会返回 FALSE 且 GetLastError=0，打包版稳定踩到。
            self._hwnd = user32.CreateWindowExW(
                WS_EX_TOOLWINDOW, self.class_name, self.class_name,
                WS_POPUP, 0, 0, 0, 0, None, 0, wc.hInstance, None)
            if not self._hwnd:
                # 退回 message-only 窗口再试一次（老系统上它是常规做法）
                self._hwnd = user32.CreateWindowExW(
                    0, self.class_name, self.class_name, 0, 0, 0, 0, 0,
                    wintypes.HWND(HWND_MESSAGE), 0, wc.hInstance, None)
            if not self._hwnd:
                self._ready.set()
                return
            self._hicon = user32.LoadImageW(
                None, self.icon_path, IMAGE_ICON,
                user32.GetSystemMetrics(SM_CXSMICON),
                user32.GetSystemMetrics(SM_CYSMICON), LR_LOADFROMFILE)
            if not self._hicon and getattr(sys, "frozen", False):
                # 打包后优先用 exe 自己的图标资源（icon='assets/pet.ico' 打进去的
                # 第一个图标资源），这样不依赖任何文件路径
                self._hicon = user32.LoadIconW(
                    kernel32.GetModuleHandleW(None), ctypes.c_void_p(1))
            if not self._hicon:
                # 图标文件没找到（比如打包时忘了带上 pet.ico）也要有个图标：
                # 第二个参数是资源 id，得按指针传（MAKEINTRESOURCE）
                self._hicon = user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))
            if not self._hicon:
                # 全 ASCII：pet_stderr.log 是按控制台编码写的，中文会变乱码
                print("tray: no icon handle (path=%s)" % self.icon_path,
                      file=sys.stderr)
            # 添加失败是间歇性的（本机管控软件有时拦、有时放），所以重试几次；
            # 成功就立即返回，失败的那几次最多多花 1.2 秒
            # 注册失败是间歇性的（管控软件会时拦时不拦）：先连试 4 次，
            # 还不行就交给 WM_TIMER 每 3 秒再试，最多试 20 次（约 1 分钟）。
            for attempt in range(4):
                self.ok = bool(self._add())
                if self.ok:
                    break
                if attempt < 3:
                    time.sleep(0.4)
            if not self.ok:
                user32.SetTimer(self._hwnd, RETRY_TIMER_ID, 3000, None)
            self._ready.set()
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception:                       # noqa: BLE001
            _log_exception()
            self._ready.set()

    def _nid(self):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self._hicon
        nid.szTip = self.tooltip
        return nid

    def _retry_add(self, hwnd):
        """定时重试托盘注册；成功就停表，试满 20 次才认输并记一行日志。"""
        user32 = ctypes.windll.user32
        self._add_tries += 1
        if self._add():
            self.ok = True
            user32.KillTimer(hwnd, RETRY_TIMER_ID)
            if self.on_ready is not None:
                try:
                    self.on_ready()
                except Exception:               # noqa: BLE001
                    pass
            return
        if self._add_tries >= 20:
            user32.KillTimer(hwnd, RETRY_TIMER_ID)
            print("tray: Shell_NotifyIcon NIM_ADD failed err=%s icon=%s hwnd=%s"
                  % (ctypes.get_last_error(), self._hicon, self._hwnd),
                  file=sys.stderr)

    def _add(self):
        try:
            shell32 = _tray_shell32 or ctypes.windll.shell32
            nid = self._nid()
            ok = shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
            if not ok:
                self.err = ctypes.windll.kernel32.GetLastError()
                print("tray: NIM_ADD failed err=%s cbSize=%s hwnd=%s icon=%s"
                      % (self.err, ctypes.sizeof(NOTIFYICONDATAW), nid.hWnd,
                         nid.hIcon), file=sys.stderr)
            return ok
        except Exception:                       # noqa: BLE001
            _log_exception()
            return False

    def _delete(self):
        try:
            nid = self._nid()
            nid.uFlags = 0
            shell32 = _tray_shell32 or ctypes.windll.shell32
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        except Exception:                       # noqa: BLE001
            pass

    def _popup(self, hwnd):
        user32 = ctypes.windll.user32
        menu = user32.CreatePopupMenu()
        for cid, label in self.commands:
            user32.AppendMenuW(menu, MF_STRING, cid, label)
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(hwnd)
        cmd = user32.TrackPopupMenu(menu, TPM_RETURNCMD | TPM_RIGHTBUTTON | TPM_NONOTIFY,
                                    pt.x, pt.y, 0, hwnd, None)
        user32.DestroyMenu(menu)
        user32.PostMessageW(hwnd, WM_NULL, 0, 0)     # 让菜单彻底收掉
        if cmd:
            self.on_event(cmd)


def set_overrideredirect(win, on=True):
    """设置窗口的 overrideredirect，绕开 tkinter 的返回值解析。

    不能用 win.overrideredirect(True)：这个包装是

        return self._getboolean(self.tk.call('wm', 'overrideredirect', w, b))

    而 `wm overrideredirect` 自己不写解释器结果，Tcl 会把**上一条命令**的
    结果原样返回。只要那个结果不是 "1"/"0"（实测出现过字符串 "None"），
    这里就抛 `expected boolean value but got "None"` —— 用户日志里的闪退
    就是这一条，位置在气泡窗口 _ensure_win()。直接调 Tcl、不解析返回值，
    再读回来核对一次，就不会被脏结果影响。
    """
    want = "1" if on else "0"
    try:
        win.tk.call("wm", "overrideredirect", str(win), want)
        return str(win.tk.call("wm", "overrideredirect", str(win))) == want
    except tk.TclError:
        return False


# ---------------------------------------------------------------- 鼠标钩子
WH_MOUSE_LL = 14
WM_MOUSEMOVE = 0x0200
LLMHF_INJECTED = 0x00000001


class MSLLHOOKSTRUCT(ctypes.Structure if ctypes else object):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", ctypes.c_uint32),
                ("flags", ctypes.c_uint32), ("time", ctypes.c_uint32),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class MouseHook:
    """全局鼠标移动钩子。

    为什么要用全局钩子：宠物默认压在桌面层，鼠标从它身上划过时，光标其实在
    **别的窗口**上，Tk 的 <Motion> 根本收不到事件。只有 LowLevel 钩子能拿到。
    钩子回调跑在主线程（装钩子的线程要有消息循环，Tk 正好有），所以很轻。
    """

    def __init__(self, on_move):
        self.on_move = on_move
        self.hwnd = None
        self._proc = None
        self.ok = False

    def install(self):
        if _user32 is None:
            return False
        try:
            # 显式声明签名：不声明的话 ctypes 会把 lParam 当 32 位 int，
            # 64 位下的高位指针一转换就 OverflowError，回调每次鼠标移动都炸
            _user32.SetWindowsHookExW.restype = wintypes.HHOOK
            _user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p,
                                                  wintypes.HINSTANCE, wintypes.DWORD]
            _user32.CallNextHookEx.restype = ctypes.c_ssize_t
            _user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int,
                                               wintypes.WPARAM, wintypes.LPARAM]
            _user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]

            proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                                           wintypes.WPARAM, wintypes.LPARAM)

            def _callback(n_code, w_param, l_param):
                if n_code >= 0 and w_param == WM_MOUSEMOVE:
                    try:
                        info = ctypes.cast(ctypes.c_void_p(l_param),
                                           ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                        if not (info.flags & LLMHF_INJECTED):
                            self.on_move(info.pt.x, info.pt.y)
                    except Exception:
                        pass
                return _user32.CallNextHookEx(None, n_code, w_param, l_param)

            self._proc = proc_type(_callback)
            self.hwnd = _user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, None, 0)
            self.ok = bool(self.hwnd)
        except Exception:
            self.ok = False
        return self.ok

    def remove(self):
        if self.ok and self.hwnd:
            try:
                _user32.UnhookWindowsHookEx(self.hwnd)
            except Exception:
                pass
        self.ok = False
        self.hwnd = None
        self._proc = None        # 回调必须活到卸载之后


# =====================================================================
# 绘图：卡片 / 尾巴 / 文字，全部用 PIL 画，两种后端共用同一套几何
# =====================================================================
SS = 4  # 超采样倍数，用来给圆角做抗锯齿


def draw_round_rect(draw, box, radius, **kw):
    draw.rounded_rectangle(box, radius=radius, **kw)


def draw_card(size, radius, card_h, tail_x, tail_w=10, tail_h=12,
              bg="#fbfaf4", edge="#4a5060", tail_at_top=False):
    """画气泡卡片（含指向宠物的小尾巴），超采样后缩回，边缘平滑。

    tail_at_top：气泡翻到头**下面**时用。尾巴要画在卡片顶部、朝上指着头，
    以前不管翻不翻都画在底部，翻下去之后尾巴就朝反方向翘着了。
    """
    w, h = size
    img = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ax = tail_x * SS
    if tail_at_top:
        ct = tail_h * SS                     # 卡片顶边，上面留给尾巴
        cb = (h - 2) * SS
        draw_round_rect(d, [1 * SS, ct, (w - 2) * SS, cb], radius * SS,
                        fill=bg, outline=edge, width=2 * SS)
        d.polygon([(ax - tail_w * SS, ct + SS), (ax + tail_w * SS, ct + SS),
                   (ax, 1 * SS)], fill=bg, outline=edge, width=2 * SS)
        d.line([(ax - tail_w * SS + SS, ct + SS), (ax + tail_w * SS - SS, ct + SS)],
               fill=bg, width=3 * SS)
    else:
        ct = 1 * SS
        cb = card_h * SS
        draw_round_rect(d, [1 * SS, ct, (w - 2) * SS, cb], radius * SS,
                        fill=bg, outline=edge, width=2 * SS)
        d.polygon([(ax - tail_w * SS, cb - SS), (ax + tail_w * SS, cb - SS),
                   (ax, (h - 2) * SS)], fill=bg, outline=edge, width=2 * SS)
        d.line([(ax - tail_w * SS + SS, cb - SS), (ax + tail_w * SS - SS, cb - SS)],
               fill=bg, width=3 * SS)
    return img.resize((w, h), Image.LANCZOS)


def draw_lines(img, lines, font, line_h, top, color):
    """把已经折好行的文字画到卡片上（行内居中）。"""
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        width = d.textlength(line, font=font)
        y = top + i * line_h + (line_h - font.getmetrics()[0]) // 2
        d.text(((img.size[0] - width) / 2.0, y), line, font=font, fill=color)
    return img


def pick_pil_font(tk_font, sample):
    """找一个宽度最接近给定 Tk 字体实测宽度的 PIL 字体。

    同一个字号在 Tk（点）和 PIL（像素）下宽度不同，气泡是用 PIL 画的，
    卡片宽度却是按 Tk 度量算的，所以必须实测对齐，不能猜字号。
    """
    target = tk_font.measure(sample)
    best, best_err = None, None
    for px in range(9, 26):
        for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc"):
            try:
                f = ImageFont.truetype("C:/Windows/Fonts/" + name, px)
            except Exception:
                continue  # 这个字体没有，试下一个
            err = abs(f.getlength(sample) - target)
            if best_err is None or err < best_err:
                best, best_err = f, err
            break  # 同一字号下用第一个可用的字体
    return best or ImageFont.load_default()


# =====================================================================
# 窗口后端
# =====================================================================
class ColorKeyWindow:
    """退化后端：Tk 的一位透明 + 纯色抠底。"""

    style = "colorkey"

    def __init__(self, app):
        self.app = app
        self.canvas = app.canvas
        self.item = None
        self._key = None
        self._pil = None            # 上一次贴上去的 PIL 图（同一个就不重建）
        self._photo = None

    def _use_image(self, image):
        """把 PIL 图换成 Tk 图片（同一对象就复用）。

        这是压扁/转圈/打飞机能看见的关键：set_frame() 以前只挪坐标、
        **完全没用传进来的 image**，所以 colorkey 后端下面压扁只有位移、
        没有真的变形 —— 看起来就像没动画。
        """
        if image is not self._pil:
            # 显式指定 master：不指定的话 Pillow 用 tkinter._default_root，进程里
            # 只要出现第二个 Tk 解释器（或旧的根窗口还没清干净），图片就会建到
            # 另一个解释器上，create_image 抛 "image pyimageNNN doesn't exist"
            old_photo = self._photo
            self._photo = ImageTk.PhotoImage(image, master=self.canvas)
            self._pil = image
            defer_photo_free(old_photo)      # 旧的留给主线程放
        photo = self._photo
        if self.item is None:
            self.item = self.canvas.create_image(
                self.app.win_w // 2, self.app.win_h - 2, image=photo, anchor="s")
        else:
            self.canvas.itemconfigure(self.item, image=photo)
        return photo

    def show(self, image, x=None, y=None):
        # 引用存在后端对象上，不挂到 canvas.image：挂到控件上会形成
        # canvas <-> photo 的引用环，环只能靠循环 GC 收，而循环 GC 可能跑在
        # AI 线程里 —— Tkinter 对象在工作线程里析构会出各种怪问题
        self._use_image(image)
        self.canvas.coords(self.item, self.app.win_w // 2, self.app.win_h - 2)

    def move(self, x, y):
        self.app.root.geometry("+%d+%d" % (int(x), int(y)))

    def set_frame(self, image, dx, dy):
        self._use_image(image)
        self.canvas.coords(self.item, self.app.win_w // 2 + dx, self.app.win_h - 2 + dy)

    def apply_key(self, key):
        self._key = key
        self.app.root.configure(bg=key)
        self.canvas.configure(bg=key)
        try:
            self.app.root.attributes("-transparentcolor", key)
        except tk.TclError:
            pass

    def set_click_through(self, on):
        if _user32 is None:
            return
        hwnd = _hwnd_of(self.app.root)
        style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE) | WS_EX_LAYERED
        style = style | WS_EX_TRANSPARENT if on else style & ~WS_EX_TRANSPARENT
        _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)


class LayeredWindow:
    """Win32 逐像素 alpha：UpdateLayeredWindow，边缘真正平滑。"""

    style = "layered"

    def __init__(self, app):
        self.app = app
        self.win = app.root
        self.hwnd = None
        self._last = None       # (图, x, y)：同一张图同一位置不用重复喂

    def apply_key(self, key):
        pass  # 逐像素 alpha 不需要抠底色

    def show(self, image, x=None, y=None):
        self._show_win()
        if x is None or y is None:
            x, y = self.app.pos
        self.feed(image, x, y)

    def _show_win(self):
        self.hwnd = _hwnd_of(self.win)
        self._last = None
        style = _user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
        _user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)

    def screen_pos(self):
        """窗口的当前真实位置（调试用）。"""
        r = wintypes.RECT()
        if _user32.GetWindowRect(self.hwnd, ctypes.byref(r)):
            return r.left, r.top
        return self.app.pos

    def feed(self, image, x, y):
        """把 RGBA 图像通过 UpdateLayeredWindow 贴到屏幕绝对坐标 (x, y)。

        这个调用会同时设定窗口位置和内容，所以喂进来的必须是最终坐标，
        不能让 Tk 的几何管理再定位一次（那会把坐标翻倍）。

        GDI 对象用 try/finally 收尾：feed 每秒被调 25 次，一旦 SetDIBits 或
        UpdateLayeredWindow 抛异常而没清理，DC/位图会迅速泄漏。
        """
        # 静止的宠物每帧都在同一位置喂同一张图：每次都要 CreateCompatibleDC
        # + Bitmap + 整张转 BGRA，一秒 25 次纯浪费；GDI 句柄一旦哪天没删干净，
        # 手柄耗尽的表现就是整个桌面画不动（看着像"卡死"）。没变化直接跳过。
        key = (image, int(x), int(y))
        last = self._last
        if (last is not None and last[0] is key[0]
                and last[1] == key[1] and last[2] == key[2]):
            return
        w, h = image.size
        data = image.tobytes("raw", "BGRA")
        buf = ctypes.create_string_buffer(data, len(data))
        screen_dc = _user32.GetDC(0)
        mem_dc = None
        bmp = None
        old = None
        try:
            mem_dc = _gdi32.CreateCompatibleDC(screen_dc)
            bmp = _gdi32.CreateCompatibleBitmap(screen_dc, w, h)
            old = _gdi32.SelectObject(mem_dc, bmp)
            if not mem_dc or not bmp:
                return                      # 句柄拿不到就别硬来，交给上层重画

            info = BITMAPINFO()
            info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            info.bmiHeader.biWidth = w
            info.bmiHeader.biHeight = -h          # 负数 = 自上而下
            info.bmiHeader.biPlanes = 1
            info.bmiHeader.biBitCount = 32
            info.bmiHeader.biCompression = 0      # BI_RGB
            _gdi32.SetDIBits(mem_dc, bmp, 0, h, ctypes.cast(buf, ctypes.c_void_p),
                             ctypes.byref(info), 0)

            blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
            pt_dst = wintypes.POINT(int(x), int(y))
            pt_src = wintypes.POINT(0, 0)
            size = wintypes.SIZE(w, h)
            _user32.UpdateLayeredWindow(self.hwnd, screen_dc, ctypes.byref(pt_dst),
                                        ctypes.byref(size), mem_dc, ctypes.byref(pt_src),
                                        0, ctypes.byref(blend), ULW_ALPHA)
            self._last = key
        finally:
            if mem_dc:
                if old:
                    _gdi32.SelectObject(mem_dc, old)
                if bmp:
                    _gdi32.DeleteObject(bmp)
                _gdi32.DeleteDC(mem_dc)
            _user32.ReleaseDC(0, screen_dc)

    def set_frame(self, image, dx, dy):
        # 位置每次都由 UpdateLayeredWindow 绝对设定，不去读窗口当前位置 ——
        # overrideredirect 下 winfo_rootx 会返回过期的值，读它会让坐标越滚越大。
        #
        # 纵坐标按"图底边 = 窗口底边 - 2"算，和 colorkey 后端画布上的
        # anchor="s" + (win_h - 2) 完全一致。以前这里用的是没缩放过的
        # HEADROOM 常量：默认 0.5 倍时宠物会比 colorkey 低 9px，气泡挂点
        # （head_anchor 按缩放后的 headroom 算）因此偏高，压扁时底边也会
        # 跟着往上跑，脚就不站在地上了。
        # 图片宽度会随"拉长变扁"和旋转变化，必须按当前图宽居中；以前用
        # 固定的 headroom_x，layered 后端下变窄/拉长时会贴到左边。
        cx = self.app.win_x + (self.app.win_w - image.size[0]) // 2 + dx
        self.feed(image, cx,
                  self.app.win_y + self.app.win_h - 2 - image.size[1] + dy)

    def move(self, x, y):
        # 位置由 UpdateLayeredWindow 独占，Tk 的几何管理不要再插手
        pass

    def set_click_through(self, on):
        style = _user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
        style = style | WS_EX_TRANSPARENT if on else style & ~WS_EX_TRANSPARENT
        _user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, style)


def make_window_backend(app, style):
    """style: layered / colorkey / auto(-> colorkey).

    colorkey 走 Tk 的 -transparentcolor，在所有 Windows 会话里都验证过；
    layered 走 Win32 逐像素 alpha，边缘更干净，但在某些被远程/管控软件
    抑制了 DWM 合成的机器上会出现"窗口在、画面不显示"，所以不作默认。
    """
    if style == "layered" and _user32 is not None:
        try:
            backend = LayeredWindow(app)
            backend._show_win()
            print("使用 layered 后端；如果看不到宠物，请改用 --style colorkey",
                  file=sys.stderr)
            return backend
        except Exception as exc:  # pragma: no cover
            print("layered 后端不可用(%s)，改用 colorkey" % exc, file=sys.stderr)
    return ColorKeyWindow(app)

# =====================================================================
# 精灵
# =====================================================================
class Sprite:
    """一张精灵图 + 缩放缓存。图片已经是最终像素（RGB 或 RGBA）。

    key + mask 只有"纯色背景抠底"的图才有：见 cut_out_flat()。带着它缩放时
    会用**硬边**合成，避免 LANCZOS 在人物轮廓上混出一圈底色描边。
    """

    def __init__(self, img, key=None, mask=None):
        self.image = img
        self.size = img.size
        self.key = key
        self.mask = mask
        self._cache = {}
        self._rot_cache = {}
        self._bbox = None

    def content_bbox(self):
        """人物实际占用的矩形（去掉四周的透明/底色留白）。

        摸头的脸红位置要按"头发顶"来算，不能按图片上沿 —— 用户自己裁的
        立绘经常在头顶留一大片空白。
        """
        if self._bbox is None:
            try:
                if self.mask is not None:
                    bbox = self.mask.getbbox()
                elif self.image.mode in ("RGBA", "LA"):
                    bbox = self.image.getchannel("A").getbbox()
                else:
                    bbox = None
            except Exception:                   # noqa: BLE001
                bbox = None
            self._bbox = bbox or (0, 0, self.size[0], self.size[1])
        return self._bbox

    def _harden(self, size):
        """按硬边遮罩把"出血"过的图合成到纯底色上。

        scale=1.0 也必须走这里：出血过的图在背景侧留了一圈"人物色渐变"，
        那不是纯底色，Tk 不会抠掉，屏幕上就是一圈描边。
        """
        if self.mask is None or self.key is None:
            return self.image.resize(size, Image.LANCZOS)
        rgb = self.image if self.image.size == size else self.image.resize(
            size, Image.LANCZOS)
        mask = self.mask if self.mask.size == size else self.mask.resize(
            size, Image.LANCZOS)
        mask = mask.point(lambda v: 255 if v >= 128 else 0)
        return Image.composite(rgb, Image.new("RGB", size, _rgb_of(self.key)), mask)

    def scaled(self, scale, squash=1.0, wide=1.0):
        """scale = 整体大小；squash = 纵向系数；wide = 横向系数。

        打飞机时 chm 会"拉长变扁"：squash > 1（更高）同时 wide < 1（更窄）。
        """
        bucket = (round(scale, 3), round(squash, 3), round(wide, 3))
        if bucket not in self._cache:
            sx, sq, wd = bucket
            if (abs(sx - 1.0) < 1e-6 and abs(sq - 1.0) < 1e-6
                    and abs(wd - 1.0) < 1e-6):
                img = (self.image if self.mask is None else self._harden(self.size))
            else:
                w = max(1, int(round(self.size[0] * sx * wd)))
                h = max(1, int(round(self.size[1] * sx * sq)))
                img = self._harden((w, h))
            # 缓存有上限：反复改大小 + 压扁动画会攒出几十种组合，一张
            # 428x477 的 RGBA 就是 0.8MB，全留着没必要
            if len(self._cache) >= 48:
                self._cache.clear()
            self._cache[bucket] = img
        return self._cache[bucket]

    def rotated(self, scale, squash=1.0, angle=0.0, wide=1.0):
        """在缩放/压扁的基础上再转一个小角度（摸头时整个人往手边歪）。

        colorkey 图不能直接 rotate 压平后的 RGB：PIL 的插值会把底色混进
        轮廓，Tk 又只抠**纯底色**，屏幕上就是一圈绿边/白边。所以这里和
        _harden() 一样，RGB 与遮罩分开旋转，遮罩二值化后再合成。
        """
        if abs(angle) < 0.12:
            return self.scaled(scale, squash, wide)
        bucket = (round(scale, 3), round(squash, 2), round(wide, 2),
                  round(angle * 2.0) / 2.0)
        if bucket not in self._rot_cache:
            sx, sq, wd, ang = bucket
            w = max(1, int(round(self.size[0] * sx * wd)))
            h = max(1, int(round(self.size[1] * sx * sq)))
            if self.mask is not None and self.key is not None:
                rgb = self.image.resize((w, h), Image.LANCZOS)
                mask = self.mask.resize((w, h), Image.LANCZOS)
                # 绕底边中点转：脚不动，上半身往手边歪，像真的被摸歪了
                rgb = rgb.rotate(ang, resample=Image.BICUBIC, expand=False,
                                 center=(w / 2.0, h))
                mask = mask.rotate(ang, resample=Image.BICUBIC, expand=False,
                                   center=(w / 2.0, h))
                mask = mask.point(lambda v: 255 if v >= 128 else 0)
                img = Image.composite(
                    rgb, Image.new("RGB", (w, h), _rgb_of(self.key)), mask)
            else:
                img = self.image.resize((w, h), Image.LANCZOS).rotate(
                    ang, resample=Image.BICUBIC, expand=False,
                    center=(w / 2.0, h))
            # 旋转帧比缩放帧贵得多：缓存小一点，宁可偶尔重算也别吃内存
            if len(self._rot_cache) >= 36:
                self._rot_cache.clear()
            self._rot_cache[bucket] = img
        return self._rot_cache[bucket]

    def frames(self, count, scale, move):
        """预热 count 帧，按实际位移缓存，避免每帧重新缩放。"""
        out = []
        for i in range(count):
            pos = i if i < count // 2 else count - 1 - i
            out.append((self.scaled(scale), move(pos)))
        return out


def _asset_path(name):
    """素材路径：打包成 exe 后从 PyInstaller 的解包目录取。"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidate = os.path.join(base, "assets", name)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(ASSETS, name)


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(int(v) for v in rgb[:3])


def dominant_edge_color(img, band=3):
    """取四条边上出现最多的颜色，当作纯色背景的抠底色。

    用户自己丢进来的图多半是白底照片，edges 上最多的那个颜色基本就是背景色。
    """
    w, h = img.size
    px = img.convert("RGB").load()
    counts = {}
    for x in range(w):
        for y in list(range(min(band, h))) + list(range(max(0, h - band), h)):
            counts[px[x, y]] = counts.get(px[x, y], 0) + 1
    for y in range(h):
        for x in list(range(min(band, w))) + list(range(max(0, w - band), w)):
            counts[px[x, y]] = counts.get(px[x, y], 0) + 1
    if not counts:
        return (255, 255, 255)
    # 取出现次数最多的那个颜色（不按亮度挑，白底黑底都能自适应）
    return max(counts.items(), key=lambda kv: kv[1])[0]


def image_has_alpha(img):
    """真正的透明通道？全不透明的 alpha 通道不算。"""
    if img.mode not in ("RGBA", "LA", "P"):
        return False
    alpha = img.convert("RGBA").split()[3]
    lo, hi = alpha.getextrema()
    return lo < 250          # 存在明显透明的像素


def load_custom_image(path, target_h=TARGET_H):
    """读一张用户图片：缩放到统一高度，返回 (RGBA 图, 是否有透明通道)。"""
    img = _open_rgba(path)
    w, h = img.size
    if w < 8 or h < 8:
        raise ValueError("图片太小了")
    scale = target_h / float(h)
    size = (max(1, int(round(w * scale))), target_h)
    if max(size) > MAX_SIDE:                 # 特别宽的图，按长边再缩一次
        shrink = MAX_SIDE / float(max(size))
        size = (max(1, int(size[0] * shrink)), max(1, int(size[1] * shrink)))
    if size != (w, h):
        img = img.resize(size, Image.LANCZOS)
    return img, image_has_alpha(img)


def _open_rgba(path, limit=MAX_SIDE):
    """打开图片并转成 RGBA，顺手把"超大图"的成本压下来。

    用户往 image/ 里丢一张手机拍的几千万像素照片是很正常的事：直接
    convert("RGBA") 会在点菜单切形象的那一下吃掉几百 MB 内存和好几秒，
    看着就是"卡死"。这里先用 draft() 让 JPEG 在解码阶段就缩到目标尺寸，
    再不行的（PNG 之类）就先缩一次再转 RGBA。
    """
    img = Image.open(path)
    try:
        img.draft("RGBA", (limit, limit))
    except Exception:                       # 只有 JPEG/MPO 支持 draft
        pass
    w, h = img.size
    if max(w, h) > limit:
        shrink = limit / float(max(w, h))
        img = img.resize((max(1, int(w * shrink)), max(1, int(h * shrink))),
                         Image.BILINEAR)
    return img.convert("RGBA")


def _rgb_of(value):
    """把 "#rrggbb" 或 (r,g,b) 统一成 (r,g,b)。"""
    if isinstance(value, str):
        value = value.lstrip("#")
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    return tuple(int(v) for v in value[:3])


def flatten_to(img, key):
    """把 RGBA 压平到纯色上（key 可以是 "#rrggbb" 或 (r,g,b)）。"""
    base = Image.new("RGBA", img.size, _rgb_of(key) + (255,))
    base.alpha_composite(img.convert("RGBA"))
    return base.convert("RGB")


def harden_onto(img, key):
    """按**硬边**把带 alpha 的图合成到纯底色上（Tk 抠底只认完全相等的颜色）。

    抗锯齿边缘的过渡色 ≠ 底色，所以不会被抠掉 —— 屏幕上就是一圈底色描边。
    气泡尤其明显：它的透明色跟着立绘的抠底色走，立绘换成绿幕之后，气泡圆角
    就镶上了一圈绿边。这里把 alpha 二值化，边缘要么是图形自己的颜色、要么是
    纯底色，不会有中间色。
    """
    rgba = img.convert("RGBA")
    alpha = rgba.getchannel("A")
    if alpha.getextrema()[0] >= 255:
        return rgba.convert("RGB")              # 本来就不透明，不用处理
    mask = alpha.point(lambda v: 255 if v >= 128 else 0)
    return Image.composite(rgba.convert("RGB"),
                           Image.new("RGB", rgba.size, _rgb_of(key)), mask)


class PetImage:
    """一张立绘：显示名 + 图片路径 + 抠底色 + 是否有透明通道。

    prefer_colorkey：这张图已经为一位抠底调好了（内置的三张），优先用 colorkey。
    """

    def __init__(self, name, path, key, alpha=False, prefer_colorkey=False):
        self.name = name
        self.path = path
        self.key = key
        self.alpha = alpha
        self.prefer_colorkey = prefer_colorkey

    def __repr__(self):
        return "PetImage(%r, key=%s, alpha=%s)" % (self.name, self.key, self.alpha)


def scan_images(image_dir=None):
    """扫描 image/ 目录，返回按文件名排序的 PetImage 列表。

    内置的三张（中性灰/浅色桌面/深色桌面）如果不在，就从打包素材里补上，
    这样用户删了或者第一次跑也一定有得用。
    """
    image_dir = image_dir or IMAGE_DIR
    found = {}
    if os.path.isdir(image_dir):
        for name in sorted(os.listdir(image_dir)):
            if not name.lower().endswith(IMAGE_EXTS):
                continue
            path = os.path.join(image_dir, name)
            if not os.path.isfile(path):
                continue
            try:
                img, alpha = load_custom_image(path)
            except Exception as exc:        # noqa: BLE001 - 坏图不该拖垮程序
                print("跳过图片 %s: %s" % (name, exc), file=sys.stderr)
                continue
            key = None if alpha else _hex(dominant_edge_color(img))
            found[name] = PetImage(name, path, key, alpha)

    images = []
    for name, _builtin, key, _label in BUILTIN_IMAGES:
        if name in found:
            # image/ 里就是内置那张（可能是 first-run 复制过去的，也可能是用户
            # 自己覆盖的）：保留它调好的固定抠底色，别按普通图片去猜
            item = found.pop(name)
            item.key = key
            item.prefer_colorkey = True
            item.alpha = True
            images.append(item)
        else:
            images.append(PetImage(name, _asset_path(BUILTIN_RGBA[name]), key,
                                   alpha=True, prefer_colorkey=True))
    images.extend(found[n] for n in sorted(found))
    return images


def new_image_folder():
    """第一次运行时把内置立绘写进 image/，让用户知道这个文件夹是干嘛的。"""
    try:
        os.makedirs(IMAGE_DIR, exist_ok=True)
        for name, _b, _k, _l in BUILTIN_IMAGES:
            target = os.path.join(IMAGE_DIR, name)
            if os.path.exists(target):
                continue
            src = _asset_path(BUILTIN_RGBA[name])
            if os.path.exists(src):
                with open(src, "rb") as fin, open(target, "wb") as fout:
                    fout.write(fin.read())
        return True
    except OSError:
        return False


def cut_out_flat(img, key, tolerance=4, bleed=4):
    """把"纯色背景"的图变成硬边抠底版本，返回 (已出血的 RGB 图, 硬边遮罩)。

    为什么需要：Tk 的 -transparentcolor 只认**完全相等**的颜色。程序把图缩放到
    统一高度时用 LANCZOS，人物轮廓上会混出一圈"人物+底色"的过渡色 —— 它们不
    等于底色，于是留在屏幕上变成描边（白底照片是一圈白边，绿幕是一圈绿边）。
    这里：
      1. 按"离底色多远"把背景标出来；
      2. 把背景像素的 RGB 用邻近人物色填掉（出血）——缩放时混进来的就是人物
         自己的颜色，不会把底色带进轮廓；
      3. 遮罩单独缩放并**二值化**，合成时边缘要么是人物、要么是纯底色。

    容差必须小：底色是**纯色**，容差 4 就足够圈出背景；取大了会把接近底色的
    **人物**像素也划成背景 —— 尤其是缩放混出来的中间调（白衬衫的褶皱混合后
    很容易落到某个中灰色上）。所以底色也不要选中间调灰，见
    tools/make_form.py：要选人物身上不可能出现的饱和色（绿幕/品红）。
    """
    key_rgb = _rgb_of(key)
    rgb = img.convert("RGB")
    solid = Image.new("RGB", rgb.size, key_rgb)
    mask = ImageChops.difference(rgb, solid).convert("L").point(
        lambda v: 255 if v > tolerance else 0)
    work = Image.composite(rgb, solid, mask)
    known = mask
    for _ in range(bleed):
        # 出血用的颜色只从"已知区域"里拿：先把背景换成纯底色再模糊，否则第一圈
        # 会把底色混进人物边缘（绿幕就是一圈绿边）
        safe = Image.composite(work, solid, mask)
        blurred = safe.filter(ImageFilter.GaussianBlur(2.0))
        grown = known.filter(ImageFilter.GaussianBlur(2.0)).point(
            lambda v: 255 if v > 8 else 0)
        work = Image.composite(blurred, work, ImageChops.subtract(grown, known))
        known = ImageChops.lighter(known, grown)
    return work, mask


def builtin_sprite_height():
    """内置立绘的高度（420x463）。

    用户图片按这个高度归一化，这样"大小"菜单里选同一档时，各个形象看起来
    一样大（以前用户图片缩到 TARGET_H=232，同一档只有内置的一半大）。
    """
    global _BUILTIN_SPRITE_H
    if _BUILTIN_SPRITE_H is None:
        try:
            with Image.open(_asset_path(BUILTIN_RGBA["中性灰.png"])) as im:
                _BUILTIN_SPRITE_H = int(im.size[1])
        except Exception:                       # noqa: BLE001
            _BUILTIN_SPRITE_H = TARGET_H * 2
    return _BUILTIN_SPRITE_H


def normalize_height(img, target=None):
    """把用户图片压到统一高度（内置素材本来就调好了，不动）。

    统一到"内置立绘的高度"，同一档大小下各形象视觉大小一致。
    """
    target = target or builtin_sprite_height()
    if img.size[1] <= target:
        return img
    scale = target / float(img.size[1])
    return img.resize((max(1, int(round(img.size[0] * scale))), target),
                      Image.LANCZOS)


def sprite_for(pet_image, use_layered):
    """按后端把一张立绘变成 Sprite。

    layered：直接用 RGBA（本机测出来这个后端不显示，见 --style colorkey）
    colorkey：压平到抠底色上；纯色背景图走 cut_out_flat() 的硬边抠底。

    顺序很关键：**先抠底（出血）再缩放到统一高度**。反过来的话，缩放那一步
    已经把人像边缘和底色混在一起了，抠底再准也洗不掉那圈描边。
    """
    img = _open_rgba(pet_image.path)
    user_made = not pet_image.prefer_colorkey      # 内置三张保持原尺寸
    if use_layered:
        return Sprite(normalize_height(img) if user_made else img)
    key = pet_image.key or "#ffffff"
    if pet_image.alpha or pet_image.prefer_colorkey:
        # 带透明通道的图（内置三张也走这里）：直接压平到抠底色上。
        # 顺手把 alpha 留成硬边遮罩：摸头旋转时要靠它把插值出来的底色边洗掉。
        if user_made:
            img = normalize_height(img)
        rgba = img.convert("RGBA")
        mask = rgba.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
        return Sprite(flatten_to(img, key), key=key, mask=mask)
    work, mask = cut_out_flat(img, key)
    work, mask = normalize_height(work), normalize_height(mask)
    return Sprite(work, key=key, mask=mask)


# =====================================================================
# 气泡
# =====================================================================
class SpeechBubble:
    """跟随宠物的气泡。几何由 plan() 算好，绘制交给 PIL（边缘平滑）。"""

    PAD_X, PAD_Y = 16, 10
    TAIL = 12
    TAIL_W = 10
    MAX_W = 250
    MIN_W = 150                   # 带按钮的控制条别窄得像根筷子
    CTRL_H = 34                   # 底部那排按钮占的高度
    BG = "#fbfaf4"
    FG = "#23262e"
    EDGE = "#4a5060"
    SHOW_MS = 4000

    def __init__(self, master, key="#000000"):
        self.master = master
        self.key = key
        self.win = None
        self.backend = None
        self._job = None
        self._plan = None
        self._img = None
        self._below = False
        self._mapped = False        # 窗口是否已经显示出来（省掉重复的 deiconify/lift）
        self._buttons = []          # 控制条上的按钮（放音乐时用）
        self._persistent = False    # 常驻（不自动消失）
        self._tkfont = tkfont.Font(root=master, family=FONT_FAMILY, size=FONT_SIZE)
        self._pilfont = pick_pil_font(self._tkfont, "桌面宠物 Desktop Pet 1234")

    # ---------------------------------------------------------- 布局
    def wrap(self, text):
        """按像素宽度自己折行（canvas 的 -width 在这里不生效）。"""
        f = self._tkfont
        lines = []
        for para in text.split("\n"):
            cur = ""
            for ch in para:
                if cur and f.measure(cur + ch) > self.MAX_W:
                    lines.append(cur)
                    cur = ch
                else:
                    cur += ch
            lines.append(cur)
        return lines or [""]

    def place(self, w, h, card_bottom, anchor, screen, want_below=None,
              avoid=None):
        """把气泡摆到宠物头顶上方（放不下就翻到下方），返回 (x, y, tail_x, below)。

        尾巴的 x 始终指向 anchor，只要窗口被屏幕边缘推回来，尾巴就跟着挪，
        但不允许跑出卡片。

        avoid：一个 (x0, y0, x1, y1) 矩形（聊天窗口）。气泡默认位置要是压到它，
        就依次试"贴它左边""贴它右边""挪到它上面" —— 实测聊天窗开着时气泡会
        正好盖住窗里的输入框和"发送"按钮，点不到。
        """
        left, top, right, bottom = screen
        x = int(round(anchor[0] - w / 2.0))
        x = max(left + 4, min(right - w - 4, x))
        tail_x = max(self.TAIL_W + 8.0, min(w - self.TAIL_W - 8.0, anchor[0] - x))

        if want_below is None:
            # 卡片底边贴着头顶往上放；卡片顶部跑到屏幕外就翻到下面
            want_below = anchor[1] - card_bottom - 2 < top + 80
        # 翻到下面时尾巴挂在卡片顶部、朝上指着头，所以窗口顶边（=尾巴尖）
        # 只留 2px，和"放在头顶上方"时的 2px 对称
        y = int(round(anchor[1] + 2 if want_below
                      else anchor[1] - card_bottom - 2))
        y = max(top + 4, min(bottom - h - 4, y))

        if avoid is not None and _rect_hit(x, y, w, h, avoid):
            for cx, cy in self._avoid_candidates(w, h, x, y, avoid, screen):
                if not _rect_hit(cx, cy, w, h, avoid):
                    x, y = cx, cy
                    break
        tail_x = max(self.TAIL_W + 8.0, min(w - self.TAIL_W - 8.0, anchor[0] - x))
        return x, y, tail_x, bool(want_below)

    @staticmethod
    def _avoid_candidates(w, h, x, y, avoid, screen):
        """躲开 avoid 的候选位置（按优先级）。"""
        left, top, right, bottom = screen
        ax0, ay0, ax1, ay1 = avoid
        cands = [
            (ax0 - w - 8, y),               # 贴聊天窗左边
            (ax1 + 8, y),                   # 贴右边
            (x, ay0 - h - 8),               # 挪到聊天窗上面
            (x, ay1 + 8),                   # 挪到下面（多半出屏）
        ]
        out = []
        for cx, cy in cands:
            if left + 4 <= cx <= right - w - 4 and top + 4 <= cy <= bottom - h - 4:
                out.append((int(cx), int(cy)))
        return out

    def plan(self, text, anchor, screen, avoid=None, extra_h=0, min_w=None):
        f = self._tkfont
        lines = self.wrap(text)
        line_h = f.metrics("linespace") + 2
        tw = max(f.measure(ln) for ln in lines)
        # 带一排按钮时底下那排也要放得下（不然按钮会挤出卡片）
        base = self.MIN_W if not min_w else max(self.MIN_W, int(min_w))
        w = max(tw, base - self.PAD_X * 2) + self.PAD_X * 2
        h = line_h * len(lines) + self.PAD_Y * 2 + self.TAIL + int(extra_h)
        card_bottom = h - self.TAIL - 1

        x, y, tail_x, below = self.place(w, h, card_bottom, anchor, screen,
                                        avoid=avoid)
        if below:
            # 尾巴在上：文字整体下移一个尾巴的高度，卡片底边就是图片底边
            text_y = self.PAD_Y + self.TAIL
            card_bottom = h - 2
        else:
            text_y = self.PAD_Y
        return {"x": int(x), "y": int(y), "w": int(w), "h": int(h), "lines": lines,
                "line_h": line_h, "text_y": text_y, "card_bottom": card_bottom,
                "tail_x": tail_x, "tail_at_top": below}

    def render(self, plan):
        card = draw_card((plan["w"], plan["h"]), 12, plan["card_bottom"],
                         plan["tail_x"], tail_w=self.TAIL_W, tail_h=self.TAIL,
                         bg=self.BG, edge=self.EDGE,
                         tail_at_top=plan.get("tail_at_top", False))
        return draw_lines(card, plan["lines"], self._pilfont, plan["line_h"],
                          plan["text_y"], self.FG)

    # ---------------------------------------------------------- 显示
    def set_key(self, key):
        self.key = key
        if self.win is not None and self.win.winfo_exists():
            try:
                self.win.attributes("-transparentcolor", key)
                self.win.configure(bg=key)
            except tk.TclError:
                pass
            # backend 要等第一次 say() 才建起来，气泡关掉再开时它可能是 None
            if self.backend is not None:
                self.backend.apply_key(key)

    def _ensure_win(self, size, want_layered):
        """建气泡窗口；要么全建好，要么一个都不留。

        以前是边建边往 self 上挂：Toplevel 建出来了、后端还没建起来的时候一旦
        抛异常（例如 configure 收到不合法的颜色、母窗口正在销毁），就会留下
        "有窗口、没 backend" 的半成品。_tick 里 follow() 每帧都会去碰
        self.backend，于是刷屏 AttributeError，宠物看着就像卡死了。
        """
        if self.win is not None and self.win.winfo_exists() and self.backend is not None:
            return True
        if self.win is not None:
            # 半成品（有窗口没后端）或者别人销毁过：先收干净再重建，别一直卡在
            # "说不出来话"的状态里
            try:
                if self.win.winfo_exists():
                    self.win.destroy()
            except tk.TclError:
                pass
            self.win = None
            self.backend = None
        self._mapped = False
        win = tk.Toplevel(self.master)
        try:
            # 用 raw Tcl：tkinter 的 overrideredirect() 会把脏结果当布尔解析，
            # 抛 'expected boolean value but got "None"'（用户日志里的闪退）
            set_overrideredirect(win, True)
            win.attributes("-topmost", True)
            win.configure(bg=self.key)
            holder = tk.Frame(win, width=1, height=1, bg=self.key)
            holder.pack()
            backend = None
            if want_layered:
                try:
                    backend = LayeredWindow(_BubbleHost(win, size))
                except Exception:               # noqa: BLE001 - 退回一位抠底
                    backend = None
            if backend is None:
                try:
                    win.attributes("-transparentcolor", self.key)
                except tk.TclError:
                    pass
                backend = _ColorKeyBubble(win, self.key)
            if _user32 is not None:
                _hide_from_alt_tab(win)
        except Exception:
            try:
                win.destroy()
            except Exception:
                pass
            _log_exception()
            return False
        self.win = win
        self.backend = backend
        return True

    def _forget(self):
        """把"这一句"的状态清掉，别让 follow() 拿到半成品。"""
        self._plan = None
        self._img = None
        self._below = False
        self._mapped = False

    def say(self, text, anchor, ms=None, want_layered=True, avoid=None):
        self._clear_buttons()
        self._persistent = False
        # 排版/画图也可能炸（字体缺字、超长文本、PIL 内部错误）：一律当成
        # "这句话没说出来"，绝不能让异常冒到事件回调或 _tick 里去。
        try:
            plan = self.plan(text, anchor, work_area(self.master), avoid=avoid)
            img = self.render(plan)
            if not self._ensure_win((plan["w"], plan["h"]), want_layered):
                self._forget()
                return False
            if self.win is None or self.backend is None or not self.win.winfo_exists():
                raise tk.TclError("气泡窗口没建起来")
            if not self._is_layered():
                self.win.geometry("%dx%d+%d+%d"
                                  % (plan["w"], plan["h"], plan["x"], plan["y"]))
            self.backend.show(img, plan["x"], plan["y"])
            self._map()
        except Exception:
            # 建不起来就当这句没说：状态清干净，_tick 里不会再拿到半成品。
            # 顺手记一笔，方便查"气泡就是不冒出来"的原因。
            _log_exception()
            self._forget()
            return False
        # 记住这次是放在头顶还是头下，跟着宠物移动时保持同一侧
        self._plan = plan
        self._avoid = avoid
        self._below = bool(plan.get("tail_at_top"))
        self._img = img
        self._cancel_job()
        self._job = self.master.after(ms or self.SHOW_MS, self.hide)
        return True

    def _is_layered(self):
        return isinstance(self.backend, LayeredWindow)

    @property
    def hwnd(self):
        """气泡窗口的 Win32 句柄（看门狗急救时用；没有窗口就是 0）。"""
        win = self.win
        if win is None:
            return 0
        try:
            if not win.winfo_exists():
                return 0
            return _hwnd_of(win)
        except tk.TclError:
            return 0

    def _map(self):
        """第一次显示才 deiconify + lift。

        每句话都 deiconify/lift 会让 DWM 反复重算这个 topmost 小窗口的层级，
        点一下宠物冒一句这种高频操作，在别的窗口正抢前台时容易一起卡住。
        """
        win = self.win
        if win is None:
            return
        try:
            if self._mapped and win.winfo_viewable():
                return
            win.deiconify()
            win.lift()
            self._mapped = True
        except tk.TclError:
            raise

    # ---------------------------------------------------------- 常驻控制条
    def _clear_buttons(self):
        for btn in self._buttons:
            try:
                btn.destroy()
            except tk.TclError:
                pass
        self._buttons = []

    def persistent(self):
        return bool(self._persistent)

    def show_controls(self, text, buttons, anchor, avoid=None, want_layered=True,
                      keymap=None):
        """常驻气泡：文字 + 底部一排按钮（放音乐时用，不自动消失）。

        buttons: [(文字, 回调), ...]；keymap: {"<space>": 回调, ...} 绑在气泡窗口上，
        这样点一下气泡再按方向键/空格就能控制（不走全局钩子，没权限也能用）。
        """
        self._clear_buttons()
        gap = 6
        pad = self.PAD_X
        # 一排按钮最少要这么宽：每个至少 42px，加上间距和内边距
        min_w = pad * 2 + max(1, len(buttons)) * 42 + gap * (max(1, len(buttons)) - 1)
        plan = self.plan(text, anchor, work_area(self.master), avoid=avoid,
                         extra_h=self.CTRL_H, min_w=min_w)
        img = self.render(plan)
        try:
            if not self._ensure_win((plan["w"], plan["h"]), want_layered):
                self._forget()
                return False
            if self.win is None or self.backend is None or not self.win.winfo_exists():
                raise tk.TclError("气泡窗口没建起来")
            if not self._is_layered():
                self.win.geometry("%dx%d+%d+%d"
                                  % (plan["w"], plan["h"], plan["x"], plan["y"]))
            self.backend.show(img, plan["x"], plan["y"])
            self._map()
        except tk.TclError:
            _log_exception()
            self._forget()
            return False
        # 按钮：等分，放在卡片下半部分的控制条里
        pad = self.PAD_X
        row_w = plan["w"] - pad * 2
        btn_w = max(36, (row_w - gap * (len(buttons) - 1)) // max(1, len(buttons)))
        row_y = plan["h"] - self.TAIL - self.CTRL_H + 2
        for i, (label, command) in enumerate(buttons):
            try:
                btn = tk.Button(self.win, text=label, command=command,
                                font=(FONT_FAMILY, 9), bd=0, relief="flat",
                                bg="#f1eee2", fg=self.FG,
                                activebackground="#e6e2d2",
                                activeforeground=self.FG, cursor="hand2")
                btn.place(x=pad + i * (btn_w + gap), y=row_y,
                          width=btn_w, height=self.CTRL_H - 8)
                self._buttons.append(btn)
            except tk.TclError:
                _log_exception()
        if keymap:
            for seq, handler in keymap.items():
                try:
                    self.win.bind(seq, handler)
                except tk.TclError:
                    pass
        self._plan = plan
        self._avoid = avoid
        self._below = bool(plan.get("tail_at_top"))
        self._img = img
        self._persistent = True
        self._cancel_job()               # 常驻：不排自动消失的定时器
        return True

    def visible(self):
        """气泡窗口是否真的显示着（overrideredirect 下 state() 会给 normal）。"""
        if self.win is None or self.backend is None:
            return False
        try:
            return bool(self.win.winfo_exists()) and self.win.state() != "withdrawn"
        except tk.TclError:
            return False

    def follow(self, anchor):
        if (self._plan is None or self.win is None or self.backend is None
                or not self.win.winfo_exists()):
            return
        p = self._plan
        x, y, _, _ = self.place(p["w"], p["h"], p["card_bottom"], anchor,
                                work_area(self.master), want_below=self._below,
                                avoid=getattr(self, "_avoid", None))
        if not self._is_layered():
            self.win.geometry("+%d+%d" % (x, y))
        if self._img is not None:
            self.backend.show(self._img, x, y)

    def hide(self):
        self._cancel_job()
        if self.win is not None and self.win.winfo_exists():
            try:
                self.win.withdraw()
            finally:
                self._mapped = False

    def _cancel_job(self):
        if self._job:
            try:
                self.master.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    def destroy(self):
        self._cancel_job()
        if self.win is not None and self.win.winfo_exists():
            self.win.destroy()
        # 后端的 Tk 图片也交回主线程释放，别跟着对象一起在工作线程里被收掉
        defer_photo_free(getattr(self.backend, "_photo", None))
        # 状态一起清掉：对象再被复用（关掉气泡又打开、重开对话框）时会重新
        # 建窗口和后端，不会留着指向已销毁窗口的引用
        self.win = None
        self.backend = None
        self._mapped = False
        self._forget()


class _BubbleHost:
    """让气泡也能复用 LayeredWindow（它只用到 root/pos）。"""

    def __init__(self, win, size):
        self.root = win
        self.size = size
        self.pos = (0, 0)
        self.HEADROOM = 0


class _ColorKeyBubble:
    """气泡的 colorkey 后端：窗口背景就是抠底色，图直接贴上去。"""

    def __init__(self, win, key):
        self.win = win
        self.key = key
        self.canvas = tk.Canvas(win, highlightthickness=0, bd=0, bg=key)
        self.canvas.pack()
        self.item = None
        self._src = None       # 上一张"原始"气泡图（用来判断要不要重建 Tk 图片）
        self._photo = None

    def apply_key(self, key):
        self.key = key
        self.canvas.configure(bg=key)
        self._src = None       # 底色变了，缓存的图要重做

    def show(self, image, x, y):
        # 气泡跟着宠物移动时每帧都会调到这里：图像没变就别重建 Tk 图片。
        # 注意要先按硬边合成到底色上，否则抗锯齿的边缘会留一圈底色描边。
        if image is not self._src:
            old_photo = self._photo
            self._src = image
            self._photo = ImageTk.PhotoImage(harden_onto(image, self.key),
                                             master=self.canvas)
            defer_photo_free(old_photo)
        photo = self._photo
        if self.item is None:
            self.item = self.canvas.create_image(0, 0, image=photo, anchor="nw")
        else:
            self.canvas.itemconfigure(self.item, image=photo)


# =====================================================================
# 摸头：爱心粒子
# =====================================================================
HEART_COLORS = (
    (255, 84, 132), (255, 112, 158), (255, 68, 112),
    (255, 146, 172), (255, 94, 124),
)
SPARKLE_COLORS = (
    (255, 220, 130), (255, 180, 215), (255, 255, 255), (255, 198, 92),
)


def _heart_mask(size=128):
    """用参数方程画一颗爱心，4 倍超采样后缩回来，边缘是平滑的。

    公式本身是 32x30 左右的大小，先按包围盒归一到 size 里，
    这样不同大小的心形状一致，不会出现"小图比例跑掉"。
    """
    ss = 4
    big = size * ss
    img = Image.new("L", (big, big), 0)
    d = ImageDraw.Draw(img)
    n = 160
    raw = []
    for i in range(n):
        t = math.tau * i / n
        hx = 16.0 * math.sin(t) ** 3
        hy = (13.0 * math.cos(t) - 5.0 * math.cos(2 * t)
              - 2.0 * math.cos(3 * t) - math.cos(4 * t))
        raw.append((hx, -hy))                  # 屏幕坐标 y 向下
    xs = [p[0] for p in raw]
    ys = [p[1] for p in raw]
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    pad = 2 * ss
    scale = (big - 2 * pad) / span
    ox = (big - (max(xs) - min(xs)) * scale) / 2.0
    oy = (big - (max(ys) - min(ys)) * scale) / 2.0
    pts = [(ox + (px - min(xs)) * scale, oy + (py - min(ys)) * scale)
           for px, py in raw]
    d.polygon(pts, fill=255)
    return img.resize((size, size), Image.LANCZOS)


def _heart_gloss(size=128):
    """心口左上角的一小片高光（高斯模糊过的椭圆），让爱心不那么扁。"""
    ss = 4
    big = size * ss
    img = Image.new("L", (big, big), 0)
    d = ImageDraw.Draw(img)
    d.ellipse([big * 0.20, big * 0.16, big * 0.39, big * 0.31], fill=150)
    img = img.filter(ImageFilter.GaussianBlur(2.2 * ss))
    return img.resize((size, size), Image.LANCZOS)


def _sparkle_mask(size=96):
    """四角星：摸头时在脑袋边上"叮"一下的小闪光。"""
    ss = 4
    big = size * ss
    img = Image.new("L", (big, big), 0)
    d = ImageDraw.Draw(img)
    cx = cy = big / 2.0
    outer, inner = big * 0.47, big * 0.075
    pts = []
    for i in range(8):
        ang = -math.pi / 2 + i * math.pi / 4
        rad = outer if i % 2 == 0 else inner
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    d.polygon(pts, fill=255)
    img = img.filter(ImageFilter.GaussianBlur(0.7 * ss))
    return img.resize((size, size), Image.LANCZOS)


def _ring_mask(size=128):
    """摸头时的"啪"一下：一圈软边圆环，从头顶扩散开。"""
    ss = 4
    big = size * ss
    img = Image.new("L", (big, big), 0)
    d = ImageDraw.Draw(img)
    pad = big * 0.12
    d.ellipse([pad, pad, big - pad, big - pad],
              outline=255, width=max(2, int(big * 0.030)))
    img = img.filter(ImageFilter.GaussianBlur(2.0 * ss))
    return img.resize((size, size), Image.LANCZOS)


class _HeartParticle:
    __slots__ = ("x", "y", "vx", "vy", "age", "life", "size", "color",
                 "phase", "sway", "kind")

    def __init__(self, x, y, vx, vy, life, size, color, phase, sway,
                 kind="heart"):
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.age = 0.0
        self.life = life
        self.size = size
        self.color = color
        self.phase = phase
        self.sway = sway
        self.kind = kind


class _Ripple:
    __slots__ = ("x", "y", "age", "life", "maxr", "color")

    def __init__(self, x, y, life, maxr, color):
        self.x, self.y = x, y
        self.age = 0.0
        self.life = life
        self.maxr = maxr
        self.color = color


class HeartFX:
    """从宠物头顶冒出来的爱心。

    单独开一个透明的置顶小窗口：宠物本体只有头顶几像素的余量，把爱心画在
    它自己的窗口里会被裁掉；画在气泡窗口里又会跟说话打架。这个窗口是
    逐像素 alpha（layered）+ 鼠标穿透，完全不影响点宠物/下面的窗口。

    粒子用屏幕坐标记位置，窗口只负责"画布"。这样宠物被拖动时，已经冒出来的
    爱心会自然留在原地飘完，而不是粘在头上一起平移。
    """

    MAX_PARTICLES = 36
    MAX_RIPPLES = 2
    SPAWN_INTERVAL = 0.14       # 摸头时大约每 0.14 秒冒一颗爱心
    SPARKLE_INTERVAL = 0.22     # 小星星更密一点，但会自己闪掉
    KEY = "#010203"             # 只能用一位透明的兜底后端才用到

    def __init__(self, pet):
        self.pet = pet
        self.master = pet.root
        self.win = None
        self.backend = None
        self.shown = False
        self.rect = None            # (x, y, w, h)，屏幕坐标
        self.particles = []
        self.ripples = []
        self._spawn_acc = 0.0
        self._sparkle_acc = 0.0
        self._pat_acc = 0.0
        self._mask = _heart_mask()
        self._gloss = _heart_gloss()
        self._sparkle = _sparkle_mask()
        self._ring = _ring_mask()
        self._sprites = {}          # 颜色 -> 128x128 的爱心贴图
        self._sparkle_sprites = {}
        self._ring_sprites = {}
        self._failed = False

    # ---------------------------------------------------------- 粒子
    def burst(self, anchor, count=6, kind="heart"):
        if self._failed:
            return
        if self.rect is None:
            self.rect = self._make_rect(anchor)
        for _ in range(count):
            self._spawn(anchor, kind=kind)
        # 别等下一帧：触发的那一刻就要看得见第一颗
        self._render(anchor)

    def _spawn(self, anchor, kind="heart"):
        if len(self.particles) >= self.MAX_PARTICLES:
            return
        pet = self.pet
        scale = pet.scale
        if kind == "sparkle":
            x = anchor[0] + random.uniform(-0.46, 0.46) * pet.win_w
            y = anchor[1] + random.uniform(-36.0, 20.0)
            vx = random.uniform(-34.0, 34.0)
            vy = random.uniform(-62.0, -26.0)
            life = random.uniform(0.55, 0.95)
            size = random.uniform(9.0, 17.0) * (0.78 + 0.45 * scale)
            color = random.choice(SPARKLE_COLORS)
        else:
            x = anchor[0] + random.uniform(-0.34, 0.34) * pet.win_w
            y = anchor[1] + random.uniform(-8.0, 14.0)
            vx = random.uniform(-15.0, 15.0)
            vy = random.uniform(-72.0, -42.0)
            life = random.uniform(1.25, 1.95)
            size = random.uniform(17.0, 26.0) * (0.78 + 0.45 * scale)
            color = random.choice(HEART_COLORS)
        if self.rect is not None:
            # 宠物贴着屏幕边时窗口会被 clamp 回来，出生点也要跟着收进画布
            x0, y0, w, h = self.rect
            x = max(x0 + 10, min(x0 + w - 10, x))
            y = max(y0 + 10, min(y0 + h - 10, y))
        self.particles.append(_HeartParticle(
            x=x, y=y, vx=vx, vy=vy, life=life, size=size, color=color,
            phase=random.uniform(0.0, math.tau),
            sway=random.uniform(2.0, 8.0) if kind == "sparkle"
            else random.uniform(3.0, 10.0),
            kind=kind,
        ))

    def _make_rect(self, anchor):
        pet = self.pet
        w = max(150, int(pet.win_w * 0.92))
        h = max(165, int(pet.win_h * 0.58))
        top = int(anchor[1] + max(6, pet.headroom) - h)
        # "啪"圈以头顶为圆心往外扩，窗口底边要盖住圈的下半部分，否则会被裁掉
        try:
            face = pet.face_anchor()
            head_y = face[0][1] - face[2] * 0.58
            bottom = int(head_y + max(24.0, pet.win_w * 0.34) + 8)
            top = min(top, bottom - h)
            h = max(h, bottom - top)
        except Exception:                       # noqa: BLE001
            pass
        x = int(anchor[0] - w // 2)
        left, top_edge, right, bottom_edge = work_area(self.master)
        x = max(left, min(right - w, x))
        top = max(top_edge, min(bottom_edge - h, top))
        return (x, top, w, h)

    def _heart_sprite(self, color):
        sprite = self._sprites.get(color)
        if sprite is None:
            sprite = Image.new("RGBA", self._mask.size, color + (0,))
            sprite.putalpha(self._mask)
            gloss = Image.new("RGBA", self._mask.size, (255, 255, 255, 0))
            gloss.putalpha(ImageChops.multiply(self._gloss, self._mask))
            sprite.alpha_composite(gloss)
            # 颜色就那几种，缓存住；粒子大小变化时只 resize，不重画
            self._sprites[color] = sprite
        return sprite

    def _sparkle_sprite(self, color):
        sprite = self._sparkle_sprites.get(color)
        if sprite is None:
            sprite = Image.new("RGBA", self._sparkle.size, color + (0,))
            sprite.putalpha(self._sparkle)
            self._sparkle_sprites[color] = sprite
        return sprite

    def _ring_sprite(self, color):
        sprite = self._ring_sprites.get(color)
        if sprite is None:
            sprite = Image.new("RGBA", self._ring.size, color + (0,))
            sprite.putalpha(self._ring)
            self._ring_sprites[color] = sprite
        return sprite

    def pat(self, x, y, count=1):
        """在 (x, y) 处"啪"一下：扩散一圈圆环。"""
        if self._failed:
            return
        for _ in range(count):
            self.ripples.append(_Ripple(
                x=float(x), y=float(y),
                life=random.uniform(0.40, 0.56),
                maxr=max(16.0, self.pet.win_w * 0.18),
                color=random.choice(((255, 160, 200), (255, 178, 212),
                                     (255, 202, 150), (255, 255, 255))),
            ))
        if len(self.ripples) > self.MAX_RIPPLES:
            self.ripples = self.ripples[-self.MAX_RIPPLES:]

    def _render(self, anchor):
        if not self.particles and not self.ripples:
            self.hide()
            return
        if self.rect is None:
            self.rect = self._make_rect(anchor)
        x0, y0, w, h = self.rect
        if not self._ensure_win():
            return
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        # 先画扩散圈（在爱心/星星下面），营造"拍在头上"的冲击感
        for r in self.ripples:
            progress = min(1.0, r.age / r.life)
            radius = max(4, int(round(r.maxr * (0.10 + 0.90 * progress))))
            alpha = (1.0 - progress) ** 1.5 * 0.62
            if alpha <= 0.01:
                continue
            sprite = self._ring_sprite(r.color).resize(
                (radius * 2, radius * 2), Image.LANCZOS)
            sprite = sprite.copy()
            sprite.putalpha(sprite.getchannel("A").point(
                lambda v: int(v * alpha)))
            canvas.alpha_composite(
                sprite, (int(round(r.x - x0 - radius)),
                         int(round(r.y - y0 - radius))))
        for p in self.particles:
            progress = min(1.0, p.age / p.life)
            if p.kind == "sparkle":
                # 星星：前 8% 亮起来，后面快速淡掉；再叠一点闪烁
                opacity = (min(1.0, p.age / 0.07) * (1.0 - progress) ** 1.4
                           * (0.72 + 0.28 * math.sin(p.age * 34.0 + p.phase)))
                size = max(5, int(round(p.size * (0.75 + 0.5 * progress))))
                sprite = self._sparkle_sprite(p.color).resize(
                    (size, size), Image.LANCZOS)
            else:
                # 爱心：前 12% 淡入，55% 之后淡出
                opacity = min(1.0, p.age / 0.12) * (
                    1.0 - max(0.0, (progress - 0.55) / 0.45))
                size = max(6, int(round(p.size * (0.85 + 0.28 * progress))))
                sprite = self._heart_sprite(p.color).resize(
                    (size, size), Image.LANCZOS)
            if opacity <= 0.012:
                continue
            sprite = sprite.copy()
            sprite.putalpha(sprite.getchannel("A").point(
                lambda v: int(v * max(0.0, min(1.2, opacity)))))
            px = int(round(p.x - x0 - size / 2.0))
            py = int(round(p.y - y0 - size / 2.0))
            canvas.alpha_composite(sprite, (px, py))
        if not self.shown:
            try:
                self.win.deiconify()
                self.win.lift()
                # Tk 把窗口映射出来时可能重写扩展样式，映射完再补一遍穿透
                self._make_click_through(self.win)
            except tk.TclError:
                return
            self.shown = True
        if isinstance(self.backend, LayeredWindow):
            self.backend.show(canvas, x0, y0)
        else:
            try:
                self.win.geometry("%dx%d+%d+%d" % (w, h, x0, y0))
            except tk.TclError:
                return
            self.backend.show(canvas, x0, y0)

    # ---------------------------------------------------------- 窗口
    def _ensure_win(self):
        if self._failed:
            return False
        if (self.win is not None and self.win.winfo_exists()
                and self.backend is not None):
            return True
        if self.win is not None:
            try:
                if self.win.winfo_exists():
                    self.win.destroy()
            except tk.TclError:
                pass
            self.win = None
            self.backend = None
        win = tk.Toplevel(self.master)
        try:
            set_overrideredirect(win, True)
            win.attributes("-topmost", True)
            win.configure(bg=self.KEY)
            win.withdraw()
            tk.Frame(win, width=1, height=1, bg=self.KEY).pack()
            backend = None
            if _user32 is not None:
                try:
                    backend = LayeredWindow(_BubbleHost(win, (1, 1)))
                    backend._show_win()
                except Exception:               # noqa: BLE001 - 退回一位抠底
                    backend = None
            if backend is None:
                try:
                    win.attributes("-transparentcolor", self.KEY)
                except tk.TclError:
                    pass
                backend = _ColorKeyBubble(win, self.KEY)
            _hide_from_alt_tab(win)
            self._make_click_through(win)
        except Exception:
            try:
                win.destroy()
            except Exception:
                pass
            _log_exception()
            self._failed = True
            return False
        self.win = win
        self.backend = backend
        self.shown = False
        return True

    @staticmethod
    def _make_click_through(win):
        """爱心窗口永远不接鼠标：它盖在宠物/桌面上面时不能挡住任何点击。"""
        if _user32 is None:
            return
        try:
            hwnd = _hwnd_of(win)
            style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= (WS_EX_LAYERED | WS_EX_TRANSPARENT
                      | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
            _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    def update(self, dt, anchor, emitting):
        """每帧推进粒子/扩散圈；emitting=True 时按节奏持续冒爱心和小星星。"""
        if not self.particles and not self.ripples and not emitting:
            self._spawn_acc = 0.0
            self._sparkle_acc = 0.0
            self._pat_acc = 0.0
            self.hide()
            return
        if self.rect is None:
            self.rect = self._make_rect(anchor)
        if emitting:
            self._spawn_acc += dt
            while (self._spawn_acc >= self.SPAWN_INTERVAL
                   and len(self.particles) < self.MAX_PARTICLES):
                self._spawn_acc -= self.SPAWN_INTERVAL
                self._spawn(anchor)
            self._sparkle_acc += dt
            while (self._sparkle_acc >= self.SPARKLE_INTERVAL
                   and len(self.particles) < self.MAX_PARTICLES):
                self._sparkle_acc -= self.SPARKLE_INTERVAL
                self._spawn(anchor, kind="sparkle")
            # 手一直在蹭的时候，每隔一会儿补一圈"啪"
            self._pat_acc += dt
            while self._pat_acc >= 0.50:
                self._pat_acc -= 0.50
                try:
                    face = self.pet.face_anchor()
                    hx = self.pet._pet_last_x or (face[0][0] + face[1][0]) / 2.0
                    self.pat(hx, face[0][1] - face[2] * 0.58)
                except Exception:               # noqa: BLE001
                    pass
        else:
            self._spawn_acc = 0.0
            self._sparkle_acc = 0.0
            self._pat_acc = 0.0
        alive = []
        for p in self.particles:
            p.age += dt
            if p.age >= p.life:
                continue
            p.x += (p.vx + math.sin(p.age * 3.2 + p.phase) * p.sway) * dt
            p.y += p.vy * dt
            p.vy -= (6.0 if p.kind == "heart" else 18.0) * dt
            alive.append(p)
        self.particles = alive
        rings = []
        for r in self.ripples:
            r.age += dt
            if r.age < r.life:
                rings.append(r)
        self.ripples = rings
        if self.particles or self.ripples:
            self._render(anchor)
        else:
            self.hide()

    def hide(self):
        if self.shown and self.win is not None:
            try:
                if self.win.winfo_exists():
                    self.win.withdraw()
            except tk.TclError:
                pass
        self.shown = False
        self.rect = None

    def clear(self):
        self.particles = []
        self.ripples = []
        self._spawn_acc = 0.0
        self._sparkle_acc = 0.0
        self._pat_acc = 0.0
        self.hide()

    def active(self):
        return bool(self.particles)

    def destroy(self):
        self.particles = []
        self.ripples = []
        if self.win is not None:
            try:
                if self.win.winfo_exists():
                    self.win.destroy()
            except tk.TclError:
                pass
        self.win = None
        self.backend = None
        self.rect = None
        self.shown = False


# =====================================================================
# 摸头弹幕（会特技的形象才冒：陈瀚铭 / 郑迪隆）
# =====================================================================
DANMAKU_PHRASES = (
    ("きもちいい〜", "kimochi ii · 好舒服～"),
)

# 按人设给的弹幕：日文一行 + 下面一行中文（照着用户给的骚话库挑的）
DANMAKU_PHRASES_BY_PERSONA = {
    "闷骚少年": DANMAKU_PHRASES,
    "骚话少年": (
        ("気持ちいい", "好舒服啊"),
        ("ちょっとドキドキする", "有点心跳加速"),
        ("離さないよ", "不放你走哦"),
        ("君だけだよ", "只有你哦"),
        ("もう一回", "再来一次"),
    ),
}


def _text_font(names, size):
    """按顺序找一个能用的字体；日语优先 Yu Gothic / Meiryo。"""
    for name in names:
        try:
            return ImageFont.truetype(os.path.join("C:/Windows/Fonts", name),
                                      size)
        except Exception:                   # noqa: BLE001 - 换下一个
            continue
    return ImageFont.load_default()


class _DanmakuItem:
    __slots__ = ("img", "x", "y", "vx", "vy", "age", "life", "phase", "jp", "cn")

    def __init__(self, img, x, y, vx, vy, life, jp, cn):
        self.img = img
        self.x = float(x)
        self.y = float(y)
        self.vx = float(vx)
        self.vy = float(vy)
        self.age = 0.0
        self.life = life
        self.phase = random.uniform(0.0, math.tau)
        self.jp = jp
        self.cn = cn


class DanmakuFX:
    """摸头时从头顶往上漂的双语弹幕。

    单独开一个透明小窗口（layered + 鼠标穿透），文字从头顶慢慢往上飘、
    淡入淡出，不会撑大宠物窗口，也不会挡鼠标。只在 chm 这套图上启用，
    由 DesktopPet.danmaku_allowed() 控制。
    """

    MAX_ITEMS = 2
    SPAWN_GAP = 1.25            # 摸头时每隔这么久再补一条
    RISE_SPEED = 46.0           # 初始上飘速度（px/s）

    def __init__(self, pet):
        self.pet = pet
        self.master = pet.root
        self.win = None
        self.backend = None
        self.shown = False
        self.rect = None
        self.items = []
        self._last_spawn = 0.0
        self._img_cache = {}
        self._failed = False

    # ---------------------------------------------------------- 文字
    def _phrases(self):
        """当前形象该冒哪几句（按人设走；取不到就用默认那一句）。"""
        getter = getattr(self.pet, "danmaku_phrases", None)
        if callable(getter):
            try:
                phrases = getter()
            except Exception:               # noqa: BLE001 - 弹幕不值得为此崩
                phrases = None
            if phrases:
                return phrases
        return DANMAKU_PHRASES

    def _text_image(self):
        scale = self.pet.scale
        jp_size = max(19, int(round(26.0 * (0.82 + 0.50 * scale))))
        cn_size = max(13, int(round(17.0 * (0.82 + 0.50 * scale))))
        jp, cn = random.choice(self._phrases())
        key = (jp, cn, jp_size, cn_size)
        cached = self._img_cache.get(key)
        if cached is not None:
            return cached, jp, cn
        ss = 2
        jp_font = _text_font(("YuGothM.ttc", "YuGothR.ttc", "meiryo.ttc",
                              "msgothic.ttc", "msyh.ttc"), jp_size * ss)
        cn_font = _text_font(("msyh.ttc", "msyhbd.ttc", "simhei.ttf"),
                             cn_size * ss)
        stroke = max(2, int(round(1.5 * ss)))
        probe = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        d = ImageDraw.Draw(probe)
        jp_box = d.textbbox((0, 0), jp, font=jp_font, stroke_width=stroke)
        cn_box = d.textbbox((0, 0), cn, font=cn_font, stroke_width=stroke)
        pad = 7 * ss
        gap = 2 * ss
        w = max(jp_box[2] - jp_box[0], cn_box[2] - cn_box[0]) + pad * 2
        h = ((jp_box[3] - jp_box[1]) + (cn_box[3] - cn_box[1])
             + gap + pad * 2)
        img = Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        jp_y = pad - jp_box[1]
        cn_y = pad + (jp_box[3] - jp_box[1]) + gap - cn_box[1]
        # 日本语主行：白字 + 深莓色描边；下面一行罗马音 + 中文
        d.text((pad, jp_y + 1 * ss), jp, font=jp_font,
               fill=(255, 248, 250, 255), stroke_width=stroke,
               stroke_fill=(70, 18, 46, 210))
        d.text((pad, jp_y), jp, font=jp_font,
               fill=(255, 250, 252, 255), stroke_width=stroke,
               stroke_fill=(112, 30, 72, 245))
        d.text((pad, cn_y + 1 * ss), cn, font=cn_font,
               fill=(255, 224, 236, 255), stroke_width=stroke,
               stroke_fill=(70, 18, 46, 210))
        d.text((pad, cn_y), cn, font=cn_font,
               fill=(255, 226, 238, 255), stroke_width=stroke,
               stroke_fill=(112, 30, 72, 245))
        img = img.resize((max(1, int(round(w / ss))),
                          max(1, int(round(h / ss)))), Image.LANCZOS)
        if len(self._img_cache) >= 12:
            self._img_cache.clear()
        self._img_cache[key] = img
        return img, jp, cn

    # ---------------------------------------------------------- 窗口
    def _make_rect(self, anchor):
        pet = self.pet
        try:
            img, _jp, _cn = self._text_image()
            need = img.width + 40
        except Exception:                       # noqa: BLE001
            need = 260
        w = max(240, int(pet.win_w * 1.35), need)
        h = max(230, int(pet.win_h * 0.86))
        x = int(anchor[0] - w // 2)
        bottom = int(anchor[1] - 6)
        y = bottom - h
        left, top, right, bottom_edge = work_area(self.master)
        # 水平只保证"还有一截在屏幕里"：贴在屏幕边时整块居中会有一半在屏幕外，
        # 那是对的（字还是从头顶正上方冒出来）；硬夹回屏幕里就会偏一头。
        x = max(left - w + 60, min(right - 60, x))
        y = max(top, min(bottom_edge - h, y))
        return (x, y, w, h)

    def _ensure_win(self):
        if self._failed:
            return False
        if (self.win is not None and self.win.winfo_exists()
                and self.backend is not None):
            return True
        if self.win is not None:
            try:
                if self.win.winfo_exists():
                    self.win.destroy()
            except tk.TclError:
                pass
            self.win = None
            self.backend = None
        win = tk.Toplevel(self.master)
        try:
            set_overrideredirect(win, True)
            win.attributes("-topmost", True)
            win.configure(bg="#010203")
            win.withdraw()
            tk.Frame(win, width=1, height=1, bg="#010203").pack()
            backend = None
            if _user32 is not None:
                try:
                    backend = LayeredWindow(_BubbleHost(win, (1, 1)))
                    backend._show_win()
                except Exception:               # noqa: BLE001
                    backend = None
            if backend is None:
                try:
                    win.attributes("-transparentcolor", "#010203")
                except tk.TclError:
                    pass
                backend = _ColorKeyBubble(win, "#010203")
            _hide_from_alt_tab(win)
            self._make_click_through(win)
        except Exception:
            try:
                win.destroy()
            except Exception:
                pass
            _log_exception()
            self._failed = True
            return False
        self.win = win
        self.backend = backend
        self.shown = False
        return True

    @staticmethod
    def _make_click_through(win):
        if _user32 is None:
            return
        try:
            hwnd = _hwnd_of(win)
            style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= (WS_EX_LAYERED | WS_EX_TRANSPARENT
                      | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
            _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    # ---------------------------------------------------------- 运行
    def _sync_rect(self, anchor):
        """窗口矩形跟着宠物走：位置变了就把正在飘的字一起平移。

        原来 rect 只在第一次算一次，宠物一走 / 被屏幕边缘夹住，字就留在
        原地，看起来就是"弹幕错位"。
        """
        new = self._make_rect(anchor)
        if self.rect is None:
            self.rect = new
            return
        if tuple(self.rect) == tuple(new):
            return
        # 窗口挪了，字在窗口里不动 —— 看起来就是跟着头走。
        # （以前这里还把每个字平移 dx/dy，结果窗口一动字就留在原地。）
        self.rect = new

    def update(self, dt, anchor, active, now):
        if self.items or active:
            self._sync_rect(anchor)
        if active and len(self.items) < self.MAX_ITEMS:
            if not self.items or now - self._last_spawn >= self.SPAWN_GAP:
                self._spawn(anchor, now)
        alive = []
        for item in self.items:
            item.age += dt
            if item.age >= item.life:
                continue
            item.x += (item.vx + math.sin(item.age * 2.6 + item.phase) * 7.0) * dt
            item.y += item.vy * dt
            item.vy -= 5.0 * dt            # 越飘越快
            if item.y + item.img.height < -8:
                continue
            alive.append(item)
        self.items = alive
        if not self.items:
            self.hide()
            return
        if self.rect is None:
            self.rect = self._make_rect(anchor)
        x0, y0, w, h = self.rect
        if not self._ensure_win():
            return
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        for item in self.items:
            progress = min(1.0, item.age / item.life)
            opacity = (min(1.0, item.age / 0.18)
                       * (1.0 - max(0.0, (progress - 0.58) / 0.42)))
            if opacity <= 0.012:
                continue
            sprite = item.img.copy()
            sprite.putalpha(sprite.getchannel("A").point(
                lambda v: int(v * opacity)))
            canvas.alpha_composite(sprite,
                                   (int(round(item.x)), int(round(item.y))))
        if not self.shown:
            try:
                self.win.deiconify()
                self.win.lift()
                self._make_click_through(self.win)
            except tk.TclError:
                return
            self.shown = True
        if isinstance(self.backend, LayeredWindow):
            self.backend.show(canvas, x0, y0)
        else:
            try:
                self.win.geometry("%dx%d+%d+%d" % (w, h, x0, y0))
            except tk.TclError:
                return
            self.backend.show(canvas, x0, y0)

    def _spawn(self, anchor, now):
        img, jp, cn = self._text_image()
        if self.rect is None:
            self.rect = self._make_rect(anchor)
        x0, y0, w, h = self.rect
        # 按"头顶那个点"定位（不是按矩形中心）：矩形被屏幕边缘夹住时也不会偏
        x = anchor[0] - x0 - img.width / 2.0 + random.uniform(-16.0, 16.0)
        x = max(6.0, min(w - img.width - 6.0, x))
        y = anchor[1] - y0 - img.height - 8
        y = max(4.0, min(h - img.height - 4.0, y))
        self.items.append(_DanmakuItem(
            img=img, x=x, y=y,
            vx=random.uniform(-9.0, 9.0),
            vy=-self.RISE_SPEED * random.uniform(0.85, 1.25),
            life=random.uniform(1.7, 2.35), jp=jp, cn=cn))
        self._last_spawn = now

    def hide(self):
        if self.shown and self.win is not None:
            try:
                if self.win.winfo_exists():
                    self.win.withdraw()
            except tk.TclError:
                pass
        self.shown = False
        self.rect = None

    def clear(self):
        self.items = []
        self._last_spawn = 0.0
        self.hide()

    def active(self):
        return bool(self.items)

    def destroy(self):
        self.items = []
        if self.win is not None:
            try:
                if self.win.winfo_exists():
                    self.win.destroy()
            except tk.TclError:
                pass
        self.win = None
        self.backend = None
        self.rect = None
        self.shown = False


# =====================================================================
# 打飞机
# =====================================================================
class _Plane:
    __slots__ = ("img", "x", "y", "vx", "w", "h", "phase", "dead")

    def __init__(self, img, x, y, vx, phase):
        self.img = img
        self.x = float(x)
        self.y = float(y)
        self.vx = float(vx)
        self.w, self.h = img.size
        self.phase = phase
        self.dead = False


class _Bullet:
    __slots__ = ("x", "y", "vx", "vy", "age", "life")

    def __init__(self, x, y, vx, vy):
        self.x = float(x)
        self.y = float(y)
        self.vx = float(vx)
        self.vy = float(vy)
        self.age = 0.0
        self.life = 1.4


class _Boom:
    __slots__ = ("x", "y", "age", "life", "size", "kind")

    def __init__(self, x, y, life, size, kind="boom"):
        self.x = float(x)
        self.y = float(y)
        self.age = 0.0
        self.life = life
        self.size = size
        self.kind = kind


class ShootFX:
    """打飞机：天空里的飞机 + 从 chm 头顶射出去的子弹。

    全屏透明置顶窗口（layered + 鼠标穿透），只在开火这几秒出现。
    """

    BULLET_INTERVAL = 0.11
    MAX_PLANES = 5

    def __init__(self, pet):
        self.pet = pet
        self.master = pet.root
        self.win = None
        self.backend = None
        self.shown = False
        self.rect = None
        self.planes = []
        self.bullets = []
        self.booms = []
        self.last_bullet = 0.0
        self.active_until = 0.0
        self.zone_center = 0.0
        self.zone_half = 300
        self.zone_left = 0.0
        self.zone_right = 0.0
        self.failed = False
        self._bullet_img = self._make_bullet()

    # ---------------------------------------------------------- 素材
    @staticmethod
    def _make_bullet():
        ss = 3
        w, h = 12, 30
        img = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        glow = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse([1 * ss, 0, 11 * ss, 14 * ss], fill=(255, 200, 80, 150))
        glow = glow.filter(ImageFilter.GaussianBlur(2.0 * ss))
        img.alpha_composite(glow)
        d.ellipse([3 * ss, 1 * ss, 9 * ss, 9 * ss],
                  fill=(255, 250, 190, 255))
        d.rectangle([4 * ss, 7 * ss, 8 * ss, 26 * ss],
                    fill=(255, 230, 120, 220))
        d.rectangle([5 * ss, 8 * ss, 7 * ss, 28 * ss],
                    fill=(255, 255, 235, 235))
        return img.resize((w, h), Image.LANCZOS)

    @staticmethod
    def _make_plane(color, direction, size):
        ss = 3
        w = int(size)
        h = max(24, int(size * 0.48))
        img = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        outline = (42, 46, 64, 255)
        wing = tuple(max(0, c - 30) for c in color) + (255,)
        body = color + (255,)

        def P(x, y):
            return (x * w * ss, y * h * ss)

        d.polygon([P(0.06, 0.34), P(0.20, 0.34), P(0.11, 0.08),
                   P(0.03, 0.08)], fill=wing, outline=outline,
                  width=max(1, ss))
        d.polygon([P(0.34, 0.50), P(0.64, 0.50), P(0.53, 0.10),
                   P(0.30, 0.10)], fill=wing, outline=outline,
                  width=max(1, ss))
        d.polygon([P(0.34, 0.50), P(0.64, 0.50), P(0.58, 0.90),
                   P(0.28, 0.90)], fill=wing, outline=outline,
                  width=max(1, ss))
        d.ellipse([P(0.08, 0.37), P(0.91, 0.63)], fill=body,
                  outline=outline, width=max(1, ss))
        d.polygon([P(0.88, 0.37), P(1.0, 0.50), P(0.88, 0.63)],
                  fill=body, outline=outline, width=max(1, ss))
        d.ellipse([P(0.60, 0.40), P(0.78, 0.55)],
                  fill=(205, 240, 255, 255), outline=outline,
                  width=max(1, ss))
        d.ellipse([P(0.30, 0.45), P(0.39, 0.56)],
                  fill=(255, 255, 255, 235), outline=outline,
                  width=max(1, ss))
        d.line([P(0.99, 0.42), P(0.99, 0.58)], fill=outline,
               width=max(1, ss))
        img = img.resize((w, h), Image.LANCZOS)
        if direction < 0:
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        return img

    # ---------------------------------------------------------- 窗口
    def _make_rect(self):
        pet = self.pet
        left, top, right, bottom = work_area(self.master)
        zl = self.zone_left or (self.zone_center - (self.zone_half or 300))
        zr = self.zone_right or (self.zone_center + (self.zone_half or 300))
        x0 = max(left, int(zl - 150))
        x1 = min(right, int(zr + 150))
        sprite_top = pet.win_y + pet.headroom
        bottom_y = min(bottom, sprite_top + max(150, pet.win_h // 3))
        return (x0, top, max(320, x1 - x0),
                max(320, bottom_y - top))

    def _ensure_win(self):
        if self.failed:
            return False
        if (self.win is not None and self.win.winfo_exists()
                and self.backend is not None):
            return True
        if self.win is not None:
            try:
                if self.win.winfo_exists():
                    self.win.destroy()
            except tk.TclError:
                pass
            self.win = None
            self.backend = None
        win = tk.Toplevel(self.master)
        try:
            set_overrideredirect(win, True)
            win.attributes("-topmost", True)
            win.configure(bg="#010203")
            win.withdraw()
            tk.Frame(win, width=1, height=1, bg="#010203").pack()
            backend = None
            if _user32 is not None:
                try:
                    backend = LayeredWindow(_BubbleHost(win, (1, 1)))
                    backend._show_win()
                except Exception:               # noqa: BLE001
                    backend = None
            if backend is None:
                try:
                    win.attributes("-transparentcolor", "#010203")
                except tk.TclError:
                    pass
                backend = _ColorKeyBubble(win, "#010203")
            _hide_from_alt_tab(win)
            self._make_click_through(win)
        except Exception:
            try:
                win.destroy()
            except Exception:
                pass
            _log_exception()
            self.failed = True
            return False
        self.win = win
        self.backend = backend
        self.shown = False
        return True

    @staticmethod
    def _make_click_through(win):
        if _user32 is None:
            return
        try:
            hwnd = _hwnd_of(win)
            style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= (WS_EX_LAYERED | WS_EX_TRANSPARENT
                      | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
            _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    # ---------------------------------------------------------- 运行
    def start(self):
        self.clear()
        self.active_until = self.pet.shooting_until
        self.zone_center = self.pet.win_x + self.pet.win_w / 2.0
        self.zone_half = max(170.0, min(240.0, self.pet.win_w * 1.5))
        left, _top, right, _bottom = work_area(self.pet.root)
        self.zone_left = max(left + 30, self.zone_center - self.zone_half)
        self.zone_right = min(right - 30, self.zone_center + self.zone_half)
        self.rect = self._make_rect()
        now = self.pet._now()
        self.last_bullet = now
        for i in range(self.MAX_PLANES):
            self._spawn_plane(i == 0)

    def _spawn_plane(self, near_pet=False):
        rect = self.rect or self._make_rect()
        x0, y0, w, h = rect
        pet = self.pet
        colors = ((235, 96, 96), (84, 156, 235), (245, 196, 72),
                  (156, 124, 235), (96, 200, 170))
        color = random.choice(colors)
        size = random.randint(max(58, int(w * 0.035)),
                              max(78, int(w * 0.060)))
        direction = 1 if random.random() < 0.5 else -1
        center_x = self.zone_center or (pet.win_x + pet.win_w / 2.0)
        zl = self.zone_left or (center_x - (self.zone_half or 300))
        zr = self.zone_right or (center_x + (self.zone_half or 300))
        if near_pet:
            x = center_x + random.uniform(-90, 90)
        else:
            x = random.uniform(zl, zr)
        direction = 1 if x < center_x else -1
        img = self._make_plane(color, direction, size)
        x = max(zl, min(zr, x))
        y = random.uniform(y0 + 70, y0 + min(240, h * 0.30))
        vx = direction * random.uniform(38, 82)
        self.planes.append(_Plane(img, x, y, vx,
                                  random.uniform(0, math.tau)))

    def lock_x(self, pet_x):
        """当前锁定哪架飞机（返回它的屏幕 x）；没有飞机就返回 None。"""
        live = [p for p in self.planes if not p.dead]
        if not live:
            return None
        return min(live, key=lambda p: abs(p.x - pet_x)).x

    def _spawn_bullet(self, pet):
        mx, my = pet.muzzle_pos()
        target = self.lock_x(mx)
        vx = 0.0 if target is None else max(-110.0, min(110.0,
                                                         (target - mx) * 1.1))
        self.bullets.append(_Bullet(
            mx + random.uniform(-5, 5), my, vx,
            random.uniform(-1120, -900)))
        pet.on_shot()
        self.booms.append(_Boom(mx, my, 0.15, 22, "flash"))

    def active(self):
        return bool(self.planes or self.bullets or self.booms)

    def update(self, dt, now, pet):
        if not self.rect:
            self.rect = self._make_rect()
        if self.active_until and now > self.active_until + 2.0:
            # 打飞机结束后最多再让飞机飞两秒，然后收干净
            self.clear()
            return
        x0, y0, w, h = self.rect
        if (now < self.active_until - 0.12
                and now - self.last_bullet >= self.BULLET_INTERVAL):
            self._spawn_bullet(pet)
            self.last_bullet = now

        # 飞机只在宠物上方的窄区域里飞，超出就从另一边回来
        zone_l = self.zone_left or (self.zone_center - self.zone_half)
        zone_r = self.zone_right or (self.zone_center + self.zone_half)
        for p in self.planes:
            p.x += p.vx * dt
            p.y += math.sin(now * 1.7 + p.phase) * 10.0 * dt
            if p.x < zone_l - p.w and p.vx < 0:
                p.x = zone_r + p.w
                p.y = random.uniform(y0 + 70, y0 + min(240, h * 0.30))
            elif p.x > zone_r + p.w and p.vx > 0:
                p.x = zone_l - p.w
                p.y = random.uniform(y0 + 70, y0 + min(240, h * 0.30))
        if (now < self.active_until
                and len([p for p in self.planes if not p.dead]) < 3):
            self._spawn_plane(False)

        for b in self.bullets:
            b.age += dt
            b.x += b.vx * dt
            b.y += b.vy * dt
        live = []
        for b in self.bullets:
            if b.age >= b.life or b.y < y0 - 30:
                continue
            hit = False
            for p in self.planes:
                if p.dead:
                    continue
                if (abs(b.x - p.x) < p.w * 0.44
                        and abs(b.y - p.y) < p.h * 0.52):
                    p.dead = True
                    hit = True
                    self.booms.append(_Boom(
                        p.x, p.y, 0.55, max(26, p.w * 0.85), "boom"))
                    self.booms.append(_Boom(
                        p.x, p.y, 0.16, max(20, p.w * 0.55), "flash"))
                    break
            if not hit:
                live.append(b)
        self.bullets = live
        self.planes = [p for p in self.planes if not p.dead]

        booms = []
        for b in self.booms:
            b.age += dt
            if b.age < b.life:
                booms.append(b)
        self.booms = booms

        if not self.active() and now > self.active_until:
            self.hide()
            return
        if not self._ensure_win():
            return
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        for p in self.planes:
            canvas.alpha_composite(
                p.img, (int(round(p.x - p.w / 2.0 - x0)),
                        int(round(p.y - p.h / 2.0 - y0))))
        for b in self.bullets:
            canvas.alpha_composite(
                self._bullet_img,
                (int(round(b.x - 6 - x0)), int(round(b.y - 28 - y0))))
        d = ImageDraw.Draw(canvas)
        for b in self.booms:
            progress = min(1.0, b.age / b.life)
            alpha = max(0, int(255 * (1.0 - progress)))
            bx, by = b.x - x0, b.y - y0
            if b.kind == "flash":
                r = max(4, int(b.size * (0.4 + 0.6 * progress)))
                d.ellipse([bx - r, by - r, bx + r, by + r],
                          fill=(255, 245, 180, alpha))
                continue
            r = max(6, int(b.size * (0.25 + 0.95 * progress)))
            d.ellipse([bx - r, by - r, bx + r, by + r],
                      outline=(255, 226, 140, alpha),
                      width=max(2, int(6 * (1.0 - progress))))
            r2 = max(3, int(r * 0.62))
            d.ellipse([bx - r2, by - r2, bx + r2, by + r2],
                      outline=(255, 120, 60, alpha), width=2)
            d.ellipse([bx - r * 0.3, by - r * 0.3,
                       bx + r * 0.3, by + r * 0.3],
                      fill=(255, 250, 210, alpha // 2))
        if not self.shown:
            try:
                self.win.deiconify()
                self.win.lift()
                self._make_click_through(self.win)
            except tk.TclError:
                return
            self.shown = True
        if isinstance(self.backend, LayeredWindow):
            self.backend.show(canvas, x0, y0)
        else:
            try:
                self.win.geometry("%dx%d+%d+%d" % (w, h, x0, y0))
            except tk.TclError:
                return
            self.backend.show(canvas, x0, y0)

    def hide(self):
        if self.shown and self.win is not None:
            try:
                if self.win.winfo_exists():
                    self.win.withdraw()
            except tk.TclError:
                pass
        self.shown = False
        self.rect = None

    def clear(self):
        self.planes = []
        self.bullets = []
        self.booms = []
        self.active_until = 0.0
        self.hide()

    def destroy(self):
        self.clear()
        if self.win is not None:
            try:
                if self.win.winfo_exists():
                    self.win.destroy()
            except tk.TclError:
                pass
        self.win = None
        self.backend = None


# =====================================================================
# 对话输入框
# =====================================================================
WM_IME_SETCONTEXT = 0x0281
WM_IME_STARTCOMPOSITION = 0x010D
WM_CANCELMODE = 0x001F
VK_ESCAPE = 0x1B
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
SW_HIDE = 0
SMTO_ABORTIFHUNG = 0x0002
IME_FIX_TOTAL_MS = 5000      # 抢键盘焦点最多盯这么久（看结果重试）
IME_FIX_STEP_MS = 150        # 每两次之间隔多久
# WM_IME_SETCONTEXT 的 lParam：告诉输入法"这些 UI 你尽管画"。传 0 等于说
# "一个都别画"，拼音的候选框就是这么被关掉的。
ISC_SHOWUICOMPOSITIONWINDOW = 0x80000000
ISC_SHOWUIALLCANDIDATEWINDOW = 0x0000000F
IME_SHOW_UI = ISC_SHOWUICOMPOSITIONWINDOW | ISC_SHOWUIALLCANDIDATEWINDOW
IACE_DEFAULT = 0x0010
NI_COMPOSITIONSTR = 0x0015
CPS_CANCEL = 0x0001

try:
    _imm32 = ctypes.windll.imm32
    # 同样要声明：ImmGetContext 返回的是 HIMC（指针），不声明会被截断成
    # 32 位再传回 imm32 —— 拿坏指针去 ImmSetOpenStatus/ImmNotifyIME 是能
    # 直接把进程搞崩的
    _imm32.ImmGetContext.restype = ctypes.c_void_p
    _imm32.ImmGetContext.argtypes = [wintypes.HWND]
    _imm32.ImmReleaseContext.restype = wintypes.BOOL
    _imm32.ImmReleaseContext.argtypes = [wintypes.HWND, ctypes.c_void_p]
    _imm32.ImmAssociateContextEx.restype = wintypes.BOOL
    _imm32.ImmAssociateContextEx.argtypes = [wintypes.HWND, ctypes.c_void_p,
                                             wintypes.DWORD]
    _imm32.ImmSetOpenStatus.restype = wintypes.BOOL
    _imm32.ImmSetOpenStatus.argtypes = [ctypes.c_void_p, wintypes.BOOL]
    _imm32.ImmGetOpenStatus.restype = wintypes.BOOL
    _imm32.ImmGetOpenStatus.argtypes = [ctypes.c_void_p]
    _imm32.ImmNotifyIME.restype = wintypes.BOOL
    _imm32.ImmNotifyIME.argtypes = [ctypes.c_void_p, wintypes.DWORD,
                                    wintypes.DWORD, wintypes.DWORD]
except Exception:                        # pragma: no cover - 非 Windows
    _imm32 = None


def _associate_ime(hwnd):
    """让输入法重新关联到这个窗口，并把它打开。

    这就是"输入法得刷新一次才能用"缺的那一步：窗口虽然拿到了焦点，但 TSF
    型输入法还没把窗口当成当前输入目标，打拼音只会看到字母（或什么都不弹）。
    用户手动点一下/切一下窗口时 Windows 帮我们做了这件事，所以看着像"刷新
    一次就好"。这里主动做掉。
    """
    if _imm32 is None or not hwnd:
        return False
    ok = False
    try:
        # 让窗口用默认 IME 上下文（Windows 激活窗口时自己也会做这一步）
        _imm32.ImmAssociateContextEx(hwnd, None, IACE_DEFAULT)
        ctx = _imm32.ImmGetContext(hwnd)
        if ctx:
            try:
                _imm32.ImmSetOpenStatus(ctx, True)
                ok = True
            finally:
                _imm32.ImmReleaseContext(hwnd, ctx)
    except Exception:
        return False
    return ok


def _cancel_ime_composition(hwnd):
    """关窗前把没上屏的拼音组字取消掉。

    正在组字的时候销毁窗口，输入法那边可能还在等这个窗口的响应，卡住的就是
    我们的界面（"点确定卡死"）。
    """
    if _imm32 is None or not hwnd:
        return
    try:
        ctx = _imm32.ImmGetContext(hwnd)
        if ctx:
            try:
                _imm32.ImmNotifyIME(ctx, NI_COMPOSITIONSTR, CPS_CANCEL, 0)
            finally:
                _imm32.ImmReleaseContext(hwnd, ctx)
    except Exception:
        pass


def has_chinese_ime():
    """系统里有没有中文输入法（用来决定提示文案）。"""
    if _user32 is None:
        return False
    try:
        n = _user32.GetKeyboardLayoutList(0, None)
        if not n:
            return False
        buf = (wintypes.HKL * n)()
        _user32.GetKeyboardLayoutList(n, buf)
        return any((h & 0xFFFF) in (0x0804, 0x0404, 0x0C04, 0x1004) for h in buf)
    except Exception:
        return False


def force_foreground(hwnd, focus_hwnd=None, allow_attach=False):
    """把窗口真正提成"前台 + 活动窗口"，并把键盘焦点给到 focus_hwnd。

    实测坑（用户反馈的"中文必须刷新一次"就是这个）：
      * 只 SetForegroundWindow 不够，还要 SetActiveWindow —— 一个线程的
        **活动窗口**可能还停在别的地方（比如刚关掉的右键菜单、宠物主窗口），
        这时 SetFocus 会**静默失败**，按键（包括输入法的组字）就全跑到那个
        窗口上去了，表现就是"打不出中文，点一下对话框才行"（点一下就是让
        Windows 自己做了一次 SetActiveWindow）。
      * 前台锁定会拒绝后台进程抢焦点，所以按"代价从小到大"依次试：
        1. SetForegroundWindow + SetActiveWindow + SetFocus
        2. 模拟一次 ALT 键（Windows 认可的"用户手势"，会临时放开前台锁定）
        3. allow_attach 时才 AttachThreadInput 到当前前台线程再试一次
           （挂别人输入队列是阻塞操作，默认不做）
    """
    if _user32 is None:
        return False
    try:
        if _user32.GetForegroundWindow() == hwnd and not focus_hwnd:
            return True

        def _set():
            _user32.SetForegroundWindow(hwnd)
            # 关键的一步：把**我们线程的活动窗口**也设为它，否则 SetFocus 会失败
            _user32.SetActiveWindow(hwnd)
            if focus_hwnd:
                _user32.SetFocus(focus_hwnd)
            return _user32.GetForegroundWindow() == hwnd

        if _set():
            return True

        # ALT 手势（只按下/抬起虚拟键，不真的破坏用户输入）
        VK_MENU, KEYEVENTF_KEYUP = 0x12, 0x0002
        _user32.keybd_event(VK_MENU, 0, 0, 0)
        _user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        if _set():
            return True

        # 再试一次更容易被系统接受的 API（未公开但业界常用）：
        # 前台被别的进程/菜单占着时，它往往还能把窗口提到前台
        try:
            _user32.SwitchToThisWindow(hwnd, True)
            if focus_hwnd:
                _user32.SetFocus(focus_hwnd)
            if _user32.GetForegroundWindow() == hwnd:
                return True
        except Exception:                   # noqa: BLE001
            pass

        if not allow_attach:
            return False

        fg = _user32.GetForegroundWindow()
        my_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        fg_thread = _user32.GetWindowThreadProcessId(fg, None) if fg else 0
        attached = False
        if fg_thread and fg_thread != my_thread:
            attached = bool(_user32.AttachThreadInput(my_thread, fg_thread, True))
        try:
            if _set():
                return True
        finally:
            if attached:
                _user32.AttachThreadInput(my_thread, fg_thread, False)
        return False
    except Exception:
        return False


class ChatDialog:
    """对话窗口：红白色系 + 校徽 + 对话记录 + 三个候选回复 + 好感度。

    * 聊天模式（默认）：窗口常驻。发一句就出现在上面的记录里；宠物回复后
      下面自动列出三个 AI 生成的"你可以这样回"选项（点一下直接发出去），
      同时**保留原来的输入框**，想自己打字也行。
    * 一次性模式（one_shot=True，设置 API Key 时用）：发送/取消即关窗，
      `ask()` 返回输入内容。

    实测坑：
    * overrideredirect 的窗口在 Windows 上有时收不到输入法（IME）的组字窗口，
      中文打不进去。所以这里不用 overrideredirect，改成普通边框窗口——
      它才能正常挂上 IME、正常拿焦点。
    * tkinter 的 wm_overrideredirect() 会把命令返回值当布尔解析，而 wm 自己
      不写结果，脏结果就会让它抛 TclError；这里一律走 set_overrideredirect()。
    * 输入法"要刷新一次"：菜单的模态状态或别的进程占着前台时 SetFocus 会静默
      失败，按键就送给了菜单/任务栏。见 _grab_ime_focus / _arm_ime_fix。
    """

    W, H = 520, 456
    ONESHOT_W, ONESHOT_H = 460, 186
    BTN_W, BTN_H = 96, 34
    GAP = 12
    OPTION_ROW_H = 60
    INPUT_ROW_H = 56
    LOGO_SIZE = 44
    # 好感度满 100 时插在选项第一位的那颗按钮（点它 = 触发恋爱）
    ROMANCE_OPTION = "♡ 恋爱"
    # 红白色系
    BG = "#fffdfd"
    CARD = "#ffffff"
    RED = "#b3242a"
    RED_DARK = "#8a1a1f"
    RED_LIGHT = "#f6dfe0"
    INK = "#332a2c"
    MUTED = "#9b8d8f"

    def __init__(self, pet, title="跟桌宠说句话", hint="Enter 发送 · Esc 取消",
                 secret=False, width=None, one_shot=False,
                 show_log=True, show_options=True, show_affection=True):
        self.pet = pet
        self.title = title
        self.secret = secret
        self.one_shot = one_shot
        self.show_log = show_log and not one_shot
        self.show_options = show_options and not one_shot
        self.show_affection = show_affection and not one_shot
        # 有中文输入法的机器上，多提一句：打不出中文可以粘贴
        if hint and not secret and has_chinese_ime():
            hint = "%s · 打不出中文就 Ctrl+V 粘贴" % hint
        self.hint = hint
        self.W = width or (self.ONESHOT_W if one_shot else self.W)
        self.H = self.ONESHOT_H if one_shot else self.H
        self.win = None
        self.entry = None
        self.hint_label = None
        self.log = None
        self.option_buttons = []
        self.affection_canvas = None
        self.affection_var = None
        self.result = None
        self._photo_logo = None
        self._options = []
        self._ai_options = []       # 上一次 AI 给的候选回复（不含恋爱选项）
        self._options_visible = False
        self._frame = None          # 标题栏+边框占的像素（懒测一次）
        self._jobs = []             # 抢前台用的定时器，关窗时要取消掉

    # ---------------------------------------------------------------- 生命周期
    def show(self):
        """建窗并显示（聊天模式不阻塞）。"""
        if self.win is not None and self.win.winfo_exists():
            self.win.deiconify()
            self.win.lift()
            self._arm_ime_fix()
            return self
        root = self.pet.root
        self.win = tk.Toplevel(root)
        self.win.title(self.title)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=self.BG)
        self.win.resizable(False, False)
        # 先把宠物那边的右键菜单彻底收掉（取消弹出 + 释放 grab）。菜单的模态
        # 状态优先级很高，不清掉的话键盘输入会被判给菜单，中文输入法要"点一下
        # 刷新"才行 —— 这就是用户反馈的那条。
        self.pet._drop_menu()
        self.win.geometry("%dx%d" % (self.W, self.H))
        try:
            # 直接调 Tcl：tkinter 的 minsize() 也会解析返回值，脏结果会抛
            self.win.tk.call("wm", "minsize", str(self.win), self.W, self.H)
            self.win.tk.call("wm", "maxsize", str(self.win), self.W, self.H)
        except tk.TclError:
            pass

        self._build_header()
        if self.show_log:
            self._build_log()
        if self.show_options:
            self._build_options()
            self._render_options()          # 好感度已满的话，恋爱选项一开窗就在
        self._build_input()

        self.win.bind("<Return>", self._on_return)
        self.win.bind("<KP_Enter>", self._on_return)
        self.win.bind("<Escape>", lambda e: self.cancel())
        self.win.protocol("WM_DELETE_WINDOW", self.cancel)
        # 输入法要"前台窗口"才收得到按键：<FocusIn> 只在焦点"变化"时来，
        # 点已经聚焦的输入框不会再触发，所以点在窗口/输入框上的点击也补一次
        self.win.bind("<FocusIn>", lambda e: self._grab_ime_focus(), add="+")
        self.win.bind("<Button-1>", lambda e: self._grab_ime_focus(), add="+")
        self.entry.bind("<Button-1>", lambda e: self._grab_ime_focus(), add="+")

        self._seed_log()
        self._place()
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()
        self._focus_entry()
        # 抢前台/焦点/输入法：盯到系统确认输入框真的拿到键盘焦点为止
        self._jobs.append(self.win.after(0, self._arm_ime_fix))
        if self.one_shot:
            try:
                self.win.grab_set()         # 一次性输入：别让点击跑到别处
            except tk.TclError:
                pass
        if not self.one_shot:
            self.pet.chat_win = self
        return self

    def ask(self):
        """显示并等到窗口关闭（一次性模式返回输入内容；工具/自检也用它）。"""
        self.show()
        if self.win is not None and self.win.winfo_exists():
            with self.pet._modal():
                self.pet.root.wait_window(self.win)
        return self.result

    # ---------------------------------------------------------------- 界面
    def _logo_image(self):
        """校徽（assets/school_logo.png，由 tools/make_logo.py 生成，圆形透明）。"""
        path = _asset_path("school_logo.png")
        if not os.path.exists(path):
            return None
        try:
            img = Image.open(path).convert("RGBA")
            img = img.resize((self.LOGO_SIZE, self.LOGO_SIZE), Image.LANCZOS)
            return ImageTk.PhotoImage(img, master=self.win)
        except Exception:                   # noqa: BLE001
            return None

    def _build_header(self):
        band_h = 64 if not self.one_shot else 60
        head = tk.Frame(self.win, bg=self.BG)
        head.place(x=0, y=0, width=self.W, height=band_h)
        self._photo_logo = self._logo_image()
        if self._photo_logo is not None:
            tk.Label(head, image=self._photo_logo, bg=self.BG, bd=0).place(
                x=14, y=(band_h - self.LOGO_SIZE) // 2)
            text_x = 14 + self.LOGO_SIZE + 12
        else:
            text_x = 16
        tk.Label(head, text=self.title, bg=self.BG, fg=self.RED_DARK,
                 font=(FONT_FAMILY, 13, "bold"), anchor="w").place(
            x=text_x, y=10, height=26)
        subtitle = (self.hint if self.one_shot
                    else "发一句话；下面会给三个可回的选项")
        # 副标题要按好感度盒子让出位置，不然会顶到"好感度"下面被压住
        sub_w = (self.W - text_x - 14 - (190 if self.show_affection else 0))
        tk.Label(head, text=subtitle, bg=self.BG, fg=self.MUTED,
                 font=(FONT_FAMILY, 9), anchor="w").place(
            x=text_x, y=36, width=max(80, sub_w), height=18)
        if self.show_affection:
            self._build_affection(head, band_h)
        tk.Frame(self.win, bg=self.RED, height=2).place(
            x=0, y=band_h, width=self.W, height=2)

    def _build_affection(self, parent, band_h):
        box_w = 176
        x0 = self.W - box_w - 14
        tk.Label(parent, text="好感度", bg=self.BG, fg=self.RED,
                 font=(FONT_FAMILY, 9), anchor="e").place(
            x=x0, y=10, width=52, height=18)
        self.affection_var = tk.StringVar(value=str(self.pet.affection))
        tk.Label(parent, textvariable=self.affection_var, bg=self.BG,
                 fg=self.RED_DARK, font=(FONT_FAMILY, 10, "bold"), anchor="e").place(
            x=x0 + 52, y=8, width=44, height=20)
        tk.Label(parent, text="♥", bg=self.BG, fg=self.RED,
                 font=(FONT_FAMILY, 11), anchor="w").place(
            x=x0 + 96, y=8, width=26, height=20)
        # 这一轮好感度变了多少（+2 / -2 / 已满），1.6 秒后自己消失
        self.aff_delta_var = tk.StringVar(value="")
        self._aff_delta_label = tk.Label(
            parent, textvariable=self.aff_delta_var, bg=self.BG,
            fg=self.RED_DARK, font=(FONT_FAMILY, 8), anchor="w")
        self._aff_delta_label.place(x=x0 + 120, y=10, width=52, height=16)
        self.affection_canvas = tk.Canvas(parent, width=box_w - 60, height=12,
                                          bg=self.RED_LIGHT, highlightthickness=1,
                                          highlightbackground=self.RED, bd=0)
        self.affection_canvas.place(x=x0 + 4, y=band_h - 26)
        self.set_affection(self.pet.affection)

    def _draw_affection(self, value):
        c = self.affection_canvas
        if c is None:
            return
        try:
            c.delete("all")
            width = int(float(c.cget("width")))
            height = int(float(c.cget("height")))
            filled = max(0, min(width, int(round(width * value / 100.0))))
            if filled > 0:
                c.create_rectangle(1, 1, filled, height - 1, fill=self.RED, width=0)
        except tk.TclError:
            pass

    def set_affection(self, value, delta=0):
        """更新好感度显示（0-100）；delta 非 0 时在旁边闪一下变化量。

        满 100 还往上加是加不动的 —— 这时候显示「已满」，省得看着像没变化。
        """
        try:
            value = max(0, min(100, int(value)))
        except (TypeError, ValueError):
            return
        if self.affection_var is not None:
            try:
                self.affection_var.set(str(value))
            except tk.TclError:
                return
        self._draw_affection(value)
        self._flash_delta(value, delta)

    def _flash_delta(self, value, delta):
        """在好感度旁边闪一下 +2 / -2 / 已满，1.6 秒后清掉。"""
        var = getattr(self, "aff_delta_var", None)
        if var is None:
            return
        try:
            delta = int(delta)
        except (TypeError, ValueError):
            delta = 0
        if not delta:
            text, color = "", self.RED_DARK
        elif value >= 100 and delta > 0:
            text, color = "已满", self.RED
        elif delta > 0:
            text, color = "+%d" % delta, self.RED_DARK
        else:
            text, color = str(delta), "#8a8a8a"
        try:
            var.set(text)
            label = getattr(self, "_aff_delta_label", None)
            if label is not None:
                label.configure(fg=color)
        except tk.TclError:
            return
        if text:
            try:
                self.win.after(1600, self._clear_delta)
            except tk.TclError:
                pass

    def _clear_delta(self):
        var = getattr(self, "aff_delta_var", None)
        if var is not None:
            try:
                var.set("")
            except tk.TclError:
                pass

    def switch_persona(self, persona, affection):
        """形象（人设）换了：标题跟着变，记录清掉重画。"""
        try:
            if self.win is not None and self.win.winfo_exists():
                self.win.title("跟%s说句话" % ai_client.persona_display_name(persona))
        except tk.TclError:
            pass
        if self.log is not None:
            try:
                self.log.configure(state="normal")
                self.log.delete("1.0", "end")
                self.log.configure(state="disabled")
            except tk.TclError:
                pass
            self._seed_log()
        self._hide_options()
        self.set_affection(affection)

    def _build_log(self):
        log_top = 76
        log_h = max(60, self.H - log_top - self.OPTION_ROW_H - self.INPUT_ROW_H - 10)
        wrap = tk.Frame(self.win, bg=self.RED, bd=0)
        wrap.place(x=14, y=log_top, width=self.W - 28, height=log_h)
        self.log = tk.Text(wrap, wrap="word", bd=0, highlightthickness=0,
                           bg=self.CARD, fg=self.INK, font=(FONT_FAMILY, 10),
                           padx=10, pady=8, spacing1=2, spacing3=4,
                           cursor="arrow", state="disabled")
        bar = tk.Scrollbar(wrap, command=self.log.yview, width=10)
        self.log.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.log.tag_configure("me", foreground=self.RED_DARK, justify="right",
                               font=(FONT_FAMILY, 10))
        self.log.tag_configure("pet", foreground=self.INK, justify="left",
                               font=(FONT_FAMILY, 10))
        self.log.tag_configure("name", foreground=self.MUTED,
                               font=(FONT_FAMILY, 8))
        # 旁白/小动作：灰色居中，不跟对话混在一起
        self.log.tag_configure("note", foreground=self.MUTED, justify="center",
                               font=(FONT_FAMILY, 8), spacing1=2, spacing3=4)

    def _build_options(self):
        row_y = self.H - self.OPTION_ROW_H - self.INPUT_ROW_H - 4
        self.options_label = tk.Label(self.win, text="你可以这样回：",
                                      bg=self.BG, fg=self.MUTED,
                                      font=(FONT_FAMILY, 9), anchor="w")
        self.options_label.place(x=14, y=row_y - 16, width=self.W - 28,
                                 height=16)
        self._opt_geom = []
        btn_w = (self.W - 28 - 2 * 8) // 3
        for i in range(3):
            btn = tk.Button(self.win, text="", relief="solid", bd=1,
                            font=(FONT_FAMILY, 9), cursor="hand2",
                            bg=self.CARD, fg=self.RED_DARK,
                            activebackground=self.RED_LIGHT,
                            activeforeground=self.RED_DARK,
                            wraplength=btn_w - 16, justify="left", anchor="w",
                            padx=6, state="disabled",
                            command=lambda idx=i: self._use_option(idx))
            geo = (14 + i * (btn_w + 8), row_y, btn_w,
                   self.OPTION_ROW_H - 10)
            self._opt_geom.append(geo)
            btn.place(x=geo[0], y=geo[1], width=geo[2], height=geo[3])
            self.option_buttons.append(btn)

    def _build_input(self):
        row_y = self.H - self.INPUT_ROW_H + 6
        entry_w = self.W - 28 - 2 * self.BTN_W - 2 * self.GAP
        self.entry = tk.Entry(self.win, font=(FONT_FAMILY, 12), relief="solid",
                              bd=1, bg=self.CARD, fg=self.INK,
                              highlightthickness=1, highlightbackground=self.RED,
                              highlightcolor=self.RED,
                              insertbackground=self.RED, insertwidth=2)
        if self.secret:
            self.entry.configure(show="●")
        self.entry.place(x=14, y=row_y, width=entry_w, height=self.BTN_H)
        close_text = "取消" if self.one_shot else "关闭"
        tk.Button(self.win, text=close_text, command=self.cancel, relief="solid",
                  bd=1, font=(FONT_FAMILY, 10), cursor="hand2", bg=self.CARD,
                  fg=self.RED_DARK, activebackground=self.RED_LIGHT,
                  activeforeground=self.RED_DARK).place(
            x=14 + entry_w + self.GAP, y=row_y, width=self.BTN_W, height=self.BTN_H)
        tk.Button(self.win, text="发送", command=self.submit, relief="flat", bd=0,
                  font=(FONT_FAMILY, 10, "bold"), cursor="hand2", bg=self.RED,
                  fg="#ffffff", activebackground=self.RED_DARK,
                  activeforeground="#ffffff").place(
            x=14 + entry_w + self.GAP + self.BTN_W + self.GAP, y=row_y,
            width=self.BTN_W, height=self.BTN_H)
        self.hint_label = tk.Label(self.win, text=self.hint, bg=self.BG,
                                   fg=self.MUTED, font=(FONT_FAMILY, 8), anchor="w")
        self.hint_label.place(x=14, y=self.H - 16, width=self.W - 28, height=14)

    # ---------------------------------------------------------------- 内容
    def _seed_log(self):
        """打开时把已有的记忆画进记录里。"""
        if not self.show_log or self.log is None:
            return
        for msg in getattr(self.pet.brain, "history", [])[-8:]:
            role = msg.get("role")
            text = str(msg.get("content") or "")
            if not text:
                continue
            self._append(
                text if role == "user" else jp_gloss.add_gloss(text),
                "me" if role == "user" else "pet")

    def _append(self, text, tag):
        if self.log is None:
            return
        try:
            self.log.configure(state="normal")
            self.log.insert("end", ("你：" if tag == "me" else "宠物：") + str(text) + "\n",
                            (tag, "name"))
            self.log.configure(state="disabled")
            self.log.see("end")
        except tk.TclError:
            pass

    def add_user(self, text):
        self._append(text, "me")
        self._hide_options()

    def add_reply(self, text, options=None):
        # 日语的下一行补中文（郑迪隆的骚话玩家不一定看得懂）
        self._append(jp_gloss.add_gloss(text), "pet")
        self._had_reply = True
        self.set_options(options or [])

    def add_note(self, text):
        """灰色的一行小字：撤回、手滑点赞这种只看得见的动作。"""
        if self.log is None:
            return
        try:
            self.log.configure(state="normal")
            self.log.insert("end", str(text) + "\n", ("note",))
            self.log.configure(state="disabled")
            self.log.see("end")
        except tk.TclError:
            pass

    def withdraw_last(self, delay_ms=2600):
        """冷战的小动作：先把刚发出去的那句删掉，再补一行"撤回了一条消息"。"""
        if self.log is None:
            return

        def do():
            try:
                idx = int(self.log.index("end-1c").split(".")[0])
                while idx > 1 and not self.log.get("%d.0" % idx,
                                                   "%d.end" % idx).strip():
                    idx -= 1
                if idx < 1:
                    return
                line = self.log.get("%d.0" % idx, "%d.end" % idx)
                if not str(line).startswith("宠物："):
                    return
                self.log.configure(state="normal")
                self.log.delete("%d.0" % idx, "%d.0+1l" % idx)
                self.log.configure(state="disabled")
            except (tk.TclError, ValueError):
                return
            self.add_note("（它撤回了一条消息）")

        try:
            self.win.after(max(0, int(delay_ms)), do)
        except tk.TclError:
            pass

    def set_options(self, options):
        """把 AI 给的候选回复放上去（好感度满时第一位插「♡ 恋爱」）。"""
        if not self.show_options:
            return
        self._ai_options = [str(o) for o in (options or [])][:3]
        self._render_options()

    def refresh_romance(self):
        """好感度/人设变了：恋爱选项该出现就出现、该消失就消失。"""
        self._render_options()

    def _romance_ready(self):
        """现在能不能点「♡ 恋爱」（人设支持 + 好感度满 + 还没在一起）。"""
        try:
            return bool(self.pet.romance_available())
        except Exception:                       # noqa: BLE001
            return False

    def _render_options(self):
        """按"恋爱选项 + AI 候选回复"重画三个按钮（没恋爱就全是 AI 的）。"""
        if not self.show_options:
            return
        opts = [self.ROMANCE_OPTION] if self._romance_ready() else []
        opts.extend(self._ai_options)
        self._options = opts[:3]
        self._options_visible = any(self._options)
        if not self._options:
            # 一条 AI 选项都没拿到（接口连挂 / 两次都没解析出来）：不再拿兜底池
            # 凑三句空话，把按钮收起来，提示自己说一句。
            try:
                self.options_label.configure(
                    text="想不出来就自己说一句吧"
                    if getattr(self, "_had_reply", False)
                    else "先跟它说一句话")
                for btn in self.option_buttons:
                    btn.configure(text="", state="disabled")
                    btn.place_forget()
            except tk.TclError:
                pass
            return
        try:
            self.options_label.configure(text="你可以这样回：")
        except tk.TclError:
            return
        for i, btn in enumerate(self.option_buttons):
            text = self._options[i] if i < len(self._options) else ""
            romance = bool(text) and text == self.ROMANCE_OPTION
            try:
                btn.configure(text=text, state="normal" if text else "disabled",
                              bg=self.RED if romance else self.CARD,
                              fg="#ffffff" if romance else self.RED_DARK,
                              activebackground=(self.RED_DARK if romance
                                                else self.RED_LIGHT),
                              activeforeground=("#ffffff" if romance
                                                else self.RED_DARK))
                # 没有内容的格子直接收起来：否则界面上会留下几个空白按钮框
                if text:
                    if not btn.winfo_ismapped():
                        x, y, w, h = self._opt_geom[i]
                        btn.place(x=x, y=y, width=w, height=h)
                else:
                    btn.place_forget()
            except tk.TclError:
                return

    def _hide_options(self):
        self._ai_options = []
        self._render_options()

    def _use_option(self, index):
        """点了某个候选回复：恋爱选项触发告白，其余就当用户说了这句。"""
        if index >= len(self._options):
            return
        text = self._options[index]
        if text == self.ROMANCE_OPTION:
            self.pet.trigger_romance()
            return
        self._send(text)

    # ---------------------------------------------------------------- 发送
    def _send(self, text):
        text = (text or "").strip()
        if not text:
            return False
        if self.one_shot:
            self.result = text
            self._close()
            return True
        self.add_user(text)
        try:
            self.entry.delete(0, "end")
        except tk.TclError:
            pass
        self.pet.ask_ai(text)
        return True

    def submit(self):
        text = self.entry.get().strip() if self.entry else ""
        if not text:
            # 空内容不关窗：输入法正在组字时按回车，这一下可能只被输入法吃掉了
            self._show_ime_hint("先按空格/回车把拼音选成字，再按发送")
            return False
        return self._send(text)

    def cancel(self):
        if self.one_shot:
            self.result = None
        self._close()

    # ---------------------------------------------------------------- IME
    def _focus_entry(self):
        """把键盘焦点放到输入框上。

        实测坑：只调 win.focus_force() 的话，焦点是落在**对话框**上的
        （GetGUIThreadInfo 显示 hwndFocus == dialog），按键进不到 Entry，
        输入法自然也组不了字。必须对 Entry 自己 focus_force()。
        """
        if self.entry is None:
            return
        try:
            self.entry.focus_force()
        except tk.TclError:
            pass

    def _grab_ime_focus(self, allow_attach=False, sync_timeout=300):
        """把对话框变成"前台 + 活动窗口"，焦点给输入框，并把输入法挂上去。

        用户反馈"中文必须点一下才能打"的完整原因：
          1. 右键菜单关掉之后，**我们线程的活动窗口还是那个菜单**（实测
             GetGUIThreadInfo 里 hwndActive/hwndFocus 都还是菜单）。这时调用
             SetFocus(输入框) 会**静默失败**，按键全给菜单吃掉了；
          2. 输入法（搜狗这类 TSF 输入法）还需要窗口的 IME 上下文，并且要收到
             WM_IME_SETCONTEXT（wParam=TRUE 表示"这个窗口是当前输入上下文"）。
        所以这里按 SetForegroundWindow → SetActiveWindow → SetFocus 的顺序做，
        再 ImmAssociateContextEx + ImmSetOpenStatus，最后同步发一次
        WM_IME_SETCONTEXT（用 SendMessageTimeout 限时，既能让输入法立刻切过来，
        又不会像 SendMessage 那样被卡死的输入法拖住界面）。
        """
        if self.win is None or not self.win.winfo_exists():
            return
        try:
            # winfo_id() 给的是 TkChild，真正接收前台激活的是它的顶层父窗口
            child = self.win.winfo_id()
            top = _user32.GetAncestor(child, 2) if _user32 else child  # GA_ROOT
            ent = self.entry.winfo_id() if self.entry else None
            force_foreground(top or child, ent, allow_attach=allow_attach)
            # 抢完前台再确认焦点在 Entry 上：Tk 侧和 Win32 侧都设一遍，
            # 否则焦点会留在对话框上，按键进不到输入框
            self._focus_entry()
            if _user32 is not None and ent:
                # 再把活动窗口钉到对话框（菜单/宠物窗口可能还占着这个位置），
                # 然后把键盘焦点给输入框
                _user32.SetActiveWindow(top or child)
                _user32.SetFocus(ent)
                _associate_ime(ent)
                # 同步（限时）通知输入法：这个窗口是当前输入上下文，组字窗和
                # 候选框都可以画。首次给足 300ms；重试时缩到 50ms，免得输入法
                # 一直不回就把重试循环拖得很慢
                result = ctypes.c_size_t()
                _user32.SendMessageTimeoutW(ent, WM_IME_SETCONTEXT, 1, IME_SHOW_UI,
                                            SMTO_ABORTIFHUNG, sync_timeout,
                                            ctypes.byref(result))
        except tk.TclError:
            pass

    def _entry_has_focus(self):
        """系统眼里键盘焦点是不是真的在输入框上（而不是任务栏/菜单/宠物）。

        只看 Tk 的 focus_get() 不够：前台被别的进程占着时 SetFocus 会静默失败，
        Tk 那边却以为焦点已经在输入框了。这里问 GetGUIThreadInfo。
        """
        if _user32 is None or self.entry is None or self.win is None:
            return True                     # 非 Windows / 窗口没了就不折腾
        try:
            if not self.win.winfo_exists():
                return True
            top = _user32.GetAncestor(self.win.winfo_id(), 2) or self.win.winfo_id()
            if _user32.GetForegroundWindow() != top:
                return False                # 前台还不是我们（任务栏/别的菜单占着）
            tid = _user32.GetWindowThreadProcessId(top, None)
            info = GUITHREADINFO()
            info.cbSize = ctypes.sizeof(GUITHREADINFO)
            if not _user32.GetGUIThreadInfo(tid, ctypes.byref(info)):
                return False
            if info.flags & (GUI_INMENUMODE | GUI_POPUPMENUMODE | GUI_SYSTEMMENUMODE):
                return False                # 还有菜单处于模态
            return info.hwndFocus == self.entry.winfo_id()
        except Exception:                   # noqa: BLE001
            return True

    def _arm_ime_fix(self, left_ms=IME_FIX_TOTAL_MS, attempt=0):
        """反复把焦点/输入法抢过来，直到系统确认输入框真的拿到了焦点。

        别的进程（任务栏、别的程序的菜单）正占着前台时 SetForegroundWindow
        会被拒；固定试几个时间点很容易全部落在它压着的那段时间里，于是用户
        必须手动点一下对话框"刷新"才能打中文。这里改成看结果重试：确认成功
        就停，最多盯 IME_FIX_TOTAL_MS 毫秒，抢不到就在提示行里告诉用户点一下。
        """
        if self.win is None or not self.win.winfo_exists():
            return
        self._grab_ime_focus(allow_attach=(attempt >= 3),
                             sync_timeout=300 if attempt == 0 else 50)
        if self._entry_has_focus():
            self._restore_hint()
            return
        if left_ms <= 0:
            self._show_ime_hint()
            return
        job = self.win.after(
            IME_FIX_STEP_MS,
            lambda: self._arm_ime_fix(left_ms - IME_FIX_STEP_MS, attempt + 1))
        self._jobs.append(job)

    def _show_ime_hint(self, text="键盘焦点被别的程序占着：点一下输入框即可打字"):
        if self.hint_label is None:
            return
        try:
            self.hint_label.configure(text=text)
        except tk.TclError:
            pass

    def _restore_hint(self):
        if self.hint_label is None:
            return
        try:
            if self.hint_label.cget("text") != self.hint:
                self.hint_label.configure(text=self.hint)
        except tk.TclError:
            pass

    def _on_return(self, event):
        if self.submit():
            return "break"
        return None

    def _frame_pad(self):
        """标题栏 + 边框占多少逻辑像素。

        Tk 的 wm geometry 给的是**客户区**大小，窗口外面还有标题栏和边框：
        不算进去，对话框就会压住宠物（实测差 40px，正好盖住它的头）。
        """
        if self._frame is not None:
            return self._frame
        try:
            scale = max(1.0, self.win.winfo_fpixels("1i") / 96.0)
        except tk.TclError:
            scale = 1.0
        caption = frame = pad = 0
        if _user32 is not None:
            caption = _user32.GetSystemMetrics(4)    # SM_CYCAPTION
            frame = _user32.GetSystemMetrics(32)     # SM_CYSIZEFRAME
            pad = _user32.GetSystemMetrics(92)       # SM_CXPADDEDBORDER
        if not frame:
            frame, pad = 4, 1
        if not caption:
            caption = 24
        border = 2 * (frame + pad)
        self._frame = (int(round(border / scale)),
                       int(round((caption + border) / scale)))
        return self._frame

    def _place(self):
        """贴着宠物放：先试上方，放不下就挪到宠物下面，且不盖住宠物。"""
        root = self.pet.root
        left, top, right, bottom = work_area(root)
        ax, ay = self.pet.head_anchor()
        frame_w, frame_h = self._frame_pad()
        x = int(min(max(left + 8, ax - self.W // 2), right - self.W - frame_w))
        # 窗口整体（含标题栏）要在宠物上方：y 是客户区顶边
        y = int(self.pet.win_y - self.H - frame_h - 6)
        if y < top + 8:
            # 宠物贴着屏幕顶（或本身很高）：改放它下面，再放不下就贴顶
            y = int(self.pet.win_y + self.pet.win_h + 6)
            if y + self.H + frame_h > bottom - 8:
                # 上下都塞不下：改放宠物左边/右边。宁可贴屏幕边，也别压住
                # 宠物 —— 宠物被窗口盖住时头顶的气泡会跟着藏起来，正在放的
                # 歌名就看不到了（用户报过这个）。
                room_left = self.pet.win_x - left - 8
                room_right = right - (self.pet.win_x + self.pet.win_w) - 8 - frame_w
                if max(room_left, room_right) >= self.W:
                    y = int(min(max(top + 8, self.pet.win_y),
                                bottom - self.H - frame_h - 8))
                    if room_left >= room_right:
                        x = int(self.pet.win_x - self.W - frame_w - 8)
                    else:
                        x = int(self.pet.win_x + self.pet.win_w + 8)
                    x = int(min(max(left + 8, x), right - self.W - frame_w))
                else:
                    y = max(top + 8, bottom - self.H - frame_h - 8)
        self.win.geometry("%dx%d+%d+%d" % (self.W, self.H, x, y))

    def _close(self):
        # 先把没上屏的拼音取消、再取消抢前台的定时器：正在组字时销毁窗口，
        # 输入法可能还在等这个窗口响应（表现就是"点确定卡死"）；定时器则是
        # 窗口一销毁就变成 "invalid command name"
        if self.entry is not None and _user32 is not None:
            try:
                ent = self.entry.winfo_id()
            except tk.TclError:
                ent = None
            if ent:
                _cancel_ime_composition(ent)
                # 再把输入法和这个窗口解绑：不解绑的话，输入法那边还挂着一个
                # 即将销毁的窗口，之后宠物/气泡窗口一动它就可能踩到野指针
                try:
                    _imm32.ImmAssociateContextEx(ent, None, 0)
                except Exception:            # noqa: BLE001
                    pass
        for job in self._jobs:
            try:
                self.win.after_cancel(job)
            except Exception:
                pass
        self._jobs = []
        if self.win is not None and self.win.winfo_exists():
            try:
                self.win.grab_release()
            except tk.TclError:
                pass
            self.win.destroy()
        self.win = None
        if not self.one_shot:
            self.pet._chat_closed(self)


# =====================================================================
# 修改器
# =====================================================================
MODIFIER_PASSWORD = "csdchm99"


class WebLinkDialog:
    """右键「打开网页 → ＋ 添加网页…」：填个名字和网址，存进配置。"""

    W, H = 390, 272

    def __init__(self, pet):
        self.pet = pet
        self.win = None
        self.name_var = tk.StringVar()
        self.url_var = tk.StringVar(value="https://")
        self.name_entry = None
        self.url_entry = None
        self.hint = None

    def show(self):
        self._build()
        if self.win is None:
            return
        try:
            self.win.grab_set()
        except tk.TclError:
            pass
        with self.pet._modal():
            self.win.wait_window()

    def _build(self):
        pet = self.pet
        win = tk.Toplevel(pet.root)
        self.win = win
        win.title("桌面宠物 · 添加网页")
        win.configure(bg="#fbfaf4")
        win.resizable(False, False)
        try:
            win.attributes("-topmost", True)
            win.transient(pet.root)
        except tk.TclError:
            pass
        x = max(0, min(pet.win_x + pet.win_w // 2 - self.W // 2,
                       win.winfo_screenwidth() - self.W - 8))
        y = max(0, pet.win_y - self.H - 12)
        win.geometry("%dx%d+%d+%d" % (self.W, self.H, x, y))
        win.protocol("WM_DELETE_WINDOW", self._close)
        win.bind("<Escape>", lambda _e: self._close())

        tk.Label(win, text="加一个快捷网页", bg="#fbfaf4", fg="#b32854",
                 font=(FONT_FAMILY, 14, "bold")).pack(anchor="w", padx=18,
                                                      pady=(14, 6))
        for label, var, attr in (("名字（菜单里显示）", self.name_var, "name_entry"),
                                 ("网址", self.url_var, "url_entry")):
            tk.Label(win, text=label, bg="#fbfaf4", fg="#23262e",
                     font=(FONT_FAMILY, 10)).pack(anchor="w", padx=18)
            ent = tk.Entry(win, textvariable=var, font=(FONT_FAMILY, 11),
                           relief="solid", bd=1, bg="#ffffff", fg="#23262e",
                           highlightthickness=1, highlightbackground="#d8a0b4",
                           highlightcolor="#b32854", insertbackground="#b32854")
            ent.pack(fill="x", padx=18, pady=(3, 7), ipady=4)
            ent.bind("<Return>", lambda _e: self._save())
            ent.bind("<Button-1>", lambda _e, w=ent: self._focus(w), add="+")
            setattr(self, attr, ent)

        self.hint = tk.Label(win, text="网址可以只写 www.example.com，会自动补 https://",
                             bg="#fbfaf4", fg="#9a8590", font=(FONT_FAMILY, 8))
        self.hint.pack(anchor="w", padx=18)
        row = tk.Frame(win, bg="#fbfaf4")
        row.pack(fill="x", padx=18, pady=(8, 12))
        tk.Button(row, text="取消", command=self._close, relief="solid", bd=1,
                  bg="#ffffff", fg="#23262e", font=(FONT_FAMILY, 10),
                  cursor="hand2").pack(side="right", ipadx=12, ipady=3)
        tk.Button(row, text="保存", command=self._save, relief="flat", bd=0,
                  bg="#b32854", fg="#ffffff", activebackground="#8f1e42",
                  activeforeground="#ffffff", font=(FONT_FAMILY, 10, "bold"),
                  cursor="hand2").pack(side="right", padx=(0, 8), ipadx=14, ipady=4)
        self._focus(self.name_entry)

    def _focus(self, widget):
        """点/开窗时把前台和输入法一起招呼好（不然中文要再点一下才能打）。"""
        if widget is None:
            return
        try:
            widget.focus_force()
            if _user32 is not None and self.win is not None:
                top = _user32.GetAncestor(self.win.winfo_id(), 2) or self.win.winfo_id()
                ent = widget.winfo_id()
                force_foreground(top, ent)
                _user32.SetFocus(ent)
                try:
                    _associate_ime(ent)
                except Exception:           # noqa: BLE001
                    pass
        except Exception:                   # noqa: BLE001
            pass

    def _save(self):
        if self.pet.add_web_link(self.name_var.get(), self.url_var.get()):
            self._close()
            return
        if self.hint is not None:
            self.hint.configure(text="网址好像不对：写成 www.example.com 或 https://…",
                                fg="#b32854")
        self._focus(self.url_entry)

    def _close(self):
        if self.win is not None and self.win.winfo_exists():
            try:
                self.win.grab_release()
            except tk.TclError:
                pass
            self.win.destroy()
        self.win = None


class ModifierDialog:
    """好感度修改器：先输密码（显示为圆点），解锁后拖/点改好感度。"""

    def __init__(self, pet):
        self.pet = pet
        self.win = None
        self.unlocked = False
        self._ready = False
        self.value_var = None
        self.status = None

    def show(self):
        self._build()
        if self.win is None:
            return
        try:
            self.win.grab_set()
        except tk.TclError:
            pass
        with self.pet._modal():
            self.win.wait_window()

    def _build(self):
        pet = self.pet
        win = tk.Toplevel(pet.root)
        self.win = win
        win.title("桌面宠物 · 修改器")
        win.configure(bg="#fbfaf4")
        win.resizable(False, False)
        try:
            win.attributes("-topmost", True)
            win.transient(pet.root)
        except tk.TclError:
            pass
        w, h = 390, 380
        x = max(0, pet.win_x + pet.win_w // 2 - w // 2)
        y = max(0, pet.win_y + pet.win_h // 2 - h // 2)
        win.geometry("%dx%d+%d+%d" % (w, h, x, y))
        win.protocol("WM_DELETE_WINDOW", self._close)

        tk.Label(win, text="修改器", bg="#fbfaf4", fg="#b32854",
                 font=(FONT_FAMILY, 16, "bold")).pack(anchor="w", padx=20, pady=(16, 2))
        tk.Label(win, text="好感度 / 当前形象：%s"
                 % ai_client.persona_display_name(getattr(pet, "_persona", "")),
                 bg="#fbfaf4", fg="#6b5560",
                 font=(FONT_FAMILY, 9)).pack(anchor="w", padx=20)

        self.pass_frame = tk.Frame(win, bg="#fbfaf4")
        self.pass_frame.pack(fill="x", padx=20, pady=18)
        tk.Label(self.pass_frame, text="密码", bg="#fbfaf4", fg="#23262e",
                 font=(FONT_FAMILY, 10)).pack(anchor="w")
        row = tk.Frame(self.pass_frame, bg="#fbfaf4")
        row.pack(fill="x", pady=(5, 0))
        self.entry = tk.Entry(row, show="●", justify="center", width=16,
                              font=(FONT_FAMILY, 13), relief="solid", bd=1,
                              bg="#ffffff", fg="#23262e",
                              highlightthickness=1, highlightbackground="#d8a0b4",
                              highlightcolor="#b32854", insertbackground="#b32854")
        self.entry.pack(fill="x", ipady=5)
        unlock_btn = tk.Button(row, text="解锁", command=self._unlock,
                               relief="flat", bd=0, bg="#b32854", fg="#ffffff",
                               activebackground="#8f1e42",
                               activeforeground="#ffffff", cursor="hand2",
                               font=(FONT_FAMILY, 10, "bold"))
        unlock_btn.pack(fill="x", pady=(7, 0), ipady=3)
        self.entry.bind("<Return>", lambda _e: self._unlock())
        self.entry.bind("<Key>", lambda _e: self.hint.configure(
            text="输入时显示为圆点", fg="#9a8590"))
        self.hint = tk.Label(self.pass_frame, text="输入时显示为圆点",
                             bg="#fbfaf4", fg="#9a8590",
                             font=(FONT_FAMILY, 8))
        self.hint.pack(anchor="w", pady=(6, 0))
        self.entry.focus_set()

        self.main_frame = tk.Frame(win, bg="#fbfaf4")
        tk.Label(self.main_frame, text="好感度", bg="#fbfaf4", fg="#23262e",
                 font=(FONT_FAMILY, 10)).pack(anchor="w", padx=20)
        self.value_var = tk.IntVar(value=int(pet.affection))
        self.value_label = tk.Label(self.main_frame, text="%d / 100" % pet.affection,
                                    bg="#fbfaf4", fg="#b32854",
                                    font=(FONT_FAMILY, 18, "bold"))
        self.value_label.pack(anchor="w", padx=20)
        self.scale = tk.Scale(self.main_frame, from_=0, to=100, orient="horizontal",
                              variable=self.value_var, showvalue=0,
                              length=310, sliderlength=22,
                              bg="#fbfaf4", fg="#23262e",
                              troughcolor="#ead6dd", highlightthickness=0,
                              activebackground="#b32854",
                              command=self._on_scale)
        self.scale.pack(fill="x", padx=20, pady=(2, 6))
        btns = tk.Frame(self.main_frame, bg="#fbfaf4")
        btns.pack(fill="x", padx=20)
        for delta in (-10, -5, -1, 1, 5, 10):
            tk.Button(btns, text="%+d" % delta, command=lambda d=delta: self._bump(d),
                      relief="solid", bd=1, bg="#ffffff", fg="#7a2c47",
                      activebackground="#f4dbe3", activeforeground="#7a2c47",
                      cursor="hand2", font=(FONT_FAMILY, 9),
                      width=3).pack(side="left", padx=2, pady=2)
        tk.Button(self.main_frame, text="应用", command=self._apply,
                  relief="flat", bd=0, bg="#b32854", fg="#ffffff",
                  activebackground="#8f1e42", activeforeground="#ffffff",
                  cursor="hand2", font=(FONT_FAMILY, 11, "bold")).pack(
                      fill="x", padx=20, pady=(14, 4), ipady=4)
        self.status = tk.Label(self.main_frame, text="", bg="#fbfaf4",
                               fg="#4a8a5a", font=(FONT_FAMILY, 9))
        self.status.pack(anchor="w", padx=20)
        tk.Button(self.main_frame, text="关闭", command=self._close,
                  relief="flat", bd=0, bg="#fbfaf4", fg="#9a8590",
                  activebackground="#fbfaf4", activeforeground="#6b5560",
                  cursor="hand2", font=(FONT_FAMILY, 9)).pack(pady=(4, 10))

    def _unlock(self):
        if self.unlocked:
            return
        value = self.entry.get().strip()
        if value != MODIFIER_PASSWORD:
            self.hint.configure(text="密码不对", fg="#c03030")
            self.entry.delete(0, "end")
            self.entry.focus_set()
            return
        self.unlocked = True
        self.pass_frame.pack_forget()
        # 把密码框彻底销毁：只 pack_forget 的话焦点/输入法还挂在它上面，
        # 解锁后中文候选框会浮在好感度滑块上
        try:
            self.entry.destroy()
        except Exception:                       # noqa: BLE001
            pass
        self.entry = None
        self.main_frame.pack(fill="x")
        self.value_var.set(int(self.pet.affection))
        self._ready = True
        self._on_scale()
        try:
            self.status.configure(text="拖动滑块或点 ±，立即生效")
        except tk.TclError:
            pass
        try:
            self.scale.focus_set()
        except tk.TclError:
            pass

    def _on_scale(self, _value=None):
        value = int(self.value_var.get())
        if self.value_label is not None:
            self.value_label.configure(text="%d / 100" % value)
        # 以前要再点一下「应用」才写进去，很多人拖完直接关窗，看起来就像
        # 好感度不会变。现在拖动/点 ± 的每一格都立刻生效。
        if self.unlocked and self._ready:
            self.pet.set_affection(value)

    def _bump(self, delta):
        if not self.unlocked:
            return
        value = max(0, min(100, int(self.value_var.get()) + int(delta)))
        self.value_var.set(value)
        self._on_scale()

    def _apply(self):
        if not self.unlocked:
            return
        self._on_scale()
        value = int(self.value_var.get())
        self.status.configure(text="已设置为 %d / 100" % value)

    def _close(self):
        try:
            self.win.grab_release()
        except Exception:
            pass
        if self.win is not None and self.win.winfo_exists():
            self.win.destroy()
        self.win = None


# =====================================================================
# 设置窗口：左侧分类，右侧「图标 + 标题 + 说明 + 胶囊开关」
# =====================================================================
SET_W, SET_H = 880, 640
SET_BG = "#f4faff"
SET_SIDE = "#fbfdff"
SET_TEXT = "#22344a"
SET_DESC = "#8aa6c9"
SET_BLUE = "#2f8bf5"
SET_PINK = "#f4789f"
SET_SOFT = "#e7f1fc"
SET_LINE = "#dbe8f7"
MENU_BG = "#fdfeff"
MENU_FG = "#243546"
MENU_HI = "#e8f2fd"
MENU_FG_HI = "#1466c8"
MENU_ACCENT = "#f4789f"
MENU_ICON = "#7fa2c6"
MENU_HEAD = "#9db4cd"

_ROUND_CACHE = {}
_SWITCH_CACHE = {}
_ICON_CACHE = {}


def _rgba(color, alpha=255):
    from PIL import ImageColor
    r, g, b = ImageColor.getrgb(color)[:3]
    return (r, g, b, alpha)


def _round_pil(size, radius, fill, outline=None, border=0):
    """圆角矩形（4 倍超采样再缩回来，边缘不带锯齿）。

    返回的 PIL 图和 Tk 无关，可以跨窗口/跨控件复用，所以缓存起来。
    """
    key = (int(size[0]), int(size[1]), int(radius), fill, outline, int(border))
    img = _ROUND_CACHE.get(key)
    if img is not None:
        return img
    ss = 4
    w, h = max(1, int(size[0])), max(1, int(size[1]))
    big = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    draw.rounded_rectangle([0, 0, w * ss - 1, h * ss - 1],
                           radius=max(1, int(radius)) * ss,
                           fill=_rgba(fill),
                           outline=_rgba(outline) if outline else None,
                           width=int(border) * ss)
    img = big.resize((w, h), Image.LANCZOS)
    _ROUND_CACHE[key] = img
    return img


def _switch_pil(on, step):
    """胶囊开关的一帧：打开是参考图那种蓝、关掉是灰，step=0..12 是滑块位置。"""
    key = (bool(on), int(step))
    img = _SWITCH_CACHE.get(key)
    if img is not None:
        return img
    ss = 4
    w, h = 52, 30
    big = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    fill = "#3d8bfd" if on else "#d7dfeb"
    draw.rounded_rectangle([1, 2, w * ss - 2, h * ss - 3],
                           radius=(h * ss) // 2 - 1, fill=_rgba(fill))
    r = (h * ss) // 2 - 5
    x0 = 2 + (h * ss) // 2 - 2
    x1 = w * ss - 2 - (h * ss) // 2 + 2
    cx = x0 + (x1 - x0) * (int(step) / 12.0)
    cy = h * ss // 2 - 1
    # 一点点投影，让白滑块从胶囊上"浮"起来
    draw.ellipse([cx - r, cy - r + 2, cx + r, cy + r + 2], fill=(70, 100, 140, 40))
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 255),
                 outline=(240, 245, 251, 255), width=2)
    img = big.resize((w, h), Image.LANCZOS)
    _SWITCH_CACHE[key] = img
    return img


_BADGE_CACHE = {}


def _badge_pil(size=64, faded=False):
    """校徽（圆形，四角透明）。faded=True 给大尺寸水印用。"""
    key = (int(size), bool(faded))
    if key in _BADGE_CACHE:
        return _BADGE_CACHE[key]
    path = _asset_path("school_badge_faded.png" if faded else "school_badge.png")
    try:
        img = Image.open(path).convert("RGBA").resize((int(size), int(size)),
                                                      Image.LANCZOS)
    except Exception:                       # noqa: BLE001 - 缺图也要能开设置
        _log_exception()
        img = Image.new("RGBA", (int(size), int(size)), (244, 120, 159, 255))
    _BADGE_CACHE[key] = img
    return img


def _logo_pil(size=62):
    """侧栏顶部的粉色猫头 logo。"""
    ss = 4
    s = size * ss
    big = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    draw.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.28),
                           fill=_rgba(SET_PINK))
    white = (255, 255, 255, 255)
    draw.polygon([(0.20 * s, 0.42 * s), (0.22 * s, 0.14 * s), (0.44 * s, 0.36 * s)],
                 fill=white)
    draw.polygon([(0.80 * s, 0.42 * s), (0.78 * s, 0.14 * s), (0.56 * s, 0.36 * s)],
                 fill=white)
    draw.ellipse([0.18 * s, 0.34 * s, 0.82 * s, 0.88 * s], fill=white)
    draw.ellipse([0.25 * s, 0.40 * s, 0.40 * s, 0.55 * s], fill=_rgba(SET_PINK))
    draw.ellipse([0.60 * s, 0.40 * s, 0.75 * s, 0.55 * s], fill=_rgba(SET_PINK))
    draw.arc([0.42 * s, 0.52 * s, 0.58 * s, 0.68 * s], 20, 160,
             fill=_rgba(SET_PINK), width=int(s * 0.022))
    draw.ellipse([0.30 * s, 0.60 * s, 0.38 * s, 0.65 * s], fill=_rgba("#ffd9e4"))
    draw.ellipse([0.62 * s, 0.60 * s, 0.70 * s, 0.65 * s], fill=_rgba("#ffd9e4"))
    return big.resize((size, size), Image.LANCZOS)


def _icon_pil(name, size=18, color="#93b5da"):
    """一套线性小图标（设置窗口里的行首图标/分类图标）。"""
    key = (name, int(size), color)
    img = _ICON_CACHE.get(key)
    if img is not None:
        return img
    ss = 6
    s = int(size) * ss
    big = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    c = _rgba(color)
    lw = max(2, int(round(s * 0.070)))

    def line(*pts):
        draw.line([(x * s, y * s) for x, y in pts], fill=c, width=lw, joint="curve")

    def box(box_, radius=0.14):
        draw.rounded_rectangle([box_[0] * s, box_[1] * s, box_[2] * s, box_[3] * s],
                               radius=radius * s, outline=c, width=lw)

    if name == "pin":
        line((0.5, 0.46), (0.5, 0.86))
        draw.ellipse([0.30 * s, 0.10 * s, 0.70 * s, 0.50 * s], outline=c, width=lw)
        draw.ellipse([0.44 * s, 0.24 * s, 0.56 * s, 0.36 * s], fill=c)
    elif name == "cursor":
        draw.polygon([(0.31 * s, 0.12 * s), (0.31 * s, 0.82 * s),
                      (0.46 * s, 0.64 * s), (0.56 * s, 0.88 * s),
                      (0.69 * s, 0.82 * s), (0.59 * s, 0.60 * s),
                      (0.79 * s, 0.55 * s)], outline=c, width=lw)
    elif name == "bubble":
        box((0.10, 0.16, 0.90, 0.68), 0.16)
        line((0.30, 0.68), (0.30, 0.90), (0.50, 0.68))
        for cx in (0.34, 0.50, 0.66):
            draw.ellipse([(cx - 0.042) * s, 0.37 * s, (cx + 0.042) * s, 0.455 * s],
                         fill=c)
    elif name == "click":
        draw.polygon([(0.34 * s, 0.14 * s), (0.34 * s, 0.74 * s),
                      (0.46 * s, 0.60 * s), (0.55 * s, 0.80 * s),
                      (0.65 * s, 0.75 * s), (0.57 * s, 0.56 * s),
                      (0.74 * s, 0.52 * s)], outline=c, width=lw)
        for x1, y1, x2, y2 in ((0.12, 0.18, 0.22, 0.28), (0.88, 0.18, 0.78, 0.28),
                               (0.12, 0.50, 0.22, 0.50)):
            line((x1, y1), (x2, y2))
    elif name == "image":
        box((0.10, 0.16, 0.90, 0.84), 0.13)
        draw.ellipse([0.24 * s, 0.28 * s, 0.40 * s, 0.44 * s], outline=c, width=lw)
        draw.polygon([(0.16 * s, 0.78 * s), (0.44 * s, 0.46 * s),
                      (0.62 * s, 0.66 * s), (0.72 * s, 0.56 * s),
                      (0.86 * s, 0.78 * s)], outline=c, width=lw)
    elif name == "size":
        line((0.26, 0.74), (0.74, 0.26))
        draw.polygon([(0.82 * s, 0.18 * s), (0.82 * s, 0.44 * s),
                      (0.56 * s, 0.18 * s)], fill=c)
        draw.polygon([(0.18 * s, 0.82 * s), (0.18 * s, 0.56 * s),
                      (0.44 * s, 0.82 * s)], fill=c)
    elif name == "eye":
        draw.ellipse([0.08 * s, 0.26 * s, 0.92 * s, 0.74 * s], outline=c, width=lw)
        draw.ellipse([0.40 * s, 0.40 * s, 0.60 * s, 0.60 * s], fill=c)
    elif name == "shield":
        draw.polygon([(0.50 * s, 0.10 * s), (0.86 * s, 0.26 * s),
                      (0.86 * s, 0.54 * s), (0.50 * s, 0.90 * s),
                      (0.14 * s, 0.54 * s), (0.14 * s, 0.26 * s)],
                     outline=c, width=lw)
        line((0.33, 0.50), (0.45, 0.62), (0.68, 0.38))
    elif name == "paw":
        draw.ellipse([0.26 * s, 0.44 * s, 0.74 * s, 0.92 * s], outline=c, width=lw)
        for cx, cy, r in ((0.20, 0.33, 0.085), (0.40, 0.23, 0.095),
                          (0.62, 0.23, 0.095), (0.81, 0.34, 0.075)):
            draw.ellipse([(cx - r) * s, (cy - r) * s, (cx + r) * s, (cy + r) * s],
                         fill=c)
    elif name == "sparkle":
        draw.polygon([(0.50 * s, 0.06 * s), (0.60 * s, 0.40 * s),
                      (0.94 * s, 0.50 * s), (0.60 * s, 0.60 * s),
                      (0.50 * s, 0.94 * s), (0.40 * s, 0.60 * s),
                      (0.06 * s, 0.50 * s), (0.40 * s, 0.40 * s)], fill=c)
    elif name == "refresh":
        draw.arc([0.16 * s, 0.16 * s, 0.84 * s, 0.84 * s], 40, 320, fill=c, width=lw)
        draw.polygon([(0.86 * s, 0.10 * s), (0.58 * s, 0.18 * s),
                      (0.80 * s, 0.38 * s)], fill=c)
    elif name == "window":
        box((0.10, 0.18, 0.90, 0.82), 0.12)
        line((0.10, 0.35), (0.90, 0.35))
        draw.ellipse([0.17 * s, 0.235 * s, 0.225 * s, 0.29 * s], fill=c)
    elif name == "fullscreen":
        box((0.08, 0.20, 0.92, 0.78), 0.10)
        line((0.36, 0.38), (0.52, 0.49), (0.36, 0.60))
        line((0.56, 0.38), (0.70, 0.49), (0.56, 0.60))
        line((0.30, 0.86), (0.70, 0.86))
    elif name == "key":
        draw.ellipse([0.12 * s, 0.28 * s, 0.52 * s, 0.68 * s], outline=c, width=lw)
        line((0.52, 0.48), (0.90, 0.48))
        line((0.76, 0.48), (0.76, 0.66))
        line((0.86, 0.48), (0.86, 0.62))
    elif name == "cat":
        draw.ellipse([0.14 * s, 0.32 * s, 0.86 * s, 0.92 * s], outline=c, width=lw)
        draw.polygon([(0.18 * s, 0.40 * s), (0.20 * s, 0.10 * s),
                      (0.44 * s, 0.30 * s)], outline=c, width=lw)
        draw.polygon([(0.82 * s, 0.40 * s), (0.80 * s, 0.10 * s),
                      (0.56 * s, 0.30 * s)], outline=c, width=lw)
        draw.ellipse([0.32 * s, 0.50 * s, 0.385 * s, 0.58 * s], fill=c)
        draw.ellipse([0.615 * s, 0.50 * s, 0.68 * s, 0.58 * s], fill=c)
        line((0.46, 0.64), (0.50, 0.68), (0.54, 0.64))
    elif name == "jump":
        line((0.50, 0.84), (0.50, 0.22))
        line((0.30, 0.42), (0.50, 0.20), (0.70, 0.42))
        line((0.24, 0.78), (0.76, 0.78))
    elif name == "squash":
        line((0.50, 0.12), (0.50, 0.50))
        line((0.32, 0.34), (0.50, 0.52), (0.68, 0.34))
        draw.ellipse([0.16 * s, 0.66 * s, 0.84 * s, 0.86 * s],
                     outline=c, width=lw)
    elif name == "spin":
        draw.arc([0.16 * s, 0.16 * s, 0.84 * s, 0.84 * s], 120, 60,
                 fill=c, width=lw)
        draw.polygon([(0.70 * s, 0.06 * s), (0.92 * s, 0.28 * s),
                      (0.66 * s, 0.36 * s)], fill=c)
    elif name == "dodge":
        draw.arc([0.26 * s, 0.20 * s, 0.96 * s, 0.80 * s], 120, 240,
                 fill=c, width=lw)
        draw.arc([0.04 * s, 0.20 * s, 0.74 * s, 0.80 * s], -60, 60,
                 fill=c, width=lw)
        draw.ellipse([0.40 * s, 0.40 * s, 0.60 * s, 0.60 * s], fill=c)
    elif name == "shoot":
        draw.polygon([(0.08 * s, 0.30 * s), (0.92 * s, 0.16 * s),
                      (0.44 * s, 0.86 * s), (0.38 * s, 0.54 * s)],
                     outline=c, width=lw)
        line((0.38, 0.54), (0.92, 0.16))
    elif name == "smile":
        draw.ellipse([0.12 * s, 0.12 * s, 0.88 * s, 0.88 * s],
                     outline=c, width=lw)
        draw.ellipse([0.32 * s, 0.34 * s, 0.40 * s, 0.46 * s], fill=c)
        draw.ellipse([0.60 * s, 0.34 * s, 0.68 * s, 0.46 * s], fill=c)
        draw.arc([0.30 * s, 0.36 * s, 0.70 * s, 0.72 * s], 20, 160,
                 fill=c, width=lw)
    elif name == "face":
        draw.ellipse([0.14 * s, 0.14 * s, 0.86 * s, 0.86 * s],
                     outline=c, width=lw)
        draw.ellipse([0.30 * s, 0.42 * s, 0.40 * s, 0.54 * s], fill=c)
        draw.ellipse([0.60 * s, 0.42 * s, 0.70 * s, 0.54 * s], fill=c)
        line((0.42, 0.64), (0.50, 0.70), (0.58, 0.64))
        draw.ellipse([0.20 * s, 0.54 * s, 0.30 * s, 0.62 * s], fill=c)
        draw.ellipse([0.70 * s, 0.54 * s, 0.80 * s, 0.62 * s], fill=c)
    elif name == "note":
        draw.ellipse([0.18 * s, 0.66 * s, 0.38 * s, 0.84 * s], fill=c)
        draw.ellipse([0.56 * s, 0.56 * s, 0.76 * s, 0.74 * s], fill=c)
        line((0.34, 0.74), (0.34, 0.24), (0.72, 0.18), (0.72, 0.66))
        line((0.34, 0.24), (0.72, 0.18))
    elif name == "globe":
        draw.ellipse([0.12 * s, 0.12 * s, 0.88 * s, 0.88 * s],
                     outline=c, width=lw)
        draw.ellipse([0.36 * s, 0.12 * s, 0.64 * s, 0.88 * s],
                     outline=c, width=lw)
        line((0.14, 0.50), (0.86, 0.50))
    elif name == "power":
        draw.arc([0.16 * s, 0.18 * s, 0.84 * s, 0.86 * s], 300, 240,
                 fill=c, width=lw)
        line((0.50, 0.10), (0.50, 0.46))
    else:
        draw.ellipse([0.15 * s, 0.15 * s, 0.85 * s, 0.85 * s], outline=c, width=lw)
    img = big.resize((int(size), int(size)), Image.LANCZOS)
    _ICON_CACHE[key] = img
    return img


class ToggleSwitch(tk.Canvas):
    """胶囊开关：关是灰的、开是粉的，点一下滑块动过去。"""

    W, H = 52, 30

    def __init__(self, master, value=False, command=None, bg=SET_BG):
        super().__init__(master, width=self.W, height=self.H, bg=bg, bd=0,
                         highlightthickness=0, cursor="hand2")
        self._value = bool(value)
        self._t = 1.0 if self._value else 0.0
        self._target = self._t
        self._job = None
        self.command = command
        self._photos = {}
        self._item = self.create_image(0, 0, anchor="nw", image=self._photo())
        self.bind("<Button-1>", self._on_click)

    def _photo(self):
        step = int(round(self._t * 12))
        key = (self._value, step)
        photo = self._photos.get(key)
        if photo is None:
            photo = ImageTk.PhotoImage(_switch_pil(self._value, step), master=self)
            self._photos[key] = photo
        return photo

    def _on_click(self, _event=None):
        self.set(not self._value)
        if self.command is not None:
            self.command(self._value)

    def get(self):
        return self._value

    def set(self, value, animate=True):
        """同步外观。animate=False 用于外部状态同步（不闪动画）。"""
        self._value = bool(value)
        self._target = 1.0 if self._value else 0.0
        if not self.winfo_exists():
            return
        if not animate:
            self._cancel()
            self._t = self._target
            self._draw()
            return
        if self._job is None:
            self._step()

    def _cancel(self):
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:                   # noqa: BLE001
                pass
            self._job = None

    def _step(self):
        self._job = None
        if not self.winfo_exists():
            return
        if abs(self._target - self._t) <= 0.17:
            self._t = self._target
            self._draw()
            return
        self._t += 0.17 if self._target > self._t else -0.17
        self._draw()
        self._job = self.after(16, self._step)

    def _draw(self):
        try:
            self.itemconfigure(self._item, image=self._photo())
        except tk.TclError:
            pass

    def destroy(self):
        self._cancel()
        super().destroy()


class PillButton(tk.Canvas):
    """圆角胶囊按钮。"""

    KINDS = {"primary": ("#f4789f", "#ffffff"),
             "ghost": (SET_SOFT, "#4d7fb5"),
             "white": ("#ffffff", SET_BLUE),
             "sel": ("#f4789f", "#ffffff"),
             "unsel": (SET_SOFT, "#4d7fb5")}

    def __init__(self, master, text, command=None, kind="ghost", size="m",
                 bg=SET_BG):
        self.text = text
        self.command = command
        self.kind = kind
        self.size = size
        self._photos = {}
        self._hover = False
        height = 36 if size == "m" else 30
        self._font = tkfont.Font(root=master, family=FONT_FAMILY,
                                 size=10 if size == "m" else 9, weight="bold")
        width = self._font.measure(text) + (44 if size == "m" else 30)
        super().__init__(master, width=width, height=height, bg=bg, bd=0,
                         highlightthickness=0, cursor="hand2")
        self._radius = height // 2
        self._img = self.create_image(0, 0, anchor="nw")
        self._label = self.create_text(width // 2, height // 2, text=text,
                                       font=self._font)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self._render()

    def _on_click(self, _event=None):
        if self.command is not None:
            self.command()

    def _set_hover(self, on):
        self._hover = bool(on)
        self._render()

    def set_kind(self, kind):
        if kind == self.kind:
            return
        self.kind = kind
        self._render()

    def _render(self):
        if not self.winfo_exists():
            return
        fill, fg = self.KINDS.get(self.kind, self.KINDS["ghost"])
        if self._hover:
            fill = {"sel": "#ef6a93", "primary": "#ef6a93"}.get(self.kind,
                                                               "#d9e8f8")
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()
        photo = self._photos.get(fill)
        if photo is None:
            photo = ImageTk.PhotoImage(
                _round_pil((w, h), self._radius, fill), master=self)
            self._photos[fill] = photo
        self.itemconfigure(self._img, image=photo)
        self.coords(self._label, w // 2, h // 2)
        self.itemconfigure(self._label, fill=fg)


class PillGroup(tk.Frame):
    """一排单选胶囊（形象 / 大小 / 不透明度）。放不下会自动折行。"""

    GAP = 6

    def __init__(self, master, options, value, command=None, bg=SET_BG,
                 max_width=0):
        super().__init__(master, bg=bg)
        self.command = command
        self.value = value
        self.buttons = {}
        rows = []
        row = None
        used = 0
        for text, val in options:
            if row is None:
                row = tk.Frame(self, bg=bg)
                used = 0
            btn = PillButton(row, text, size="s", bg=bg,
                             kind="sel" if val == value else "unsel",
                             command=lambda v=val: self._pick(v))
            need = btn.winfo_reqwidth() + self.GAP
            if max_width and used and used + need > max_width:
                rows.append(row)
                row = tk.Frame(self, bg=bg)
                used = 0
            btn.pack(side="left", padx=(0, self.GAP))
            used += need
            self.buttons[val] = btn
        if row is not None:
            rows.append(row)
        for i, frame in enumerate(rows):
            frame.pack(anchor="w", pady=(0 if i == 0 else 6, 0))

    def _pick(self, val):
        if val == self.value:
            return
        self.set_value(val)
        if self.command is not None:
            self.command(val)

    def set_value(self, val):
        self.value = val
        for key, btn in self.buttons.items():
            btn.set_kind("sel" if key == val else "unsel")


class NavItem(tk.Canvas):
    """侧栏分类按钮（选中是粉色圆角块 + 白字）。"""

    W, H = 152, 60

    def __init__(self, master, text, icon, command, bg=SET_SIDE):
        super().__init__(master, width=self.W, height=self.H, bg=bg, bd=0,
                         highlightthickness=0, cursor="hand2")
        self.text = text
        self.icon = icon
        self.command = command
        self.active = False
        self._hover = False
        self._bg_photo = None
        self._icon_photo = None
        self.bind("<Button-1>", lambda e: self.command())
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self._render()

    def set_active(self, on):
        if bool(on) == self.active:
            return
        self.active = bool(on)
        self._render()

    def _set_hover(self, on):
        self._hover = bool(on)
        self._render()

    def _render(self):
        if not self.winfo_exists():
            return
        self.delete("all")
        if self.active:
            color = SET_PINK
        elif self._hover:
            color = "#fdeef4"
        else:
            color = None
        if color is not None:
            self._bg_photo = ImageTk.PhotoImage(
                _round_pil((self.W, self.H), 16, color), master=self)
            self.create_image(0, 0, anchor="nw", image=self._bg_photo)
        fg = "#ffffff" if self.active else "#4d6b8f"
        self._icon_photo = ImageTk.PhotoImage(_icon_pil(self.icon, 20, fg),
                                             master=self)
        self.create_image(27, self.H // 2, image=self._icon_photo)
        self.create_text(46, self.H // 2, anchor="w", text=self.text, fill=fg,
                         font=(FONT_FAMILY, 11, "bold"))


class SettingsWindow:
    """独立设置窗口：左侧分类，右边一列「标题 / 说明 / 开关」。

    非模态，同一时间只开一个；改任何一项都立刻生效，也会同步回右键菜单的
    勾选状态。所有回调都在主线程（Tk 事件里）跑，方法本身不做重活。
    """

    TABS = (("prefs", "偏好", "cat"),
            ("gestures", "手势", "paw"),
            ("look", "外观", "eye"),
            ("talk", "对话", "bubble"),
            ("about", "关于", "image"))

    def __init__(self, pet, on_close=None):
        self.pet = pet
        self.on_close = on_close
        self.win = None
        self.tab = "prefs"
        self._photos = []          # 窗口级（logo/标题图标），整个窗口生命周期有效
        self._page_photos = []     # 当前页的图标，换页时释放
        self._switches = []
        self._pills = []
        self._navs = {}
        self._body = None
        self._scroll = None
        self._body_id = None
        self._title = None
        self._hint = None
        self._hint_job = None
        self._drag = None
        self._closed = False

    # ------------------------------------------------------------ 窗口
    def show(self):
        if self.win is not None:
            try:
                if self.win.winfo_exists():
                    self.win.deiconify()
                    self.win.lift()
                    self.win.attributes("-topmost", True)
                    self._grab_focus()
                    self.sync()
                    return
            except tk.TclError:
                pass
            self.win = None
        self._build()

    def _grab_focus(self):
        """无边框 Toplevel 不抢焦点，Esc 就收不到；这里主动要一次。

        不能 grab_set：设置窗口开着的宠物还得能点、能被划。
        """
        try:
            self.win.focus_force()
        except tk.TclError:
            pass

    def close(self):
        if self._closed:
            return
        self._closed = True
        win, self.win = self.win, None
        if self._hint_job is not None:
            try:
                win.after_cancel(self._hint_job)
            except Exception:                   # noqa: BLE001
                pass
            self._hint_job = None
        if win is not None:
            try:
                win.destroy()
            except tk.TclError:
                pass
        if self.on_close is not None:
            try:
                self.on_close()
            except Exception:                   # noqa: BLE001
                _log_exception()

    def _photo(self, img, page=False):
        photo = ImageTk.PhotoImage(img, master=self.win)
        (self._page_photos if page else self._photos).append(photo)
        return photo

    def _build(self):
        pet = self.pet
        win = tk.Toplevel(pet.root)
        self.win = win
        win.withdraw()
        win.title("桌面宠物 · 设置")
        win.configure(bg=SET_BG)
        set_overrideredirect(win, True)
        try:
            win.attributes("-topmost", True)
        except tk.TclError:
            pass
        win.protocol("WM_DELETE_WINDOW", self.close)
        win.bind("<Escape>", lambda e: self.close())
        win.bind("<MouseWheel>", self._on_wheel)

        # ---- 左侧分类
        side = tk.Frame(win, bg=SET_SIDE, width=176)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        logo = ImageTk.PhotoImage(_logo_pil(62), master=win)
        self._photos.append(logo)
        tk.Label(side, image=logo, bg=SET_SIDE).pack(pady=(24, 8))
        tk.Label(side, text=APP_NAME, bg=SET_SIDE, fg="#4b9df8",
                 font=(FONT_FAMILY, 14, "bold")).pack()
        tk.Label(side, text="桌宠设置", bg=SET_SIDE, fg="#b3c9e0",
                 font=(FONT_FAMILY, 8)).pack(pady=(0, 16))
        for key, label, icon in self.TABS:
            nav = NavItem(side, label, icon, lambda k=key: self.set_tab(k),
                          bg=SET_SIDE)
            nav.pack(pady=3, padx=12)
            self._navs[key] = nav
        tk.Label(side, text="v1.1", bg=SET_SIDE, fg="#c9dbec",
                 font=(FONT_FAMILY, 8)).pack(side="bottom", pady=(0, 12))
        tk.Label(side, text="莆田第一中学", bg=SET_SIDE, fg="#c6a6b2",
                 font=(FONT_FAMILY, 8)).pack(side="bottom", pady=(0, 6))
        badge = ImageTk.PhotoImage(_badge_pil(56), master=win)
        self._photos.append(badge)
        tk.Label(side, image=badge, bg=SET_SIDE).pack(side="bottom", pady=(0, 4))

        # ---- 右侧
        right = tk.Frame(win, bg=SET_BG)
        right.pack(side="left", fill="both", expand=True)

        head = tk.Frame(right, bg=SET_BG, height=52)
        head.pack(fill="x", padx=26, pady=(16, 6))
        head.pack_propagate(False)
        head.bind("<Button-1>", self._drag_start)
        head.bind("<B1-Motion>", self._drag_move)
        cat = tk.Label(head, bg=SET_BG,
                       image=self._photo(_icon_pil("cat", 22, SET_BLUE)))
        cat.pack(side="left", pady=(4, 0))
        cat.bind("<Button-1>", self._drag_start)
        cat.bind("<B1-Motion>", self._drag_move)
        self._title = tk.Label(head, text="偏好", bg=SET_BG, fg=SET_BLUE,
                               font=(FONT_FAMILY, 15, "bold"))
        self._title.pack(side="left", padx=(8, 0))
        self._title.bind("<Button-1>", self._drag_start)
        self._title.bind("<B1-Motion>", self._drag_move)
        close = tk.Canvas(head, width=34, height=34, bg=SET_BG, bd=0,
                          highlightthickness=0, cursor="hand2")
        close.pack(side="right", pady=(2, 0))
        close.create_text(17, 17, text="✕", fill="#9db6cf",
                          font=(FONT_FAMILY, 13))
        close.bind("<Button-1>", lambda e: self.close())
        close.bind("<Enter>", lambda e: close.configure(bg="#e3eefb"))
        close.bind("<Leave>", lambda e: close.configure(bg=SET_BG))

        bar = tk.Frame(right, bg="#ffffff")
        bar.pack(side="bottom", fill="x")
        tk.Frame(bar, bg=SET_LINE, height=1).pack(side="top", fill="x")
        inner = tk.Frame(bar, bg="#ffffff")
        inner.pack(fill="x", padx=26, pady=10)
        self._hint = tk.Label(inner, text="改动会立刻生效", bg="#ffffff",
                              fg="#9db6cf", font=(FONT_FAMILY, 9))
        self._hint.pack(side="left")
        PillButton(inner, "完成", command=self.close, kind="primary",
                   bg="#ffffff").pack(side="right", padx=(8, 0))
        PillButton(inner, "刷新一下", command=self._refresh, kind="ghost",
                   bg="#ffffff").pack(side="right")

        wrap = tk.Frame(right, bg=SET_BG)
        wrap.pack(fill="both", expand=True)
        self._scroll = tk.Canvas(wrap, bg=SET_BG, bd=0, highlightthickness=0)
        self._scroll.pack(fill="both", expand=True)
        self._body = tk.Frame(self._scroll, bg=SET_BG)
        self._body_id = self._scroll.create_window((0, 0), anchor="nw",
                                                   window=self._body)
        self._body.bind("<Configure>", self._on_body)
        self._scroll.bind("<Configure>", self._on_canvas)

        win.update_idletasks()
        left, top, right_, bottom = work_area(pet.root)
        w = min(SET_W, max(520, right_ - left - 60))
        h = min(SET_H, max(420, bottom - top - 60))
        x = left + (right_ - left - w) // 2
        y = top + (bottom - top - h) // 2
        win.geometry("%dx%d+%d+%d" % (w, h, x, y))
        win.deiconify()
        win.lift()
        self.set_tab("prefs")
        self._grab_focus()

    # ------------------------------------------------------------ 拖动 / 滚动
    def _drag_start(self, event):
        self._drag = (event.x_root, event.y_root,
                      self.win.winfo_x(), self.win.winfo_y())

    def _drag_move(self, event):
        if self._drag is None or self.win is None:
            return
        x0, y0, wx, wy = self._drag
        self.win.geometry("+%d+%d" % (wx + event.x_root - x0,
                                      wy + event.y_root - y0))

    def _on_body(self, _event=None):
        try:
            self._scroll.configure(scrollregion=self._scroll.bbox("all"))
        except tk.TclError:
            pass

    def _on_canvas(self, event):
        try:
            self._scroll.itemconfigure(self._body_id, width=max(1, event.width))
        except tk.TclError:
            pass

    def _on_wheel(self, event):
        if self._scroll is None:
            return
        try:
            region = self._scroll.bbox("all")
            if not region:
                return
            if region[3] - region[1] <= self._scroll.winfo_height():
                return
            self._scroll.yview_scroll(-1 if event.delta > 0 else 1, "units")
        except tk.TclError:
            pass

    # ------------------------------------------------------------ 分类切换
    def set_tab(self, key):
        labels = {k: label for k, label, _icon in self.TABS}
        if key not in labels:
            return
        self.tab = key
        for k, nav in self._navs.items():
            nav.set_active(k == key)
        if self._title is not None:
            self._title.configure(text=labels[key])
        self._render_page()

    def _render_page(self):
        if self._body is None:
            return
        for child in list(self._body.winfo_children()):
            try:
                child.destroy()
            except tk.TclError:
                pass
        self._page_photos = []
        self._switches = []
        self._pills = []
        try:
            self._scroll.yview_moveto(0.0)
        except tk.TclError:
            pass
        builder = getattr(self, "_page_" + self.tab, None)
        if builder is not None:
            builder(self._body)
        self._body.update_idletasks()
        self._on_body()
        self.sync()

    # ------------------------------------------------------------ 小部件工厂
    def _section(self, parent, title, icon):
        head = tk.Frame(parent, bg=SET_BG)
        head.pack(fill="x", padx=30, pady=(20, 10))
        tk.Label(head, bg=SET_BG, image=self._photo(
            _round_pil((4, 18), 2, SET_PINK), page=True)).pack(side="left",
                                                               pady=(1, 0))
        ic = tk.Canvas(head, width=20, height=20, bg=SET_BG, bd=0,
                       highlightthickness=0)
        ic.pack(side="left", padx=(8, 0))
        ic.create_image(10, 10, image=self._photo(_icon_pil(icon, 18, SET_BLUE),
                                                  page=True))
        tk.Label(head, text=title, bg=SET_BG, fg=SET_BLUE,
                 font=(FONT_FAMILY, 10, "bold")).pack(side="left", padx=(6, 0))

    def _row_shell(self, parent, icon, title, desc, wrap=430, below=False):
        outer = tk.Frame(parent, bg=SET_BG)
        outer.pack(fill="x", padx=30, pady=(4, 16))
        row = tk.Frame(outer, bg=SET_BG)
        row.pack(fill="x")
        holder = tk.Frame(outer, bg=SET_BG)
        if not below:
            holder = tk.Frame(row, bg=SET_BG)
            holder.pack(side="right", padx=(14, 0), pady=(3, 0))
        ic = tk.Canvas(row, width=22, height=22, bg=SET_BG, bd=0,
                       highlightthickness=0)
        ic.pack(side="left", anchor="n", pady=(1, 0))
        ic.create_image(11, 11, image=self._photo(_icon_pil(icon, 19, "#93b5da"),
                                                  page=True))
        text = tk.Frame(row, bg=SET_BG)
        text.pack(side="left", fill="x", expand=True, padx=(10, 0))
        tk.Label(text, text=title, bg=SET_BG, fg=SET_TEXT,
                 font=(FONT_FAMILY, 10, "bold")).pack(anchor="w")
        if desc:
            tk.Label(text, text=desc, bg=SET_BG, fg=SET_DESC,
                     font=(FONT_FAMILY, 9), justify="left",
                     wraplength=wrap).pack(anchor="w", pady=(1, 0))
        if below:
            holder.pack(anchor="w", fill="x", padx=(32, 0), pady=(8, 0))
        return holder

    def _note(self, parent, text):
        tk.Label(parent, text=text, bg=SET_BG, fg="#a9c0dc",
                 font=(FONT_FAMILY, 9), justify="left",
                 wraplength=520).pack(anchor="w", padx=56, pady=(2, 6))

    def _setting(self, parent, icon, title, desc, getter, setter, wrap=430):
        holder = self._row_shell(parent, icon, title, desc, wrap=wrap)
        switch = ToggleSwitch(holder, value=bool(getter()), bg=SET_BG,
                              command=lambda v: self._apply(setter, bool(v)))
        switch.pack()
        self._switches.append((getter, switch))
        return switch

    def _choice(self, parent, icon, title, desc, options, getter, setter,
                row_key, below=False):
        holder = self._row_shell(parent, icon, title, desc, below=below,
                                 wrap=520 if below else 430)
        group = PillGroup(holder, options, getter(),
                          command=lambda v: self._apply(setter, v), bg=SET_BG,
                          max_width=560 if below else 0)
        group.pack(anchor="w")
        self._pills.append((row_key, getter, group))
        return group

    def _apply(self, setter, value):
        try:
            setter(value)
        except Exception:                       # noqa: BLE001
            _log_exception()
        self.sync()

    # ------------------------------------------------------------ 三个页面
    def _page_prefs(self, parent):
        pet = self.pet
        self._section(parent, "窗口", "window")
        self._setting(parent, "cursor", "鼠标穿透",
                      "鼠标可以穿过桌宠，点不到它。想关掉时右键托盘图标。",
                      lambda: getattr(pet, "click_through", False),
                      pet.set_click_through)
        self._setting(parent, "bubble", "显示气泡",
                      "关掉后它不再冒气泡说话，只安静地待在桌面上。",
                      lambda: pet.bubble_enabled, pet.set_bubble_enabled)
        self._section(parent, "桌面显示", "fullscreen")
        self._setting(parent, "fullscreen", "全屏时停用",
                      "前台有全屏窗口（游戏、全屏视频、演示）时它先躲起来，"
                      "动画、气泡和 AI 都停下来，退出全屏再自己回来。",
                      lambda: pet.pause_fullscreen, pet.set_pause_fullscreen)
        self._section(parent, "启动", "power")
        self._setting(parent, "power", "开机自动启动",
                      "开机后自己出现在桌面上（写的是当前用户的启动项，不需要管理员）。",
                      lambda: pet.autostart, pet.set_autostart)
        self._section(parent, "卡死急救", "shield")
        self._setting(parent, "refresh", "卡死自动刷新",
                      "超过 9 秒没有响应时自动刷新一次；还是卡着就让桌宠自己重启。",
                      lambda: pet.auto_restart, pet.set_auto_restart)
        self._note(parent, "桌宠卡住、气泡不消失时，点下面「刷新一下」就能把它拽回来，"
                           "不用结束进程。")

    def _page_gestures(self, parent):
        pet = self.pet
        self._section(parent, "互动", "paw")
        self._setting(parent, "paw", "手势互动",
                      "鼠标从身上划过时会压扁、跳一下、躲开、转圈和摸头。"
                      "关掉后这些动作都不再触发。",
                      lambda: pet.gestures_enabled, pet.set_gestures_enabled)
        self._setting(parent, "refresh", "摇一摇刷新",
                      "在身上快速左右摇一摇：开着就直接刷新（卡死时也能摇），"
                      "关掉它只是摇头撒娇。",
                      lambda: pet.shake_refresh, pet.set_shake_refresh)
        self._setting(parent, "click", "点击说话",
                      "点一下桌宠就说一句话。关掉后单击只跳一下，不弹气泡。",
                      lambda: pet.click_speak, pet.set_click_speak)
        self._note(parent, "下滑压扁 / 连着下滑两次弹一下 / 上划跳一下 / "
                           "身体横划躲开 / 绕圈转晕 / 头顶来回蹭是摸头 / "
                           "按住不动一秒也是摸头 / 身上左右摇一摇看上面的开关。"
                           "右键菜单「逗它玩」里的动作不受这个开关限制，"
                           "想让它做动作随时可以手动点。")

    def _page_look(self, parent):
        pet = self.pet
        self._section(parent, "气泡", "bubble")
        self._choice(parent, "bubble", "停留时长",
                     "一句话在屏幕上停留多久。",
                     [("2 秒", 2000), ("4 秒", 4000), ("6 秒", 6000),
                      ("8 秒", 8000)],
                     lambda: pet.bubble_ms, pet.set_bubble_ms, "bubble_ms")
        self._section(parent, "动作", "sparkle")
        self._choice(parent, "sparkle", "动作幅度",
                     "跳多高、晃多明显。安静一点适合上班摸鱼。",
                     [("安静", "calm"), ("正常", "normal"),
                      ("活泼", "lively")],
                     lambda: pet.anim_level, pet.set_anim_level, "anim_level")
        self._choice(parent, "paw", "手势灵敏度",
                     "划动要多快、多远才算一个手势。",
                     [("迟钝", "low"), ("正常", "normal"),
                      ("灵敏", "high")],
                     lambda: pet.gesture_sensitivity,
                     pet.set_gesture_sensitivity, "gesture")
        self._note(parent, "灵敏度调高以后轻轻一划就有反应，但打字时手从屏幕上"
                           "扫过也可能被当成手势；调低更稳。")

    def _page_about(self, parent):
        pet = self.pet
        box = tk.Frame(parent, bg=SET_BG)
        box.pack(fill="x", pady=(18, 4))
        badge = ImageTk.PhotoImage(_badge_pil(104), master=self.win)
        self._page_photos.append(badge)
        tk.Label(box, image=badge, bg=SET_BG).pack()
        tk.Label(box, text="莆田第一中学", bg=SET_BG, fg="#22344a",
                 font=(FONT_FAMILY, 13, "bold")).pack(pady=(8, 0))
        tk.Label(box, text="桌面宠物 · 校徽纪念版", bg=SET_BG, fg="#8aa6c9",
                 font=(FONT_FAMILY, 9)).pack(pady=(2, 0))
        self._section(parent, "关于", "cat")
        holder = self._row_shell(parent, "image", "素材目录",
                                 "立绘放在 image/，音乐放在 music/，换图不用改代码。")
        PillButton(holder, "打开 image", kind="white", size="s",
                   command=lambda: self._apply(pet.open_image_folder, None)
                   ).pack(side="left")
        self._note(parent, "版本 v1.1   渲染后端 %s   配置文件 pet_config.json"
                   % getattr(getattr(pet, "backend", None), "style", "auto"))

    def _page_talk(self, parent):
        pet = self.pet
        self._section(parent, "对话", "bubble")
        self._setting(parent, "sparkle", "启用 AI",
                      "开着才能接话、聊天；关掉只用内置话术。",
                      lambda: pet.ai_enabled, pet.set_ai_enabled)
        self._setting(parent, "sparkle", "说话带颜文字",
                      "每句话后面带一个颜文字，不喜欢可以关掉。",
                      lambda: pet.kaomoji_enabled, pet.set_kaomoji_enabled)
        self._section(parent, "连接", "key")
        holder = self._row_shell(parent, "key", "API Key / 记忆",
                                 "换 Key、清空和当前形象的对话记录。")
        PillButton(holder, "清空记忆", kind="ghost", size="s",
                   command=self._forget_memory).pack(side="left", padx=(0, 6))
        PillButton(holder, "设置 Key…", kind="white", size="s",
                   command=self._set_key).pack(side="left")
        self._note(parent, "模型：%s" % (getattr(pet.brain, "model", "") or "默认"))

    # ------------------------------------------------------------ 页面动作
    def _refresh(self):
        try:
            self.pet.request_refresh()
        except Exception:                       # noqa: BLE001
            _log_exception()
        self._flash("已经让它刷新一下了…")

    def _set_key(self):
        try:
            self.pet.set_api_key()
        except Exception:                       # noqa: BLE001
            _log_exception()
        self.sync()

    def _forget_memory(self):
        with self.pet._modal():
            ok = messagebox.askyesno("清空记忆",
                                     "会忘掉和当前形象的所有对话，确定吗？",
                                     parent=self.win)
        if ok:
            try:
                self.pet.forget_chat()
            except Exception:                   # noqa: BLE001
                _log_exception()
            self._flash("已经忘掉了。")

    def _flash(self, text):
        if self._hint is None:
            return
        self._hint.configure(text=text, fg="#f4789f")
        if self._hint_job is not None:
            try:
                self.win.after_cancel(self._hint_job)
            except Exception:                   # noqa: BLE001
                pass
        self._hint_job = self.win.after(1800, self._reset_hint)

    def _reset_hint(self):
        self._hint_job = None
        if self._hint is not None:
            self._hint.configure(text="改动会立刻生效", fg="#9db6cf")

    # ------------------------------------------------------------ 同步
    def sync(self):
        """把界面上的开关/选中项对齐到桌宠的真实状态。"""
        win = self.win
        if win is None or not win.winfo_exists():
            return
        for getter, switch in list(self._switches):
            try:
                switch.set(bool(getter()), animate=False)
            except Exception:                   # noqa: BLE001
                pass
        for _key, getter, group in list(self._pills):
            try:
                group.set_value(getter())
            except Exception:                   # noqa: BLE001
                pass


class PetWatchdog(threading.Thread):
    """主线程心跳看门狗：卡死时用纯 Win32 消息急救，必要时重启进程。

    这个线程**绝对不能碰 Tk**（Tk 不是线程安全的）：只读布尔/浮点字段、
    发窗口消息、写日志、起新进程。
    """

    WARN_S = 4.0
    RESCUE_S = 9.0
    RESTART_S = 25.0

    def __init__(self, pet):
        super().__init__(name="pet-watchdog", daemon=True)
        self.pet = pet
        self._stop = threading.Event()
        self._restarted = False

    def stop(self):
        self._stop.set()

    def _log(self, text):
        try:
            path = os.path.join(ROOT, "pet_error.log")
            if os.path.exists(path) and os.path.getsize(path) > 256 * 1024:
                os.remove(path)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("----- %s watchdog\n%s\n"
                         % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
        except Exception:                       # noqa: BLE001
            pass

    def run(self):
        pet = self.pet
        while not self._stop.wait(0.5):
            if not getattr(pet, "_alive", False):
                return
            gap = time.monotonic() - getattr(pet, "_last_tick", time.monotonic())
            if gap < 0.8:
                pet._stall_logged = False
            # 模态窗口（聊天输入、改 API Key、重置确认…）开着的时候主线程在跑
            # 嵌套事件循环，一切正常；千万不能把"用户正在打字"当成卡死。
            if getattr(pet, "_modal_depth", 0) > 0:
                pet._stall_logged = False
                self._restarted = False
                continue
            if gap >= self.WARN_S and not getattr(pet, "_stall_logged", False):
                pet._stall_logged = True
                self._log("主线程 %.1f 秒没有心跳" % gap)
            if gap >= self.RESCUE_S:
                try:
                    pet._watch_rescue()
                except Exception:               # noqa: BLE001
                    import traceback
                    self._log(traceback.format_exc())
            if gap >= self.RESTART_S and getattr(pet, "auto_restart", False):
                if not self._restarted:
                    self._restarted = True
                    self._restart(gap)

    def _restart(self, gap):
        if "--selftest" in sys.argv or os.environ.get("PET_RELAUNCHED") == "1":
            self._log("卡死 %.0f 秒；测试进程/重启后的进程里不再自动重启" % gap)
            return
        self._log("主线程卡死 %.0f 秒，重启桌宠进程" % gap)
        try:
            import traceback
            frames = sys._current_frames()
            parts = ["线程堆栈（%d 个线程）:" % len(frames)]
            for tid, frame in frames.items():
                parts.append("---- thread %s" % tid)
                parts.extend(line.rstrip("\n")
                             for line in traceback.format_stack(frame))
            self._log("\n".join(parts))
        except Exception:                       # noqa: BLE001
            pass
        cmd = self._replacement_cmd()
        if cmd is None:
            return
        try:
            import subprocess
            env = os.environ.copy()
            env["PET_RELAUNCHED"] = "1"
            subprocess.Popen(cmd, cwd=ROOT, env=env, close_fds=True,
                             creationflags=0x00000008 | 0x00000200)
        except Exception:                       # noqa: BLE001
            import traceback
            self._log("重启失败：\n" + traceback.format_exc())
            return
        # 新进程已经起来了：卡住的主线程没有别的办法收尾，直接硬退出
        os._exit(0)

    def _replacement_cmd(self):
        argv = list(sys.argv[1:])
        if FROZEN:
            return [sys.executable] + argv
        script = os.path.abspath(sys.argv[0]) if sys.argv else ""
        if not script.lower().endswith(".py"):
            script = os.path.abspath(__file__)
        return [sys.executable, script] + argv


class DesktopPet:
    FRAME_MS = 40
    BREATH_FRAMES = 9
    JUMP_PX = 64
    HEADROOM = 260       # 窗口顶部留白：给拉长、跳动、旋转留空间（实际立绘位置不变）
    # 立绘原始 420px 宽，在 1920 宽的桌面上太大，默认缩到一半
    SCALES = (0.40, 0.50, 0.60, 0.75, 1.0)
    DEFAULT_SCALE = 0.50
    # 被"快速下滑"压扁的判定：0.25 秒内下滑这么多像素、速度够快、方向够竖直
    swipe_min_px = 70
    swipe_window_s = 0.25        # 上面那 70px 要在这个时间内划完才算"快速"
    swipe_speed = swipe_min_px / swipe_window_s      # 280 像素/秒
    squash_floor = 0.62          # 最扁时纵向只剩 62%
    SQUASH_DECAY = 0.11          # 回弹速度

    # 摸头弹幕 + 打飞机：只有"会这个特技"的形象才有。
    # 以前只认文件名（chm 开头），现在按人设判断，换张图也照样会。
    DANMAKU_PERSONAS = ("闷骚少年", "骚话少年")
    DANMAKU_PREFIXES = ("chm",)   # 兼容老图：文件名 chm 开头也算（人设没登记时）

    # 摸头：鼠标在头顶左右来回蹭。两笔反向、各够长就触发
    PET_STROKE_MIN_PX = 14       # 单笔至少这么长，防止手抖
    PET_RUB_MIN_PX = 42          # 一来一回的总位移
    PET_RUB_WINDOW_S = 1.10      # 这几笔要在这么短的时间里完成
    PET_HOLD_S = 2.40            # 触发后至少摸这么久
    PET_ENERGY_RISE = 11.0       # 状态进入速度（越大越快）
    PET_ENERGY_FALL = 4.0        # 收手后慢慢停下来
    PET_FRAME_MS = 30            # 摸头/爱心期间提到 ~33fps，动画更顺

    def __init__(self, image=None, bubble=None, style="auto", scale=None,
                 api_key=None, model=None, use_ai=None, topmost=None,
                 image_dir=None):
        """image/bubble/scale/use_ai 传 None 表示"用配置里的"，显式传入才覆盖配置。"""
        self.cfg = self._load_config()
        self.image_dir = image_dir or IMAGE_DIR
        self.images = scan_images(self.image_dir)
        want = image or self.cfg.get("image")
        names = [im.name for im in self.images]
        self.image_name = want if want in names else (
            DEFAULT_IMAGE if DEFAULT_IMAGE in names else names[0])
        self.bubble_enabled = self.cfg.get("bubble", True) if bubble is None else bool(bubble)
        # 颜文字：它自己说的话后面贴一个（模型不掺和，代码按心情补）
        self.kaomoji_enabled = bool(self.cfg.get("kaomoji", True))
        self.want_layered = style == "layered"
        self.force_colorkey = style == "colorkey"
        # 注意：配置里那个 "style" 记的是**上次实际用的后端**，不拿来当意图。
        # 以前它被当成意图读回来，于是"某次不小心用了 layered（整层不显示）"
        # 会被写进配置，之后每次启动都沿用这个看不见的后端 —— 立绘一片空白。
        self.style_pref = style
        # 桌宠永远待在桌面层（贴在所有普通窗口下面），不再有"置顶"这个选项。
        # topmost 参数只为兼容老的调用方保留，传什么都是 False。
        self.topmost = False
        self.click_through = False       # 穿透不存盘：开机总是能点得到
        self.gestures_enabled = bool(self.cfg.get("gestures", True))
        self.click_speak = bool(self.cfg.get("click_speak", True))
        self.auto_restart = bool(self.cfg.get("auto_restart", True))
        self.pause_fullscreen = bool(self.cfg.get("pause_fullscreen", True))
        # 更多设置：气泡停留时长 / 动作幅度 / 手势灵敏度 / 摇一摇刷新 / 开机自启
        try:
            self.bubble_ms = max(1000, min(12000,
                                          int(self.cfg.get("bubble_ms", 4000))))
        except (TypeError, ValueError):
            self.bubble_ms = 4000
        self.anim_level = str(self.cfg.get("anim_level") or "normal")
        self.gesture_sensitivity = str(
            self.cfg.get("gesture_sensitivity") or "normal")
        self.shake_refresh = bool(self.cfg.get("shake_refresh", False))
        self.autostart = bool(self.cfg.get("autostart", False))
        self._shake_angle = 0.0
        self._shake_head_until = 0.0
        self._shake_ready_at = 0.0
        self._shake_track = []
        self._shake_rev = 0
        self._last_squash_at = 0.0
        self._press_at = 0.0
        self._hold_petted = False
        self.press_pos = None            # 按下时的 (x, y, win_x, win_y)
        self.moved = False
        self._apply_gesture_tuning()
        self._alive = True
        self.visible = True              # 桌面宠物：当前有没有被别的窗口完全盖住
        self.scale = self._pick_scale(scale if scale is not None else self.cfg.get("scale"))

        # AI：优先级 命令行 > 配置 > 环境变量 > 内置 key
        self.ai_enabled = (bool(self.cfg.get("ai", True)) if use_ai is None
                           else bool(use_ai))
        key = (api_key or self.cfg.get("api_key")
               or os.environ.get(ai_client.ENV_KEY))
        if not key:
            key = BUILTIN_API_KEYS          # 内置两个，轮换分担压力
        elif isinstance(key, str) and key.strip() == BUILTIN_API_KEY:
            key = BUILTIN_API_KEYS          # 旧配置里只存了原 key -> 自动带上新 key
        self.brain = ai_client.PetBrain(
            api_key=key, model=model or self.cfg.get("model") or DEFAULT_MODEL,
            on_context=self._context_from_worker)
        self.brain.restore(self.cfg.get("brain"))
        self._ai_lanes = set()       # 正在进行的 AI 请求（chatter / chat / summary）
        self._callbacks = queue.Queue()   # 工作线程 -> 主线程的回调
        self._speech_seq = 0         # 说话权：每次说话 +1，旧的闲话回复自动作废
        self._owned_epoch = 0        # 用户发起过多少次对话请求
        self._owned_shown = 0        # 已经回复到第几次了
        self.pending = None          # 正在等待回复时，气泡上显示的占位文本
        self.prefetched = None       # 后台备好的待机用语，点一下就能显示
        self._next_visible_check = 0.0
        # 被"快速下滑"压扁的动画：squash 从 1 回落到 0
        self.squash = 0.0
        self._swipe = []             # 最近的鼠标采样 (时间, x, y)
        self._mouse_hook = None
        # 全局钩子回调在钩子线程里跑：只能往这个队列里塞采样，Tk 一律碰不得
        # （跨线程调 Tcl 会 0xC0000409 直接把进程打死）。主线程每帧取走。
        self._hook_samples = collections.deque(maxlen=128)
        # 摸头：手势状态 + 平滑动画状态
        self._pet_prev = None        # 上一个落在头顶的采样 (t, x, y)
        self._pet_dir = 0            # 当前这一笔往左(-1)还是往右(+1)
        self._pet_stroke = 0.0       # 当前这一笔已经划了多远
        self._pet_strokes = []       # 已经划完的笔画 [(时间, 距离)]
        self._pet_last_seen = 0.0    # 光标最后一次在头顶的时间
        self._pet_energy = 0.0       # 0..1，摸头的整体强度（平滑过渡）
        self._pet_sway = 0.0         # 跟手摆动的当前值
        self._pet_sway_target = 0.0
        self._pet_press = 0.0        # 0..1，被摸时一下一下往下缩的节拍
        self._pet_kick = 0.0         # 每一笔蹭过来的短促下压（会衰减）
        self._pet_angle = 0.0        # 整个人往手边歪的角度（度）
        self._pet_dx = 0.0           # 这一帧额外加的偏移
        self._pet_dy = 0.0
        self._pet_puff_t = 0.0       # 上一次补爱心的时间，别刷屏
        self._pet_last_x = 0.0       # 光标最后一次在头顶的 x
        self._pet_burst_pending = 0  # 待补的爱心数（下一帧在主线程里真的画）
        self._pet_sparkle_pending = 0  # 待补的小星星数
        self._pet_pat_points = []    # 待画的"啪"圈位置（x 坐标）
        # 额外手势：上划跳、身体横划躲、绕圈转晕
        self._body_track = []        # 身体区域的鼠标采样 (时间, x, y)
        self._circle_track = []      # 绕圈采样 (时间, 角度, 半径)
        self._shake_track = []       # 摇一摇采样 (时间, x)
        self._gesture_hits = {"squash": 0, "jump": 0, "dodge": 0,
                              "spin": 0, "shake": 0, "bounce": 0,
                              "hold": 0}   # 验收用计数
        self._circle_last_seen = 0.0
        self._circle_last_xy = None   # 上一笔采样坐标（不动就不重复记）
        self._last_extra_gesture = 0.0
        self._extra_sparkle_pending = 0
        self._dodge_until = 0.0
        self._dodge_dir = 0
        self._dodge_phase = 0.0
        self._dodge_dx = 0.0
        self._spin_until = 0.0
        self._spin_dir = 1
        self._spin_phase = 0.0
        self._spin_angle = 0.0
        self._spin_star_t = 0.0
        self.spin_count = 0
        # 打飞机（chm 专属）
        self.shooting_until = 0.0
        self._shoot_energy = 0.0
        self._shoot_kick = 0.0
        self._shoot_phase = 0.0
        self._shoot_home_x = None
        self._shoot_lean = 0.0
        self.shoot_count = 0
        self.petting_until = 0.0     # 摸头状态持续到什么时候
        self.petting_count = 0       # 触发过多少次（自检用）
        self._last_tick = self._now()
        self._next_gc = 0.0          # 下一次主线程手动 GC 的时间
        self._pending_actions = []   # 菜单里点的动作，排队到下一次 tick 执行
        self._busy_action = False
        self._in_tick = False        # 当前是否正在 _tick_body 里
        self._tick_job = None        # 主循环的 after id（刷新时要用）
        self._modal_depth = 0        # 正在等哪个模态窗口（>0 时看门狗别急着救）
        self._refresh_requested = False   # 等下一次 tick 完整刷新一遍
        self._refresh_quiet = False
        self._stall_logged = False        # 看门狗：这次卡顿是否已经记过日志
        self._rescue_at = 0.0             # 看门狗上次急救的时间
        self._rescue_hwnds = []           # 可以安全发消息的窗口（只在主线程更新）
        self._bubble_hwnd = 0             # 气泡句柄的 int 副本（看门狗线程只读这个）
        self._hwnd_refresh_at = 0.0
        self.settings_win = None          # 设置窗口（单开）
        self._fs_paused = False           # 前台全屏窗口时暂停（不跑动画、不冒气泡）
        self._fs_hwnd = 0                 # 触发暂停的那个全屏窗口
        self._next_fs_check = 0.0
        self._pending_lower = False  # 启动时等窗口映射后再压层级
        self._pos_check_until = 0.0  # 头一两秒核对窗口真实位置
        self._next_lower = 0.0       # 定时把窗口重新压回最底层
        self.opacity = 1.0           # 不透明度：每次启动都是 100%
        self.affection = AFFECTION_START
        try:
            if self.cfg.get("affection") is not None:
                self.affection = max(0, min(100, int(self.cfg["affection"])))
        except (TypeError, ValueError):
            self.affection = AFFECTION_START
        self.chat_win = None         # 常驻聊天窗口（开着的时候）
        # 恋爱状态：好感度满 100 时点「♡ 恋爱」触发；目前只对陈瀚铭这套人设开放，
        # 存在人设的槽里（见 _stash_persona / _apply_persona）
        self.romance = bool(self.cfg.get("romance"))
        # 情绪状态机：日常 / 吃醋 / 冷战（见 pet_mood.py）。它只决定"怎么说话"，
        # 不改好感度数值；跟人设存在一起，切形象各气各的。
        self.mood = pet_mood.MoodEngine()
        # 音乐：music/ 里的歌自己选，播放时头顶气泡报歌名
        self.music = pet_music.MusicPlayer()
        # 在线电台专用：MCI 打开流会阻塞 25 秒以上，所以它跑在自己的线程里，
        # 这里只发命令、读状态（见 pet_music.StreamPlayer）
        self.stream = pet_music.StreamPlayer()
        self.music_files = pet_music.scan_music(MUSIC_DIR)
        self.music_name = ""          # 当前（或上次）那一首的文件名
        self.music_paused = False
        self.music_volume = 60
        # 在线电台：music_online 为真时 music 放的是网络流；radio_list 是当前
        # 这一批台（切台在上面的列表里绕圈），radio_station 是正在放的那个。
        self.music_online = False
        self.radio_station = None
        self.radio_list = []
        self.radio_index = -1
        self._radio_retry = 0
        self._radio_dialog = None
        self._radio_tick_at = 0.0
        try:
            mcfg = self.cfg.get("music") or {}
            self.music_name = str(mcfg.get("file") or "")
            self.music_volume = max(0, min(100, int(mcfg.get("volume", 60))))
            online = mcfg.get("online") or {}
            url = str(online.get("url") or "")
            if url.lower().startswith(("http://", "https://")):
                self.radio_station = {"name": str(online.get("name") or "在线电台"),
                                      "url": url}
                self.music_name = self.radio_station["name"]
        except (TypeError, ValueError, AttributeError):
            self.music_volume = 60
        self._music_next_check = 0.0
        self._music_bubble_wanted = False   # 放歌时头顶那个"歌名+按钮"常驻气泡
        self._music_bubble_at = 0.0         # 别的气泡消失后，隔一会儿再挂回来
        try:
            os.makedirs(MUSIC_DIR, exist_ok=True)
        except OSError:
            pass
        # 每个形象有自己的 AI 人设和记忆/好感度（见 _apply_persona）
        self._persona = persona_key_for(self.image_name, self.cfg)
        self._persona_state(self._persona)          # 沿用配置里的当前状态

        self.root = tk.Tk()
        self.root.title(APP_NAME)
        set_overrideredirect(self.root, True)
        # 宠物本体不进任务栏（避免和下面那个"任务栏入口"重复出现）
        set_taskbar_button(self.root, False)
        # 回调里漏出来的异常也要落盘，不然菜单点了没反应 / 宠物突然不动
        # 这类问题在 pythonw 下一点痕迹都没有
        self.root.report_callback_exception = self._report_callback_exception
        # 桌面宠物默认压在所有窗口下面（自己会按需置底），--topmost 才浮在最上
        self.root.attributes("-topmost", bool(self.topmost))

        active = self._active_image()
        # 先建一层占位画布，后端确定后再决定用不用它
        self.canvas = tk.Canvas(self.root, width=1, height=1, highlightthickness=0,
                                bd=0, bg=active.key or "#ffffff")
        self.canvas.pack()

        auto = self._style_for(active)
        self.backend = make_window_backend(self, auto)
        self.layered = self.backend.style == "layered"
        self.sprite = sprite_for(active, self.layered)
        self._apply_size()
        self._build_frames()

        self.win_x = 0
        self.win_y = 0
        if self.layered:
            # 内容完全由 UpdateLayeredWindow 画（坐标是相对父窗口的，所以宿主必须
            # 呆在原点附近，不能挪到 -4000 那种地方）。把 Tk 宿主缩到 1x1，
            # 它就被宠物自己盖住，也不会留下一个空方块。
            self.root.geometry("1x1+0+0")
        else:
            self.canvas.configure(width=self.win_w, height=self.win_h)
        self._mount_sprite()
        self.backend.apply_key(active.key or "#ffffff")

        self.bubble = None
        if self.bubble_enabled:
            self.bubble = SpeechBubble(self.root, active.key or "#ffffff")
        self.hearts = HeartFX(self)
        self.danmaku = DanmakuFX(self)
        self.shoot_fx = ShootFX(self)

        # 动画状态
        self.offset = [0.0, 0.0]
        self.target = [0.0, 0.0]
        self._last_dy = 0.0
        self.phase = random.uniform(0, math.tau)
        self.jump = 0.0
        self.started = self._now()
        self.next_shift = self._now() + random.uniform(2.0, 4.5)
        self.next_talk = self._now() + random.uniform(30, 70)
        self._place_initial()
        # 压层级等第一个 tick 再做：这时候窗口真的映射出来了，SetWindowPos
        # 不会把还没生效的 wm geometry 吃掉（否则宠物会蹲在屏幕左上角）
        self._pending_lower = True
        # 自定义人设：存在配置里，启动时注册回 ai_client（菜单、提示词、语气表同一套）
        self.custom_personas = {}
        self.persona_editor = None
        self._load_custom_personas()
        self._build_menu()
        # 只挂托盘图标（右下角「^」里）；拿不到也不在任务栏留按钮
        self._install_tray()
        # 开机就套用当前形象的人设（窗口/位置都已就绪，_save_config 能用了）
        self._apply_persona(load=True)
        self._install_mouse_hook()
        # 不透明度：每次启动都从 100% 开始（配置里不记这个值）
        self.set_opacity(1.0, quiet=True)
        self._tick()
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self._maybe_greet()
        # 心跳看门狗最后启动：卡死时它只读 _last_tick / _alive / auto_restart
        self._watchdog = PetWatchdog(self)
        self._watchdog.start()

    # ------------------------------------------------------------ 素材
    def _build_frames(self):
        """预热呼吸帧：把呼吸位移预先烘进图像，运行时零开销。"""
        step = max(1, int(round(3 * self.scale)))
        self.frames = self.sprite.frames(self.BREATH_FRAMES, self.scale,
                                         lambda i: (0, -i * step))

    # ------------------------------------------------------------ 尺寸
    @classmethod
    def _pick_scale(cls, value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return cls.DEFAULT_SCALE
        if not 0.15 <= value <= 2.0:
            return cls.DEFAULT_SCALE
        # 吸附到预设档位，方便菜单里显示选中项
        return min(cls.SCALES, key=lambda s: abs(s - value))

    def _sprite_img(self):
        return self.sprite.scaled(self.scale, self._squash_factor(),
                                  self._wide_factor())

    def _squash_factor(self):
        """当前这一帧的纵向压缩系数（1.0 = 没被压）。

        摸头时额外轻轻往下压一点（不超过 5%），和"被快速下滑压扁"叠加。
        量化到 1% 是为了让 Sprite.scaled 的缓存真的命中：每帧一个 0.001
        的细碎变化会把缓存塞满、反而更卡。
        """
        factor = 1.0 - (1.0 - self.squash_floor) * self.squash
        # 摸头时跟着节拍一下一下往下缩；比"被划一下"轻，但看得见
        factor *= 1.0 - (0.045 + 0.065 * self._pet_press) * self._pet_energy
        # 打飞机：整个人往上拉长，开枪时再抖一下
        factor *= 1.0 + 0.38 * self._shoot_energy + 0.04 * self._shoot_kick
        return max(0.5, min(1.48, round(factor, 2)))

    def _wide_factor(self):
        """横向系数：打飞机时变窄，配合纵向拉长就是"拉长变扁"。"""
        factor = 1.0 - 0.30 * self._shoot_energy - 0.03 * self._shoot_kick
        return max(0.62, min(1.0, round(factor, 3)))

    def _apply_size(self):
        """按缩放档位算窗口尺寸（精灵窗口 + 顶部给呼吸/跳跃留的余量）。"""
        # 只按缩放算，不要用 _sprite_img()：它带着当前的压扁系数，回弹动画
        # 还没走完时改大小会把窗口钉成"压扁后的高度"，宠物顶部被裁掉
        self.sw, self.sh = self.sprite.scaled(self.scale).size
        self.headroom = max(4, int(round(self.HEADROOM * self.scale)))
        # 摸头时整个人会左右歪几度：colorkey 的图是画在 Tk 画布上的，
        # 画布外会被裁掉，所以左右多留一点透明边（layered 不受窗口裁剪）。
        margin = 0 if self.layered else max(12, int(round(self.sw * 0.40)))
        self.win_w = self.sw if self.layered else self.sw + margin
        self.win_h = self.sh + self.headroom
        self.headroom_x = 0 if self.layered else (self.win_w - self.sw) // 2
        self.jump_px = max(6, int(round(self.JUMP_PX * self.scale)))

    def set_scale(self, scale):
        if abs(scale - self.scale) < 1e-6:
            return
        old_scale = self.scale
        try:
            self._set_scale_impl(scale)
        except Exception:                   # noqa: BLE001 - 改大小失败不该拖垮程序
            _log_exception()
            # 退回原来的档位，至少让界面状态和实际显示一致
            self.scale = old_scale
            try:
                self._apply_size()
                self._build_frames()
                if not self.layered:
                    self.canvas.configure(width=self.win_w, height=self.win_h)
                    self._mount_sprite()
                self._redraw()
            except Exception:                # noqa: BLE001
                _log_exception()
            if abs(self.scale_var.get() - self.scale) > 1e-6:
                self.scale_var.set(self.scale)
            self.speak("这个大小先不换了。")

    def _set_scale_impl(self, scale):
        # 以底边中点为锚点缩放，脚不会因为改大小而跳走
        anchor = self.anchor()
        self.scale = self._pick_scale(scale)
        self._apply_size()
        self._build_frames()
        if not self.layered:
            self.canvas.configure(width=self.win_w, height=self.win_h)
            self._mount_sprite()
        self.backend.show(self._sprite_img())
        # 一定要 clamp：在屏幕上半部分放大时 "锚点 - 新高度" 会把窗口推到屏幕
        # 上方外面去（宠物看着就像消失了）
        self.move(anchor[0] - self.win_w // 2, anchor[1] - self.win_h, clamp=True)
        self._redraw()
        self._save_config()
        self.sync_settings()
        self.speak("这个大小还合适吗？")

    def _mount_sprite(self):
        """colorkey 后端把图挂到画布上。

        不 delete + 重建画布 item：itemconfigure 换图就够了，反复删建反而
        多出没必要的 Tk 图片/C 层分配（换形象时最怕的就是这条路径）。
        """
        self.backend.show(self._sprite_img())

    def _frame_for_phase(self):
        t = (1.0 - math.cos(self.phase * 0.5)) / 2.0      # 0..1，来回摆动
        idx = int(round(t * (self.BREATH_FRAMES - 1)))
        return self.frames[idx]

    # ------------------------------------------------------------ 配置
    def _load_config(self):
        # utf-8-sig：用户用记事本/某些编辑器改过配置就会存成带 BOM 的 UTF-8，
        # 那种文件用 "utf-8" 读会在开头留一个 \ufeff，json.load 直接抛异常，
        # 结果是**整份配置被当成读不到**、静默回到默认值（形象/大小/位置全丢）。
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8-sig") as fh:
                cfg = json.load(fh)
                if isinstance(cfg, dict):
                    return cfg
        except Exception:
            pass
        return {}

    def _save_config(self):
        if getattr(self, "_shoot_home_x", None) is not None:
            # 打飞机追飞机时窗口临时滑走了，存档仍按原位存
            cx = int(self._shoot_home_x) + self.win_w // 2
            base = self.win_y + self.win_h
        else:
            cx, base = self.anchor()
        self.cfg.update({"image": self.image_name, "bubble": self.bubble_enabled,
                         "x": cx, "y": base,
                         "scale": self.scale, "style": self.backend.style,
                         "gestures": bool(self.gestures_enabled),
                         "click_speak": bool(self.click_speak),
                         "auto_restart": bool(self.auto_restart),
                         "pause_fullscreen": bool(self.pause_fullscreen),
                         "bubble_ms": int(self.bubble_ms),
                         "anim_level": self.anim_level,
                         "gesture_sensitivity": self.gesture_sensitivity,
                         "shake_refresh": bool(self.shake_refresh),
                         "autostart": bool(self.autostart),
                         "ai": self.ai_enabled, "model": self.brain.model,
                         "context": self.brain.context,
                         "affection": self.affection,
                         "romance": self.romance,
                         "brain": self.brain.export(),
                         "kaomoji": self.kaomoji_enabled,
                         "custom_personas": dict(
                             getattr(self, "custom_personas", {}) or {}),
                         "web_links": [dict(x) for x in (self.cfg.get("web_links") or [])
                                       if isinstance(x, dict)],
                         "music": {"file": "" if self.music_online else self.music_name,
                                   "volume": self.music_volume,
                                   "online": ({"name": self.radio_station.get("name", ""),
                                               "url": self.radio_station.get("url", "")}
                                              if (self.music_online and self.radio_station)
                                              else {})}})
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(self.cfg, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ------------------------------------------------------------ 位置
    def clamp_pos(self, x, y):
        """把坐标夹回桌面：至少留一角在屏幕里，但整体不许沉到任务栏下面。"""
        left, top, right, bottom = work_area(self.root)
        x = max(left - self.win_w + 36, min(right - 36, x))
        y = max(top, min(bottom - 24, y))
        return int(x), int(y)

    def _place_initial(self):
        """开机位置：**右下角**（固定，不恢复上次拖到的地方）。

        用户要求"一打开就要出现在右下角"。而且恢复上次位置还有个坑：旧配置里
        的坐标会把默认位置顶掉 —— 之前有过一版默认生成在右上角，那个坐标被存
        进 pet_config.json 之后，即使代码改回右下角，打开还是右上角。
        """
        left, top, right, bottom = work_area(self.root)
        self.root.update_idletasks()
        self.move(*self.bottom_right_pos())
        # 位置还没真正落到窗口上（Tk 的 wm geometry 要等事件循环），
        # 让 _tick 在头一两秒里核对并纠正 —— 否则紧接着的压层级调用
        # （SetWindowPos 会吃掉待处理的几何）会把宠物留在 (0,0) 左上角
        self._pos_check_until = self._now() + 2.0

    def bottom_right_pos(self):
        """右下角的坐标（离右边 SPAWN_MARGIN，脚踩工作区下沿）。"""
        left, top, right, bottom = work_area(self.root)
        return self.clamp_pos(right - self.win_w - SPAWN_MARGIN,
                              bottom - self.win_h)

    def anchor(self):
        """底边中点（缩放时用它当锚点）。"""
        return (self.win_x + self.win_w // 2, self.win_y + self.win_h)

    def _redraw(self):
        """把当前帧按当前位置重画一遍（layered 后端需要显式喂图）。"""
        if not self.layered:
            return
        image, (fx, fy) = self._frame_for_phase()
        self.backend.set_frame(image, fx, fy)

    # ------------------------------------------------------------ 被划一下
    def _install_mouse_hook(self):
        """尝试全局鼠标钩子（能拿到"宠物被别的窗口盖住时"的划过动作）。

        实测这台机器上 LowLevel 钩子装得上但**收不到回调**（装着管控软件，
        钩子链被占了），所以钩子只当加速器：真正兜底的是 _tick 里按帧轮询
        GetCursorPos —— 不依赖任何钩子，25fps 采样足够看出一次快速下滑。
        """
        if os.environ.get("PET_NO_MOUSE_HOOK"):
            self._mouse_hook = None
            return
        hook = MouseHook(self._on_hook_move)
        if hook.install():
            self._mouse_hook = hook

    def _on_hook_move(self, x, y):
        """全局钩子回调（钩子线程）：记下采样就走人，不碰 Tk、不画图。

        这里是整个程序最危险的地方 —— 它在系统钩子线程里执行，只要碰一下
        Tk（哪怕只是读 winfo_*），Tcl 就会因为跨线程而 abort。采样交给主线程
        的 _poll_cursor 处理，时间戳也一并带上，动作判定才不会被压缩。
        """
        try:
            self._hook_samples.append((time.monotonic(), x, y))
        except Exception:                       # noqa: BLE001
            pass

    def _poll_cursor(self):
        """每个动画帧读一次光标位置，喂给同一个划过判定。"""
        if _user32 is None or not self.gestures_enabled:
            return
        # 钩子线程攒下的采样先处理（时间戳用它自己的，别都压成"现在"）
        while True:
            try:
                stamp, hx, hy = self._hook_samples.popleft()
            except IndexError:
                break
            self._on_mouse_move(hx, hy, stamp)
        pt = wintypes.POINT()
        if _user32.GetCursorPos(ctypes.byref(pt)):
            self._on_mouse_move(pt.x, pt.y)

    def _on_mouse_move(self, x, y, now=None):
        """记录鼠标轨迹，发现快速下滑就压一下、快速上划就跳一下。

        采样是 (时间, x, y)，别把下标搞混：oldest[1] 是 x，oldest[2] 才是 y。

        判定只看"最近 0.18 秒"这一小段：手一快就当场有反应，不用等攒够一整段
        位移（那样手感就是"有延迟"）；也不会被"从屏幕另一头甩过来"的那几百
        像素带偏（old 版按 0.4 秒整段算，甩过来再划经常判不出来）。
        """
        if not self.gestures_enabled:
            # 关掉手势时把轨迹清空：重新打开后从干净的采样开始，
            # 不会拿"关闭前最后一次移动"和"打开后第一次移动"算出一个假划动
            self._swipe = []
            return
        if now is None:
            now = self._now()
        self._swipe.append((now, x, y))
        # 摸头、身体横划躲、绕圈转晕共用同一路光标采样
        self._track_extra_gestures(now, x, y)
        self._track_petting(now, x, y)
        # 只保留最近 0.45 秒的采样
        cutoff = now - 0.45
        while self._swipe and self._swipe[0][0] < cutoff:
            self._swipe.pop(0)
        window = [s for s in self._swipe if now - s[0] <= 0.18]
        if len(window) < 3:
            return
        # 光标刚瞬移过来时，窗口里还留着"在别处"的旧采样；它们会把位移和
        # 方向全带偏，直接从窗口头部丢掉
        while len(window) > 2 and (abs(window[0][1] - x) > 300
                                   or abs(window[0][2] - y) > 300):
            window.pop(0)
        t0, x0, y0 = window[0]
        span = now - t0
        if span <= 0.02:
            return
        dy = y - y0
        dx = abs(x - x0)
        speed = dy / span
        if os.environ.get("PET_GESTURE_DEBUG"):
            print("MM x=%d y=%d n=%d dy=%.0f dx=%.0f speed=%.0f" % (
                x, y, len(window), dy, dx, speed))
        if not self._swipe_touches_pet(x, x0, y0, y):
            return
        if (dy <= -self.swipe_min_px and speed <= -self.swipe_speed
                and dx <= abs(dy) * 0.8):
            self._swipe = []                  # 触发一次就清空，别连发
            self._gesture_hits["jump"] += 1
            self.trigger_jump(now)            # 快速上划 -> 开心地跳一下
            return
        if (dy >= self.swipe_min_px and speed >= self.swipe_speed
                and dx <= dy * 0.8):
            self._swipe = []
            self._gesture_hits["squash"] += 1
            self.squash = 1.0
            # 0.9 秒内连着两次下滑 = 弹一下（压扁 + 跳起来 + 冒爱心）
            if now - self._last_squash_at <= 0.9:
                self._gesture_hits["bounce"] = \
                    self._gesture_hits.get("bounce", 0) + 1
                self.jump = max(self.jump, 0.9)
                try:
                    self.hearts.burst(self.head_anchor(), count=5)
                except Exception:               # noqa: BLE001
                    pass
            self._last_squash_at = now                 # 快速下滑 -> 压扁

    def _swipe_touches_pet(self, x_now, x_old, y_from, y_to):
        """这半个划动轨迹有没有从宠物身上经过（横竖都要沾边）。"""
        left, right = self.win_x, self.win_x + self.win_w
        if max(x_now, x_old) < left or min(x_now, x_old) > right:
            return False
        top, bottom = self.win_y, self.win_y + self.win_h
        lo, hi = min(y_from, y_to), max(y_from, y_to)
        return hi >= top and lo <= bottom

    # ------------------------------------------------------------ 其他手势
    def _in_body_zone(self, x, y):
        """身体中段：在这里快速横划是"躲一下"，不是摸头。"""
        margin_x = max(10, int(self.win_w * 0.12))
        sprite_top = self.win_y + self.headroom
        top = sprite_top + self.sh * self.scale * 0.30
        bottom = self.win_y + self.win_h + 10
        return (self.win_x - margin_x <= x <= self.win_x + self.win_w + margin_x
                and top <= y <= bottom)

    def _gesture_ready(self, now, gap=0.75):
        return now - self._last_extra_gesture >= gap

    def _track_extra_gestures(self, now, x, y):
        # 绕圈先记采样：后面几个判定都要看"手是不是在绕圈"，
        # 采样得先把当前这一笔算进去
        self._track_circle(now, x, y)
        # 摇一摇（来回至少 4 次）判在最前：它本身就是一串横向移动，
        # 要是先判横划躲闪，会被"躲一下"吃掉。
        if self._track_shake_head(now, x, y):
            return
        # 横划躲一下接着判：这一笔最短，最容易被别的判定吃掉
        self._track_body_swipe(now, x, y)

    def _track_shake_head(self, now, x, y):
        """在身上快速左右摇 -> 摇头（设置里可改成刷新）。"""
        if not self._in_body_zone(x, y):
            if self._shake_track and now - self._shake_track[-1][0] > 0.3:
                self._shake_track = []
                self._shake_rev = 0
            return False
        track = self._shake_track
        if track and track[-1][1] == x:          # 手没动：别把静止帧算进时长
            return False
        track.append((now, x, y))
        cutoff = now - 1.0
        while track and track[0][0] < cutoff:
            track.pop(0)
        if len(track) < 6:
            return False
        reversals = 0
        travel = 0.0
        last_dir = 0
        last_x = track[0][1]
        for _t, sx, _sy in track[1:]:
            step = sx - last_x
            travel += abs(step)
            if abs(step) >= 6:
                direction = 1 if step > 0 else -1
                if last_dir and direction != last_dir:
                    reversals += 1
                last_dir = direction
            last_x = sx
        self._shake_rev = reversals
        span = now - track[0][0]
        if (reversals < 4 or travel < max(150.0, self.win_w * 0.9)
                or span > 1.0 or now < self._shake_ready_at
                or now < self.petting_until):
            return False
        self._shake_track = []
        self._body_track = []
        self._shake_ready_at = now + 5.0
        self._gesture_hits["shake"] = self._gesture_hits.get("shake", 0) + 1
        if self.shake_refresh:
            self.request_refresh()
        else:
            self._shake_head(now)
        return True

    def _shake_head(self, now):
        """摇头：0.7 秒里左右摆几下。"""
        self._shake_head_until = now + 0.7
        self.speak("别、别摇啦～", background=True)

    def _track_body_swipe(self, now, x, y):
        """在身体上快速横划 -> 往反方向躲一下。"""
        if getattr(self, "_shake_rev", 0) >= 2:
            # 正在左右摇（方向已经在反转）：那是"摇一摇"，不是横划躲闪
            return
        if not self._in_body_zone(x, y):
            if self._body_track and now - self._body_track[-1][0] > 0.25:
                self._body_track = []
            return
        self._body_track.append((now, x, y))
        cutoff = now - 0.38
        while self._body_track and self._body_track[0][0] < cutoff:
            self._body_track.pop(0)
        if len(self._body_track) < 3:
            return
        old_t, old_x, old_y = self._body_track[0]
        dt = now - old_t
        if dt <= 0.02:
            return
        dx = x - old_x
        dy = y - old_y
        if (abs(dx) >= max(80, int(self.win_w * 0.42))
                and abs(dx) > abs(dy) * 1.3
                and abs(dx) / dt >= 700.0
                # 手其实是在绕圈的时候别判躲闪：绕圈的上下两段横着走，
                # 也会满足"横着快速划过"，抢了转圈就变成"一直在躲"了
                and self._gesture_ready(now)):
            self._body_track = []
            self._gesture_hits["dodge"] += 1
            self.trigger_dodge(1 if dx > 0 else -1, now)

    def _circle_progress(self):
        """绕圈采样累计转过的角度和时长：(弧度, 秒)。

        角度一大跳（超过 90 度）说明光标直接穿过宠物中心、并不是在绕着转，
        这时候从头重新累计，别把"直线划过去"当成转圈。
        """
        track = self._circle_track
        if len(track) < 5:
            return 0.0, 0.0
        total = 0.0
        prev = None
        for _t, ang in track:
            if prev is not None:
                delta = ang - prev
                while delta > math.pi:
                    delta -= math.tau
                while delta < -math.pi:
                    delta += math.tau
                if abs(delta) <= math.pi / 2.0:
                    # 超过 90 度的一跳 = 采样断了/穿过了宠物中心，这一笔不算，
                    # 但别把已经转过的角度清零（否则永远凑不满一整圈）
                    total += delta
            prev = ang
        return total, track[-1][0] - track[0][0]

    def _track_circle(self, now, x, y):
        """绕宠物画一圈 -> 转晕。"""
        cx = self.win_x + self.win_w / 2.0
        cy = self.win_y + self.win_h - self.sh * self.scale * 0.46
        dx, dy = x - cx, y - cy
        radius = math.hypot(dx, dy)
        min_r = max(28.0, self.win_w * 0.34)
        max_r = max(self.win_w * 0.85, self.sh * self.scale * 0.78)
        if not (min_r <= radius <= max_r):
            if self._circle_track and now - self._circle_last_seen > 0.3:
                self._circle_track = []
            return
        if (x, y) == self._circle_last_xy:
            # 手没动：不重复记采样，也别刷新"刚刚还在动"的时间戳，
            # 否则人停在那儿也会一直算"正在绕圈"，把别的手势压住
            return
        self._circle_last_xy = (x, y)
        self._circle_last_seen = now
        angle = math.atan2(dy, dx)
        self._circle_track.append((now, angle))
        cutoff = now - 1.7
        while self._circle_track and self._circle_track[0][0] < cutoff:
            self._circle_track.pop(0)
        if len(self._circle_track) < 8:
            return
        total, span = self._circle_progress()
        if (abs(total) >= math.pi * 1.2 and span >= 0.30
                and self._gesture_ready(now, 0.0)):
            self._circle_track = []
            self._gesture_hits["spin"] += 1
            self.trigger_spin(1 if total > 0 else -1, now)

    def trigger_dodge(self, direction=1, now=None):
        now = self._now() if now is None else now
        self._last_extra_gesture = now
        self._dodge_until = now + 0.55
        self._dodge_dir = 1 if direction >= 0 else -1
        self._spin_until = 0.0
        self._spin_angle = 0.0
        self.squash = max(self.squash, 0.35)
        self._extra_sparkle_pending += 2

    def trigger_spin(self, direction=1, now=None):
        now = self._now() if now is None else now
        self._last_extra_gesture = now
        self._spin_until = now + 1.45
        self._spin_dir = 1 if direction >= 0 else -1
        self._spin_star_t = now - 1.0
        self.spin_count += 1
        self._extra_sparkle_pending += 6

    def trigger_jump(self, now=None, force=False):
        now = self._now() if now is None else now
        if not force and not self._gesture_ready(now, 0.55):
            return
        self._last_extra_gesture = now
        self.jump = 1.0
        self._extra_sparkle_pending += 3

    def _update_extra(self, now, dt):
        """推进躲闪位移和转圈角度；叠加在摸头/打飞机之上。"""
        if self._extra_sparkle_pending:
            pending, self._extra_sparkle_pending = self._extra_sparkle_pending, 0
            self.hearts.burst(self.head_anchor(), count=min(12, pending),
                              kind="sparkle")
        if now < self._shake_head_until:
            total = 0.7
            p = 1.0 - (self._shake_head_until - now) / total
            self._shake_angle = math.sin(p * math.pi * 7.0) * 15.0 * (1.0 - p)
        else:
            self._shake_angle = 0.0
        if now < self._dodge_until:
            total = 0.55
            p = 1.0 - (self._dodge_until - now) / total
            amp = max(14.0, self.win_w * 0.16)
            self._dodge_dx = -self._dodge_dir * amp * math.sin(math.pi * p)
        else:
            self._dodge_dx = 0.0
        self._pet_dx += self._dodge_dx
        if now < self._spin_until:
            total = 1.45
            p = 1.0 - (self._spin_until - now) / total
            self._spin_angle = (self._spin_dir * math.sin(p * math.pi * 4.0)
                                * 13.0 * (1.0 - p))
            if now - getattr(self, "_spin_star_t", 0.0) > 0.16:
                self._spin_star_t = now
                self.hearts.burst(self.head_anchor(), count=2,
                                  kind="sparkle")
        else:
            self._spin_angle = 0.0
        self._pet_angle += self._spin_angle

    def _note_interaction(self):
        """用户刚碰过它：强制认定"看得见"，并推迟一次遮挡复查。

        桌宠固定在最底层，check_covered() 偶尔会把"其实看得见"判成被盖住
        （透明工具窗、壁纸层、贴边窗口都会造成这种误判）。人已经点到了它，
        再按"被盖住"把动作吃掉就成了"右键点了没反应"。
        """
        self.visible = True
        self._next_visible_check = self._now() + 6.0
        self._next_lower = self._now() + 6.0

    def do_gesture(self, kind):
        """右键「逗它玩」里的手动手势。"""
        self._note_interaction()
        now = self._now()
        if kind == "head":
            self._start_petting(self.win_x + self.win_w // 2, now)
            self._pet_last_seen = now
            self._pet_last_x = self.win_x + self.win_w // 2
        elif kind == "jump":
            self.trigger_jump(now, force=True)
        elif kind == "squash":
            self.squash = 1.0
            self._last_extra_gesture = now
        elif kind == "spin":
            self.trigger_spin(1, now)
        elif kind == "dodge":
            self.trigger_dodge(1 if random.random() < 0.5 else -1, now)
        elif kind == "shoot":
            self.trigger_shooting()

    # ------------------------------------------------------------ 打飞机
    def trigger_shooting(self):
        """右键「打飞机」：只有会特技的形象（陈瀚铭 / 郑迪隆）会。"""
        if not self.has_special_skill():
            self.speak("这个特技只有陈瀚铭和郑迪隆会。")
            return
        now = self._now()
        self.shooting_until = now + 3.4
        self._shoot_energy = 0.0
        self._shoot_kick = 0.0
        self._shoot_phase = 0.0
        self.petting_until = 0.0
        self.squash = 0.0
        self.shoot_count += 1
        self._shoot_home_x = self.win_x
        self._shoot_lean = 0.0
        self.shoot_fx.start()

    def shooting_active(self, now=None):
        now = self._now() if now is None else now
        return bool(now < self.shooting_until
                    or self._shoot_energy > 0.01
                    or (getattr(self, "shoot_fx", None) is not None
                        and self.shoot_fx.active()))

    def on_shot(self):
        """ShootFX 每发射一颗子弹时回调：身体抖一下（后坐力）。"""
        self._shoot_kick = 1.0

    def _move_shooting_to(self, desired, dt, rate=5.0):
        """打飞机时平滑滑到目标 x（脚底 y 不动）。"""
        left, _top, right, _bottom = work_area(self.root)
        desired = max(left, min(right - self.win_w, desired))
        k = min(1.0, max(0.02, rate * dt))
        new_x = self.win_x + (desired - self.win_x) * k
        if abs(new_x - self.win_x) >= 0.5:
            self.win_x = int(round(new_x))
            self.backend.move(self.win_x, self.win_y)

    def _restore_shoot_home(self):
        """取消/退出打飞机时，把滑出去的宠物放回原位。"""
        home = getattr(self, "_shoot_home_x", None)
        if home is None:
            return
        self.win_x = int(home)
        self._shoot_home_x = None
        try:
            self.backend.move(self.win_x, self.win_y)
        except Exception:                       # noqa: BLE001 - 退出途中窗口可能已销毁
            pass

    def _update_shooting(self, now, dt):
        target = 1.0 if now < self.shooting_until else 0.0
        rate = 8.0 if target > self._shoot_energy else 3.2
        self._shoot_energy += (target - self._shoot_energy) * (
            1.0 - math.exp(-rate * dt))
        if self._shoot_energy < 0.001:
            self._shoot_energy = 0.0
        self._shoot_kick = max(0.0, self._shoot_kick - 7.0 * dt)
        self._shoot_phase += dt * 11.0

        # 自己滑到飞机下面锁定；打完再滑回原位
        self._shoot_lean = 0.0
        home = self._shoot_home_x
        if home is not None:
            if now < self.shooting_until:
                target_x = self.shoot_fx.lock_x(
                    self.win_x + self.win_w / 2.0)
                if target_x is not None:
                    desired = target_x - self.win_w / 2.0
                    limit = max(100.0, self.win_w * 1.5)
                    desired = max(home - limit, min(home + limit, desired))
                    self._move_shooting_to(desired, dt, 6.0)
                    center = self.win_x + self.win_w / 2.0
                    self._shoot_lean = max(
                        -4.5, min(4.5, (target_x - center)
                                  / max(24.0, self.win_w * 0.45)))
                else:
                    self._move_shooting_to(home, dt, 3.0)
            else:
                self._move_shooting_to(home, dt, 3.5)
                if abs(self.win_x - home) <= 3:
                    self.win_x = int(home)
                    self.backend.move(self.win_x, self.win_y)
                    self._shoot_home_x = None
        self._pet_angle += self._shoot_lean

    def muzzle_pos(self):
        """枪口 = 当前立绘头顶偏下的位置（打飞机时子弹从这里出）。"""
        img = self._sprite_img()
        bbox = self.sprite.content_bbox()
        scale = self.scale
        factor = self._squash_factor()
        top = self.win_y + self.win_h - 2 - img.height + self._pet_dy
        content_top = bbox[1] * scale * factor
        x = (self.win_x + self.win_w / 2.0
             + self.offset[0] + self._pet_dx)
        y = top + content_top
        return (x, y)

    # ------------------------------------------------------------ 摸头
    def _in_head_zone(self, x, y):
        """(x, y) 是不是在头顶那一块（左右可以稍微超出窗口一点）。

        不同立绘的头部位置不一样，但都是"人像"，头顶一定在图片上沿往下
        三分之一以内；横向放宽一点是为了让手蹭到边缘也算摸到。
        """
        margin_x = max(10, int(self.win_w * 0.10))
        sprite_top = self.win_y + self.headroom
        top = sprite_top - max(6, int(round(10 * self.scale)))
        bottom = sprite_top + self.sh * 0.34
        return (self.win_x - margin_x <= x <= self.win_x + self.win_w + margin_x
                and top <= y <= bottom)

    def _pet_reset_gesture(self):
        """手势断开：重新进头顶时不会把上一次的半笔接起来。"""
        self._pet_prev = None
        self._pet_dir = 0
        self._pet_stroke = 0.0
        self._pet_strokes = []

    def _track_petting(self, now, x, y):
        """判定"在头顶左右来回蹭"。

        只看水平方向：每一笔（同一个方向）要够长，且至少有一笔反方向，
        两笔加起来超过阈值才触发。单次从头顶横着划过去（没有回头）不会
        误触发；划出去再回来会重新起一笔。
        """
        if now < self._spin_until or now < self.shooting_until:
            return
        if not self._in_head_zone(x, y):
            # 手滑出头顶一点点不算中断；离开久了才清零
            if now - self._pet_last_seen > 0.25:
                self._pet_reset_gesture()
            return
        self._pet_last_seen = now
        self._pet_last_x = x
        prev = self._pet_prev
        self._pet_prev = (now, x, y)
        if prev is None:
            return
        dt = now - prev[0]
        if dt <= 0.0 or dt > 0.30:          # 中间停过 / 时间戳倒了
            self._pet_reset_gesture()
            return
        dx = x - prev[1]
        dy = y - prev[2]
        # 只认"基本在横着动"的采样，斜着拖动宠物不该触发摸头
        if abs(dx) < 2.5 or abs(dx) < abs(dy) * 1.15:
            return
        direction = 1 if dx > 0 else -1
        reversed_now = False
        if self._pet_dir == 0:
            self._pet_dir = direction
            self._pet_stroke = abs(dx)
        elif direction == self._pet_dir:
            self._pet_stroke += abs(dx)
        else:
            # 方向反了：先把上一笔结算掉
            reversed_now = True
            if self._pet_stroke >= self.PET_STROKE_MIN_PX:
                self._pet_strokes.append((now, self._pet_stroke))
            self._pet_dir = direction
            self._pet_stroke = abs(dx)
        # 只保留时间窗里的笔画
        while (self._pet_strokes
               and now - self._pet_strokes[0][0] > self.PET_RUB_WINDOW_S):
            self._pet_strokes.pop(0)
        # 跟手：光标在头的左半边就往左靠，右半边往右靠
        center = self.win_x + self.win_w / 2.0
        self._pet_sway_target = max(
            -1.0, min(1.0, (x - center) / max(1.0, self.win_w * 0.5)))
        # 已经在摸：继续蹭就续上状态，每次反向补几颗爱心
        if now < self.petting_until:
            self.petting_until = max(self.petting_until, now + 0.70)
            if reversed_now:
                self._pet_puff(now, x)
            return
        # 两笔（一来一回）都够长 -> 开始摸头
        total = sum(dist for _t, dist in self._pet_strokes) + self._pet_stroke
        if (self._pet_strokes
                and self._pet_stroke >= self.PET_STROKE_MIN_PX
                and total >= self.PET_RUB_MIN_PX):
            self._start_petting(x, now)

    def _start_petting(self, x, now):
        self.petting_until = now + self.PET_HOLD_S
        self.petting_count += 1
        self._pet_last_seen = now
        center = self.win_x + self.win_w / 2.0
        self._pet_sway_target = max(
            -1.0, min(1.0, (x - center) / max(1.0, self.win_w * 0.5)))
        # 第一波爱心/星星多一点，之后靠 update() 持续冒
        self._pet_burst_pending += 6
        self._pet_sparkle_pending += 7
        self._pet_pat_points.append(x)
        self._pet_kick = 1.0
        self._pet_strokes = []
        self._pet_stroke = 0.0
        self._pet_dir = 0

    def _pet_puff(self, now, x):
        """已经摸上头了，再蹭一下时补一小簇爱心/星星和一圈"啪"。"""
        if now - self._pet_puff_t < 0.16:
            return
        self._pet_puff_t = now
        # 只记个数/坐标：这个函数可能跑在全局鼠标钩子回调里，别在这里建窗口/画图
        self._pet_burst_pending += 2
        self._pet_sparkle_pending += 2
        self._pet_pat_points.append(x)
        self._pet_kick = max(self._pet_kick, 0.85)

    def petting_active(self, now=None):
        """摸头状态是否还在（含收手后的平滑收尾）。"""
        now = self._now() if now is None else now
        return bool(self._pet_energy > 0.01 or now < self.petting_until)

    def has_special_skill(self):
        """会不会"摸头弹幕 + 打飞机"：按人设判断（陈瀚铭 / 郑迪隆）。

        老图（文件名 chm 开头、配置里还没登记人设的）也算会，避免升级后
        用户原来的立绘突然不能打飞机了。
        """
        persona = str(getattr(self, "_persona", "") or "").strip()
        if persona in self.DANMAKU_PERSONAS:
            return True
        name = os.path.basename(self.image_name).lower()
        return any(name.startswith(prefix) for prefix in self.DANMAKU_PREFIXES)

    def danmaku_allowed(self):
        """这条形象摸头时会不会冒弹幕（和打飞机是同一批人）。"""
        return self.has_special_skill()

    def danmaku_phrases(self):
        """当前人设的弹幕台词（日文 + 中文两行）。"""
        persona = str(getattr(self, "_persona", "") or "").strip()
        return DANMAKU_PHRASES_BY_PERSONA.get(persona, DANMAKU_PHRASES)

    def _update_petting(self, now, dt):
        """按时间平滑推进摸头动画：整体强度、跟手方向、下压/摆动位移。"""
        if dt <= 0.0:
            dt = self.FRAME_MS / 1000.0
        # 手停在头顶不动时会一直续时间；离开后让状态自然到期
        if now < self.petting_until and now - self._pet_last_seen > 0.35:
            self.petting_until = min(self.petting_until, now + 0.35)
        target = 1.0 if now < self.petting_until else 0.0
        rate = self.PET_ENERGY_RISE if target > self._pet_energy else self.PET_ENERGY_FALL
        self._pet_energy += (target - self._pet_energy) * (
            1.0 - math.exp(-rate * dt))
        if self._pet_energy < 0.001:
            self._pet_energy = 0.0
        # 手离开后，跟手的摆动目标回正，别一直歪着
        if now - self._pet_last_seen > 0.30:
            self._pet_sway_target *= math.exp(-3.0 * dt)
        self._pet_sway += (self._pet_sway_target - self._pet_sway) * (
            1.0 - math.exp(-11.0 * dt))
        # 一下一下往下缩的节拍：0 -> 1 -> 0，用 cos 保证触发瞬间不跳变；
        # 再加上每一笔蹭过来的短促下压，手划一下它就往下缩一下
        self._pet_kick = max(0.0, self._pet_kick - 2.8 * dt)
        self._pet_press = max(0.5 - 0.5 * math.cos(now * 7.2),
                              self._pet_kick)
        # 跟手左右摆：幅度按窗口宽度走，小图也不会只有 1px
        self._pet_dx = (self._pet_sway * self._pet_energy
                        * max(5.0, self.win_w * 0.085))
        # 被摸的时候往下沉，再加上节拍的起伏；底边固定，不会顶出窗口
        drop = max(5.0, self.win_h * 0.050)
        self._pet_dy = self._pet_energy * (
            1.5 + drop * (0.25 + 0.75 * self._pet_press))
        # 跟着手歪一点（正角度 = 逆时针）。再叠一点很小的高频摆动，
        # 看起来是在"蹭"，而不是整块贴图在平移。
        self._pet_angle = (-self._pet_sway * 4.0
                           - math.sin(now * 8.5) * 0.9) * self._pet_energy

    def simulate_pet_head(self, cycles=3, duration=0.42, span=None):
        """模拟在头顶左右蹭（测试用，等价于鼠标真的来回划）。

        返回这次有没有触发摸头。
        """
        cx = self.win_x + self.win_w // 2
        cy = self.win_y + self.headroom + max(4, int(self.sh * 0.12))
        span = span if span is not None else max(34, int(self.win_w * 0.24))
        before = self.petting_count
        steps = max(8, cycles * 8)
        for i in range(steps + 1):
            # 三角波：左 -> 右 -> 左，转身发生在两端，像真的来回蹭
            t = i / 8.0
            tri = abs((t % 2.0) - 1.0)       # 1 -> 0 -> 1
            x = cx + span * (1.0 - 2.0 * tri)
            self._on_mouse_move(x, cy)
            time.sleep(duration / steps)
        return self.petting_count > before

    def _squash_pos(self):
        """压扁时图像顶部应该在窗口里的位置（调试/测试用）。"""
        if self.squash <= 0.001:
            return 0
        squeezed = self.sprite.scaled(self.scale, self._squash_factor(),
                                      self._wide_factor()).size[1]
        return max(0, self.win_h - 2 - squeezed)

    def simulate_swipe(self, duration=0.18, distance=220):
        """模拟一次"快速下滑"（测试用，等价于鼠标真的划过去）。"""
        cx = self.win_x + self.win_w // 2
        y0 = self.win_y - 40
        steps = 5
        for i in range(steps + 1):
            self._on_mouse_move(cx, y0 + int(distance * i / float(steps)))
            time.sleep(duration / steps)
        return self.squash > 0

    # ------------------------------------------------------------ 桌面层级
    def lower_to_desktop(self):
        """把宠物放到所有窗口下面（贴着桌面），--topmost 时不做。

        用 HWND_BOTTOM 而不是 HWND_BOTTOM 之外的相对层级：它只在"非置顶"那一层
        里排最后，所以不会盖住任何应用窗口，桌面图标仍在自己下面。
        """
        if _user32 is None or self.topmost:
            return
        try:
            hwnd = _user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            HWND_BOTTOM, SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 1, 0x1, 0x2, 0x10
            _user32.SetWindowPos(hwnd, HWND_BOTTOM, 0, 0, 0, 0,
                                 SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
            # 关键：这一发 SetWindowPos 会把"还没生效的 wm geometry"顶掉，
            # 窗口就停在 (0,0)（用户看到的就是"一开就在左上角"）。所以压完
            # 层级再把我们想要的位置重新设一遍，并在下一个 tick 里核对。
            if not self.layered:
                self.backend.move(self.win_x, self.win_y)
                self._pos_check_until = self._now() + 1.0
        except Exception:
            pass

    def _verify_position(self):
        """核对窗口真实位置，和我们的记录不一致就纠正回来。

        Tk 的 wm geometry 是异步的，外面又有 SetWindowPos/图层切换在动窗口，
        很容易出现"程序以为在右上角、实际在左上角"。头一两秒里对一下账。
        """
        if self.layered or _user32 is None:
            return
        try:
            if self.root.winfo_rootx() == self.win_x and self.root.winfo_rooty() == self.win_y:
                return
            self.backend.move(self.win_x, self.win_y)
        except tk.TclError:
            pass

    def _fx_hwnds(self):
        """特效/气泡自己的窗口：检查"被盖住"时要跳过它们。

        打飞机的全屏透明层会盖在宠物上面；如果不跳过，程序会误以为自己被
        别的窗口盖住了，直接暂停动画，飞机/子弹就停住。
        """
        out = set()
        for obj in (getattr(self, "hearts", None),
                    getattr(self, "danmaku", None),
                    getattr(self, "shoot_fx", None),
                    getattr(self, "bubble", None)):
            win = getattr(obj, "win", None)
            if win is None:
                continue
            try:
                if win.winfo_exists():
                    out.add(_hwnd_of(win))
            except Exception:                   # noqa: BLE001
                pass
        return out

    def check_covered(self):
        """被别的窗口完全盖住了吗？盖住就暂停（省 CPU / 不打扰）。

        沿 Z 序往上找（GW_HWNDPREV），直到某个可见窗口把宠物的矩形整个包住
        就算被盖住。桌宠永远在最底层，所以这里一般要往上走几十个窗口才能
        找到真正的那个（浏览器、IDE 之类），上限放宽到 500，别提前放弃。
        """
        if _user32 is None or self.topmost:
            return False
        try:
            hwnd = _user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            me = wintypes.RECT()
            if not _user32.GetWindowRect(hwnd, ctypes.byref(me)):
                return False
            rect = (me.left, me.top, me.right, me.bottom)
            skip = self._fx_hwnds()
            other = wintypes.RECT()
            h = _user32.GetWindow(hwnd, 3)       # GW_HWNDPREV：Z 序里比它高的第一个
            guard = 0
            while h and guard < 500:
                guard += 1
                if h not in skip and _user32.IsWindowVisible(h) \
                        and not _user32.IsIconic(h):
                    if _user32.GetWindowRect(h, ctypes.byref(other)):
                        # 这个窗口完全包含了宠物 -> 被盖住了
                        if (other.left <= rect[0] and other.top <= rect[1]
                                and other.right >= rect[2] and other.bottom >= rect[3]):
                            return True
                h = _user32.GetWindow(h, 3)
            return False
        except Exception:
            return False

    def move(self, x, y, clamp=False):
        if clamp:
            x, y = self.clamp_pos(x, y)
        self.win_x, self.win_y = int(x), int(y)
        self.backend.move(self.win_x, self.win_y)
        if self.layered:
            self._redraw()

    @property
    def pos(self):
        """虚拟窗口左上角（屏幕坐标），后端用它定位实际窗口。"""
        return (self.win_x, self.win_y)

    def head_anchor(self):
        """宠物头顶中心的屏幕坐标（气泡挂点），带上当前动画位移。"""
        factor = self._squash_factor()
        delta = (1.0 - factor) * self.sh      # 拉长时头顶上移，压扁时下移
        return (self.win_x + self.win_w // 2 + self.offset[0] + self._pet_dx,
                self.win_y + self.headroom + self._last_dy + 4 + delta)

    def face_anchor(self):
        """估一下脸的位置，返回 ((左脸颊), (右脸颊), 头高)。

        按人物实际占用区域的顶部往下算（见 Sprite.content_bbox），这样图上方
        留着空白也不影响"头顶在哪"。没有做人脸识别：桌面宠物都是正面人像，
        "头顶往下约一半处的左右两片"已经够用来挂摸头特效了。
        """
        bbox = self.sprite.content_bbox()
        sw, sh = self.sprite.size
        scale = self.scale
        top = bbox[1] * scale
        content_h = max(1.0, (bbox[3] - bbox[1]) * scale)
        head_h = max(20.0, min(content_h * 0.30, sh * scale * 0.32))
        cx = self.win_x + self.headroom_x + sw * scale / 2.0
        cy = self.win_y + self.headroom + top + head_h * 0.52
        # 跟着身体一起缩/歪：图是底边钉住压缩的，再绕底边中点旋转
        bottom = self.win_y + self.win_h - 2
        d = max(0.0, bottom - cy) * self._squash_factor()
        rad = math.radians(self._pet_angle)
        cx += -d * math.sin(rad) + self._pet_dx
        cy = bottom - d * math.cos(rad) + self._pet_dy
        half = head_h * 0.24
        return ((cx - half, cy), (cx + half, cy), head_h)

    # ------------------------------------------------------------ 菜单
    def _defer(self, fn, *args):
        """把菜单里点的动作排队，等下一次 tick 执行。

        菜单弹出时 Windows/Tk 那边压着一个**模态菜单循环**，输入焦点和 grab
        都还在菜单上（用户的原话：右键菜单优先级太高、调用对话时没消除，
        所以输入被判给菜单，中文要"刷新一次"才能打）。而且在这种模态循环里
        重建画布/图片/输入法状态很容易出问题，崩了还留不下日志 —— 统一改成
        排队，等回到普通事件循环里再干。

        同一个动作只保留最后一次（连点大小），不同动作各自按顺序执行
        （否则"换形象"会被紧随其后的"改大小"顶掉）。
        """
        self._pending_actions = [(f, a) for (f, a) in self._pending_actions
                                 if f is not fn]
        self._pending_actions.append((fn, args))

    @contextlib.contextmanager
    def _modal(self):
        """标记"现在正等一个模态窗口"。

        wait_window / messagebox 会开一层嵌套事件循环：tick 还在跑，但用户在
        打字/思考，可能几十秒都不点。看门狗要是把这当成卡死，就会在用户正输入
        API Key 的时候把窗口关掉甚至重启进程。进了这个上下文就先让它别动手。
        """
        self._modal_depth += 1
        self._last_tick = self._now()
        try:
            yield
        finally:
            self._modal_depth = max(0, self._modal_depth - 1)
            self._last_tick = self._now()

    def _run_pending_action(self):
        if not self._pending_actions or self._busy_action:
            return
        actions, self._pending_actions = self._pending_actions, []
        self._busy_action = True
        try:
            for fn, args in actions:
                try:
                    fn(*args)
                except Exception:           # noqa: BLE001 - 包含 TclError
                    # 菜单里点的动作失败一定要留痕：以前 TclError 是静默吞掉的，
                    # 现象就是"点了没反应"，什么线索都没有
                    _log_exception()
        finally:
            self._busy_action = False

    def _drop_menu(self):
        """把右键菜单彻底收掉（取消弹出 + 释放 grab + 结束菜单模态状态）。

        不这么做的话，菜单关掉后**我们线程的活动窗口/焦点仍然是菜单**（实测
        GetGUIThreadInfo 里 hwndActive==hwndFocus==菜单窗口），之后 SetFocus
        到输入框会静默失败，中文输入法就"要刷新一次"才能用。
        """
        try:
            self.menu.unpost()
        except Exception:                   # noqa: BLE001
            pass
        try:
            self.menu.grab_release()
        except Exception:                   # noqa: BLE001
            pass
        # 让窗口取消自己的模态状态（Windows 的菜单模式就是靠这个消息收掉的）
        if _user32 is not None:
            try:
                hwnd = _user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
                _user32.PostMessageW(hwnd, WM_CANCELMODE, 0, 0)
            except Exception:               # noqa: BLE001
                pass

    # ------------------------------------------------------------ 右键菜单
    def _menu_font(self, size=10, bold=False):
        return (FONT_FAMILY, size, "bold" if bold else "normal")

    def _style_menu(self, menu):
        """统一菜单配色：Tk 默认的灰底黑字太朴素。"""
        try:
            menu.configure(font=self._menu_font(10),
                           bg=MENU_BG, fg=MENU_FG,
                           activebackground=MENU_HI,
                           activeforeground=MENU_FG_HI,
                           bd=0, relief="flat", activeborderwidth=0,
                           selectcolor=MENU_ACCENT)
        except tk.TclError:
            pass
        return menu

    def _menu_icon(self, name):
        """菜单左边的小图标。PhotoImage 必须留引用，不然会被回收成空白。"""
        try:
            photo = ImageTk.PhotoImage(_icon_pil(name, 17, MENU_ICON),
                                       master=self.root)
        except Exception:                       # noqa: BLE001
            _log_exception()
            return None
        self._menu_photos.append(photo)
        return photo

    def _menu_add(self, menu, label, command=None, icon=None,
                  accel=None, state=None):
        kwargs = {"label": label}
        if command is not None:
            kwargs["command"] = command
        if accel:
            kwargs["accelerator"] = accel
        if state:
            kwargs["state"] = state
        photo = self._menu_icon(icon) if icon else None
        if photo is not None:
            kwargs["image"] = photo
            kwargs["compound"] = "left"
        menu.add_command(**kwargs)

    def _menu_head(self, menu, title):
        """分组标题：一条分隔线 + 一行浅蓝小字。"""
        menu.add_separator()
        menu.add_command(label="  " + title, state="disabled",
                         font=(FONT_FAMILY, 8), foreground=MENU_HEAD)

    def _build_menu(self):
        self._menu_photos = []
        self.menu = self._style_menu(tk.Menu(self.root, tearoff=0))
        self.image_menu = self._style_menu(tk.Menu(self.menu, tearoff=0))
        self.image_var = tk.StringVar(value=self.image_name)
        self._fill_image_menu()
        size_menu = self._style_menu(tk.Menu(self.menu, tearoff=0))
        self.scale_var = tk.DoubleVar(value=self.scale)
        for s in self.SCALES:
            size_menu.add_radiobutton(
                label="%d%%" % round(s * 100), value=s,
                variable=self.scale_var,
                command=lambda v=s: self._defer(self.set_scale, v))
        opacity_menu = self._style_menu(tk.Menu(self.menu, tearoff=0))
        self.opacity_var = tk.DoubleVar(value=self.opacity)
        for value in OPACITY_STEPS:
            opacity_menu.add_radiobutton(
                label="%d%%" % round(value * 100), value=value,
                variable=self.opacity_var,
                command=lambda v=value: self._defer(self.set_opacity, v))
        opacity_menu.add_separator()
        opacity_menu.add_command(label="Ctrl + 滚轮 也能调", state="disabled")

        ai_menu = self._style_menu(tk.Menu(self.menu, tearoff=0))
        self.ai_var = tk.BooleanVar(value=self.ai_enabled)
        # 「启用 AI」是设置项，放在设置窗口的「对话」页，这里只留功能入口
        self._menu_add(ai_menu, "设置 API Key…", icon="key",
                       command=lambda: self._defer(self.set_api_key))
        self._menu_add(ai_menu, "清空对话记忆", icon="refresh",
                       command=lambda: self._defer(self.forget_chat))
        self.model_label = "模型: %s" % self.brain.model
        ai_menu.add_command(label=self.model_label, state="disabled")
        self.affection_label = "好感度: %d / 100" % self.affection
        ai_menu.add_command(label=self.affection_label, state="disabled")
        ai_menu.add_command(
            label="人设: %s" % ai_client.persona_display_name(
                getattr(self, "_persona", DEFAULT_PERSONA)),
            state="disabled")
        persona_menu = self._style_menu(tk.Menu(ai_menu, tearoff=0))
        self.persona_var = tk.StringVar(
            value=getattr(self, "_persona", DEFAULT_PERSONA))
        for key in ai_client.PERSONA_PROMPTS:
            persona_menu.add_radiobutton(
                label="%s（%s）" % (ai_client.persona_display_name(key), key),
                value=key, variable=self.persona_var,
                command=lambda k=key: self._defer(self.set_persona, k))
        persona_menu.add_separator()
        self._menu_add(persona_menu, "编辑人设…", icon="key",
                       command=lambda: self._defer(self.open_persona_editor))
        self._persona_menu = persona_menu
        ai_menu.add_cascade(label="这张图的人设", menu=persona_menu)
        self._affection_menu = ai_menu

        self.music_menu = self._style_menu(tk.Menu(self.menu, tearoff=0))
        self.music_var = tk.StringVar(value=self.music_name)
        self._fill_music_menu()
        self.web_menu = self._style_menu(tk.Menu(self.menu, tearoff=0))
        self._fill_web_menu()

        play_menu = self._style_menu(tk.Menu(self.menu, tearoff=0))
        for label, key, icon in (("摸头", "head", "paw"),
                                 ("跳一下", "jump", "jump"),
                                 ("压扁", "squash", "squash"),
                                 ("转圈圈（晕）", "spin", "spin"),
                                 ("躲一下", "dodge", "dodge")):
            self._menu_add(play_menu, label, icon=icon,
                           command=lambda k=key: self._defer(self.do_gesture, k))
        play_menu.add_separator()
        self._menu_add(play_menu, "打飞机（chm / 郑迪隆）", icon="shoot",
                       command=lambda: self._defer(self.trigger_shooting))
        self._play_menu = play_menu

        # 顶栏：最常用的三个入口
        self._menu_add(self.menu, "跟它说话", icon="bubble", accel="点一下",
                       command=lambda: self._defer(self.speak_random))
        self._menu_add(self.menu, "对话…", icon="cat", accel="双击",
                       command=lambda: self._defer(self.open_chat))
        self._menu_add(self.menu, "设置…", icon="window", accel="Esc",
                       command=lambda: self._defer(self.open_settings))

        self._menu_head(self.menu, "形象")
        self.menu.add_cascade(label="形象", menu=self.image_menu,
                              image=self._menu_icon("image"), compound="left")
        self.menu.add_cascade(label="大小", menu=size_menu,
                              image=self._menu_icon("size"), compound="left")
        self.menu.add_cascade(label="不透明度", menu=opacity_menu,
                              image=self._menu_icon("eye"), compound="left")

        self._menu_head(self.menu, "玩法")
        self.menu.add_cascade(label="逗它玩", menu=play_menu,
                              image=self._menu_icon("sparkle"), compound="left")
        games_menu = self._style_menu(tk.Menu(self.menu, tearoff=0))
        game_icons = {"rps": "paw", "guess": "face",
                      "memory": "sparkle", "mole": "shoot"}
        for key, (label, _cls) in pet_games.GAMES.items():
            self._menu_add(games_menu, label, icon=game_icons.get(key),
                           command=lambda k=key: self._defer(
                               self.open_game, k))
        games_menu.add_separator()
        games_menu.add_command(label=self._game_stats_text(), state="disabled")
        self._games_stats_index = games_menu.index("end")
        self._game_menu = games_menu
        self.menu.add_cascade(label="小游戏", menu=games_menu,
                              image=self._menu_icon("paw"), compound="left")
        self._menu_add(self.menu, "说点什么", icon="smile",
                       command=lambda: self._defer(self.speak_random))
        self._menu_add(self.menu, "来一个颜文字", icon="face",
                       command=lambda: self._defer(self.say_kaomoji))

        self._menu_head(self.menu, "声音与网页")
        self.menu.add_cascade(label="音乐", menu=self.music_menu,
                              image=self._menu_icon("note"), compound="left")
        self.menu.add_cascade(label="打开网页", menu=self.web_menu,
                              image=self._menu_icon("globe"), compound="left")

        self._menu_head(self.menu, "维护")
        self.menu.add_cascade(label="AI 设置", menu=ai_menu,
                              image=self._menu_icon("sparkle"), compound="left")
        self._menu_add(self.menu, "刷新一下（卡死急救）", icon="refresh",
                       command=lambda: self._defer(self.request_refresh))
        self._menu_add(self.menu, "修改器…", icon="key",
                       command=lambda: self._defer(self.open_modifier))
        self._menu_add(self.menu, "重置", icon="refresh",
                       command=lambda: self._defer(self.confirm_reset))
        self._menu_add(self.menu, "回到右下角", icon="pin",
                       command=lambda: self._defer(self.reset_position))
        self._menu_add(self.menu, "打开图片文件夹", icon="image",
                       command=lambda: self._defer(self.open_image_folder))
        self.menu.add_command(
            label="渲染后端: %s" % self.backend.style, state="disabled")

        self.menu.add_separator()
        self._menu_add(self.menu, "退出", icon="power",
                       command=lambda: self._defer(self.quit))

        # 只绑一次！以前画布和根窗口都绑了同一批处理函数，而 Tk 的分发是
        # "控件 -> 类 -> 顶层窗口" 逐级来的：点在画布上时两个绑定都会执行，
        # 于是双击弹出**两个**对话框（第二个把气泡回复盖住，看着就是"没回答"）、
        # 右键弹出**两个**菜单、单击说话也说两次。根窗口这一层已经能收到所有
        # 子控件的冒泡事件，所以只绑根窗口就够。
        for seq, fn in (("<Button-1>", self._on_press),
                        ("<B1-Motion>", self._on_drag),
                        ("<ButtonRelease-1>", self._on_release),
                        ("<Double-Button-1>", self._on_double),
                        ("<Button-3>", self._on_menu)):
            self.root.bind(seq, fn)
        # Ctrl + 滚轮 调不透明度（Linux/Windows 下 Tk 给的是 <Control-MouseWheel>，
        # 有些环境只给 <MouseWheel>，两个都绑）
        for seq in ("<Control-MouseWheel>", "<Control-Button-4>",
                    "<Control-Button-5>"):
            try:
                self.root.bind(seq, self._on_opacity_wheel)
            except tk.TclError:
                pass
        # 放歌时的快捷键：空格 = 停止，左右方向键 = 后退/前进 15 秒。
        # 只绑在宠物自己身上（不装全局键盘钩子 —— 本机安全软件会拦，而且
        # 把空格注册成全局热键会把所有程序的空格都吃掉）。点一下宠物或
        # 那个控制条气泡，再用这几个键就行。
        for seq, fn in (("<space>", self._key_stop_music),
                        ("<Left>", lambda e: self._key_seek(-15)),
                        ("<Right>", lambda e: self._key_seek(15)),
                        ("<KeyPress-bracketleft>", self._key_switch_music(-1)),
                        ("<KeyPress-bracketright>", self._key_switch_music(1))):
            try:
                self.root.bind(seq, fn)
            except tk.TclError:
                pass

    def _fill_image_menu(self):
        """形象菜单：一张图一项，显示文件名（按文件名排序，内置的三张排前面）。"""
        menu = self.image_menu
        menu.delete(0, "end")
        for img in self.images:
            label = img.name if not img.alpha else "%s（带透明）" % img.name
            menu.add_radiobutton(label=label, value=img.name,
                                 variable=self.image_var,
                                 command=lambda n=img.name: self._defer(self.set_image, n))
        menu.add_separator()
        menu.add_command(label="重新扫描图片文件夹",
                         command=lambda: self._defer(self.reload_images))
        menu.add_command(label="打开图片文件夹",
                         command=lambda: self._defer(self.open_image_folder))

    def set_opacity(self, value, quiet=False):
        """设置不透明度（0.2 ~ 1.0），并记住它。

        注意：启动时一律是 100%（需求如此），这个值不写进配置文件。
        """
        try:
            value = float(value)
        except (TypeError, ValueError):
            return
        value = max(OPACITY_MIN, min(1.0, value))
        self.opacity = value
        try:
            self.root.attributes("-alpha", value)
        except tk.TclError:
            return
        try:
            if abs(self.opacity_var.get() - value) > 1e-6:
                self.opacity_var.set(value)
        except Exception:                   # noqa: BLE001 - 菜单还没建好
            pass
        if not quiet:
            self.speak("不透明度 %d%%。" % round(value * 100))
        self.sync_settings()

    def _on_opacity_wheel(self, event):
        """Ctrl + 滚轮：每次 5%。"""
        delta = getattr(event, "delta", 0) or 0
        if delta == 0:                      # X11 的 Button-4/5
            delta = 120 if getattr(event, "num", 0) == 4 else -120
        self.set_opacity(self.opacity + (OPACITY_WHEEL_STEP if delta > 0
                                        else -OPACITY_WHEEL_STEP))
        return "break"

    def _on_menu(self, event):
        self._note_interaction()
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        except tk.TclError:
            return  # 窗口正在销毁
        finally:
            # 菜单收掉之后必须把模态状态清干净：不然 grab/焦点还留在菜单上，
            # 之后弹出的对话框收不到键盘（中文输入法要"刷新一次"就是这个）
            self._drop_menu()

    def forget_chat(self):
        """忘掉对话记忆，把好感度退回初始值（恋人关系也一起清掉）。"""
        self.brain.history = []
        self.brain.context = ""
        self.brain.turns = 0
        self.cfg.pop("brain", None)
        self.cfg.pop("context", None)
        self.affection = AFFECTION_START
        self.mood.reset()
        self._sync_mood_hint(None)
        if self.romance:
            self.romance = False
            self.brain.system_prompt = ai_client.persona_prompt(self._persona)
            self._update_persona_menu()
        self._stash_persona()
        self._update_affection_menu()
        self._save_config()
        if self.chat_win is not None:
            self.chat_win.set_affection(self.affection)
            self.chat_win.refresh_romance()
        self.speak("好，刚才聊的我都忘了。")

    # ------------------------------------------------------------ 开关
    def set_bubble_enabled(self, on, quiet=False):
        """显示/隐藏气泡。设置窗口和右键菜单共用这一个入口。"""
        on = bool(on)
        changed = on != self.bubble_enabled
        self.bubble_enabled = on
        if on and self.bubble is None:
            self.bubble = SpeechBubble(self.root, self._active_image().key or "#ffffff")
        if not on and self.bubble:
            # 关掉就要真的销毁并置空：speak() 是按 "bubble is None" 判断的，
            # 只 hide() 的话点一下宠物气泡又冒出来了，开关等于没关
            self.bubble.destroy()
            self.bubble = None
        if changed:
            self._save_config()
        if not quiet:
            self.speak("好，我继续说话。" if on else "好，我先安静待着。")
        self.sync_settings()
        return on

    def toggle_bubble(self):
        self.set_bubble_enabled(not self.bubble_enabled)

    def set_click_through(self, on, quiet=False):
        """鼠标穿透。不存盘：下次启动总能点得到它。"""
        on = bool(on) and _user32 is not None
        self.click_through = on
        try:
            self.backend.set_click_through(on)
        except Exception:                       # noqa: BLE001
            _log_exception()
        if not quiet and on:
            self.speak("好，鼠标可以直接穿过我了。想关掉就右键托盘图标。")
        self.sync_settings()
        return on

    def toggle_click_through(self):
        self.set_click_through(not self.click_through)

    def set_gestures_enabled(self, on, quiet=False):
        """手势互动总开关：关掉后划过、摸头、绕圈都不再触发动作。"""
        on = bool(on)
        changed = on != self.gestures_enabled
        self.gestures_enabled = on
        if not on:
            # 把正在进行的采样和状态一起清掉，免得关掉瞬间还补一个动作
            self._swipe = []
            self._body_track = []
            self._circle_track = []
            self._shake_track = []
            self._pet_prev = None
            self._pet_last_seen = 0.0
            self._pet_reset_gesture()
        if changed:
            self._save_config()
        if not quiet:
            self.speak("好，可以来逗我了。" if on else "好，我不乱动了。")
        self.sync_settings()
        return on

    def toggle_gestures(self):
        self.set_gestures_enabled(not self.gestures_enabled)

    def set_click_speak(self, on, quiet=False):
        on = bool(on)
        changed = on != self.click_speak
        self.click_speak = on
        if changed:
            self._save_config()
        if not quiet:
            self.speak("点我一下我就说句话。" if on else "好，点我就不吵你了。")
        self.sync_settings()
        return on

    def _apply_gesture_tuning(self):
        """按「手势灵敏度」「动作幅度」算出阈值与跳跃幅度。"""
        table = {"low": (125.0, 390.0), "normal": (90.0, 300.0),
                 "high": (65.0, 235.0)}
        min_px, speed = table.get(self.gesture_sensitivity, table["normal"])
        self.swipe_min_px = min_px
        self.swipe_speed = speed
        self._jump_gain = {"calm": 0.72, "normal": 1.0,
                           "lively": 1.32}.get(self.anim_level, 1.0)

    def set_bubble_ms(self, value, quiet=True):
        """气泡停留时长（毫秒）。"""
        try:
            value = max(1000, min(12000, int(value)))
        except (TypeError, ValueError):
            return False
        if value == self.bubble_ms:
            return True
        self.bubble_ms = value
        self._save_config()
        if not quiet:
            self.speak("气泡会停 %d 秒。" % round(value / 1000.0), background=True)
        return True

    def set_anim_level(self, value, quiet=False):
        """动作幅度：calm / normal / lively。"""
        if value not in ("calm", "normal", "lively"):
            return False
        self.anim_level = value
        self._apply_gesture_tuning()
        self._save_config()
        if not quiet:
            self.speak({"calm": "那我安静一点。", "normal": "好，正常幅度。",
                        "lively": "那我活泼一点！"}[value], background=True)
        return True

    def set_gesture_sensitivity(self, value, quiet=False):
        """手势灵敏度：low / normal / high。"""
        if value not in ("low", "normal", "high"):
            return False
        self.gesture_sensitivity = value
        self._apply_gesture_tuning()
        self._save_config()
        if not quiet:
            self.speak({"low": "手势要划得久一点我才懂。",
                        "normal": "手势灵敏度正常。",
                        "high": "轻轻一划我就有反应。"}[value], background=True)
        return True

    def set_shake_refresh(self, on, quiet=False):
        """摇一摇：关 = 摇头撒娇，开 = 摇一次就刷新。"""
        self.shake_refresh = bool(on)
        self._save_config()
        if not quiet:
            self.speak("摇一摇就刷新。" if self.shake_refresh
                       else "摇一摇就是摇头。", background=True)
        return True

    def set_autostart(self, on, quiet=False):
        """开机自启：写 HKCU 的 Run 项（不需要管理员）。"""
        on = bool(on)
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Run",
                                 0, winreg.KEY_SET_VALUE)
            try:
                if on:
                    winreg.SetValueEx(key, "DesktopPet", 0, winreg.REG_SZ,
                                      self._launch_command())
                else:
                    try:
                        winreg.DeleteValue(key, "DesktopPet")
                    except FileNotFoundError:
                        pass
            finally:
                winreg.CloseKey(key)
        except Exception:                       # noqa: BLE001
            _log_exception()
            return False
        self.autostart = on
        self._save_config()
        if not quiet:
            self.speak("开机我就自己出来。" if on else "开机我先不出来。",
                       background=True)
        return True

    def _launch_command(self):
        """开机自启要执行的命令行（打包版直接跑 exe，源码版跑 pythonw + 脚本）。"""
        if FROZEN:
            return '"%s"' % sys.executable
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pyw):
            pyw = sys.executable
        return '"%s" "%s"' % (pyw, os.path.join(ROOT, "desktop_pet.py"))

    def set_auto_restart(self, on, quiet=False):
        on = bool(on)
        changed = on != self.auto_restart
        self.auto_restart = on
        if changed:
            self._save_config()
        if not quiet:
            self.speak("卡死了我会自己爬起来。" if on else "好，卡住就等我手动刷新。")
        self.sync_settings()
        return on

    def set_pause_fullscreen(self, on, quiet=False):
        on = bool(on)
        changed = on != self.pause_fullscreen
        self.pause_fullscreen = on
        if changed:
            self._save_config()
        self._next_fs_check = 0.0
        if not on and self._fs_paused:
            self._leave_fullscreen_pause()
        if not quiet:
            self.speak("好，全屏的时候我先躲起来。" if on
                       else "好，全屏的时候也不躲了。")
        self.sync_settings()
        return on

    def _update_fullscreen(self, now):
        """前台有全屏窗口（游戏、全屏视频、演示）时把桌宠整个收起来。

        只在前台窗口真的铺满一整个显示器、并且没有标题栏（详见
        foreground_fullscreen）时才算；普通"最大化"窗口不算。
        """
        if not self.pause_fullscreen:
            if self._fs_paused:
                self._leave_fullscreen_pause()
            return
        ignore = set(h for h in (self._rescue_hwnds or ()) if h)
        if self._bubble_hwnd:
            ignore.add(self._bubble_hwnd)
        try:
            hwnd = foreground_fullscreen(ignore)
        except Exception:                       # noqa: BLE001
            hwnd = 0
        if hwnd and not self._fs_paused:
            self._enter_fullscreen_pause(hwnd)
        elif not hwnd and self._fs_paused:
            self._leave_fullscreen_pause()

    def _enter_fullscreen_pause(self, hwnd=0):
        """进入全屏暂停：收起窗口、停掉动画/气泡/AI 请求。"""
        self._fs_paused = True
        self._fs_hwnd = int(hwnd or 0)
        self._pet_reset_gesture()
        self._swipe = []
        self._body_track = []
        self._circle_track = []
        self._shake_track = []
        self._pet_prev = None
        self._pet_last_seen = 0.0
        try:
            if self.bubble is not None:
                self.bubble.hide()
            self.hearts.clear()
            self.danmaku.clear()
            if getattr(self, "shoot_fx", None) is not None:
                self.shoot_fx.clear()
        except Exception:                       # noqa: BLE001
            _log_exception()
        self.shooting_until = 0.0
        self._restore_shoot_home()
        self.squash = 0.0
        self.jump = 0.0
        self._fs_pos = self.pos
        try:
            # overrideredirect 的窗口 withdraw 之后位置会丢，回来的时候按这个补
            self.root.withdraw()
        except tk.TclError:
            pass

    def _leave_fullscreen_pause(self):
        """退出全屏暂停：把窗口放回原位，重新压到桌面层。"""
        if not self._fs_paused:
            return
        self._fs_paused = False
        self._fs_hwnd = 0
        self._next_fs_check = 0.0
        self._next_visible_check = 0.0
        try:
            self.root.deiconify()
            self.root.attributes("-topmost", False)
            self._pending_lower = True
            self.visible = True
            self.phase = random.uniform(0, math.tau)
            pos = getattr(self, "_fs_pos", None)
            if pos:
                self.move(pos[0], pos[1], clamp=True)
        except tk.TclError:
            pass

    # ------------------------------------------------------------ 设置窗口
    def open_settings(self):
        """右键「设置…」/托盘：打开唯一的设置窗口。"""
        if self.settings_win is None:
            self.settings_win = SettingsWindow(self, on_close=self._settings_closed)
        self.settings_win.show()

    def _settings_closed(self):
        self.settings_win = None

    def sync_settings(self):
        """设置窗口开着的话，把开关对齐到当前状态（不触发回调）。"""
        win = getattr(self, "settings_win", None)
        if win is None:
            return
        try:
            win.sync()
        except tk.TclError:
            self.settings_win = None
        except Exception:                       # noqa: BLE001
            _log_exception()

    # ------------------------------------------------------------ 刷新 / 急救
    def request_refresh(self):
        """请求刷新：菜单、设置窗口、托盘、看门狗都走这里。

        真正的重启动作放到下一帧（_tick_body）里做：从菜单回调里直接重建
        气泡/主循环会把正在跑的 Tk 模态循环弄坏。
        """
        self._refresh_requested = True
        if self._in_tick:
            return
        try:
            self.root.after(1, self._run_refresh_if_pending)
        except tk.TclError:
            pass

    def _run_refresh_if_pending(self):
        if self._refresh_requested and not self._in_tick:
            self.refresh_pet()

    def refresh_pet(self):
        """把宠物从卡死/错乱状态里拽回来（不重启进程）。

        依次做：丢掉排队的动作 -> 收掉特效和摸头状态 -> 重建气泡窗口 ->
        重铺帧/位置/层级 -> 如果主循环真的停了就重新起一条 -> 同步设置窗口。
        """
        self._refresh_requested = False
        # 1) 卡死时点的菜单/按钮多半已经过期，别再执行了
        self._pending_actions = []
        self._busy_action = False
        # 2) 特效、摸头、手势状态清零
        for fx in (self.hearts, self.danmaku, self.shoot_fx):
            clear = getattr(fx, "clear", None)
            try:
                if clear is not None:
                    clear()
            except Exception:                   # noqa: BLE001
                _log_exception()
        self._restore_shoot_home()
        self.petting_until = 0.0
        self._pet_energy = 0.0
        self._pet_press = 0.0
        self._pet_prev = None
        self._pet_reset_gesture()
        self._swipe = []
        self._body_track = []
        self._circle_track = []
        self._shake_track = []
        self._dodge_until = 0.0
        self._spin_until = 0.0
        self.squash = 0.0
        self.jump = 0.0
        self.offset = [0.0, 0.0]
        self.target = [0.0, 0.0]
        # 3) 气泡窗口整个重建：卡死时它最容易停在"显示着但不再更新"的半成品状态
        if self.bubble_enabled:
            old = self.bubble
            try:
                if old is not None:
                    old.destroy()
            except Exception:                   # noqa: BLE001
                _log_exception()
            try:
                self.bubble = SpeechBubble(self.root,
                                           self._active_image().key or "#ffffff")
            except Exception:                   # noqa: BLE001
                self.bubble = None
                _log_exception()
        else:
            self.bubble = None
        # 4) 尺寸/帧/位置重新对一遍
        try:
            self._apply_size()
            self._build_frames()
            if not self.layered:
                self.canvas.configure(width=self.win_w, height=self.win_h)
            self._mount_sprite()
            self.move(self.win_x, self.win_y, clamp=True)
            self._redraw()
        except Exception:                       # noqa: BLE001
            _log_exception()
        # 5) 层级、钩子、可见性检查都重置
        try:
            self.root.attributes("-topmost", False)
            self.lower_to_desktop()
            if self._mouse_hook is None:
                self._install_mouse_hook()
        except Exception:                       # noqa: BLE001
            _log_exception()
        self.visible = True
        self._next_visible_check = 0.0
        self._last_tick = self._now()
        self._stall_logged = False
        # 6) 主循环自己也可能已经停了：取消旧的 after，重新起一条
        if not self._in_tick:
            try:
                if self._tick_job is not None:
                    self.root.after_cancel(self._tick_job)
            except Exception:                   # noqa: BLE001
                pass
            self._tick_job = None
            self._tick()
        self._refresh_hwnds()
        self.sync_settings()
        self.speak("好了，我没事了。")

    # 看门狗线程里允许调用的部分（不能碰 Tk！）
    def _refresh_hwnds(self):
        """（主线程）记下可以安全发消息的窗口句柄，供看门狗急救用。

        ⚠ 这里算出来的句柄是普通 int，看门狗线程只能读它 —— 不能在那边
        去碰 pet.bubble.hwnd（那个属性内部会调 Tk 的 winfo_exists，
        跨线程调 Tcl 会直接把进程带崩：0xC0000409）。
        """
        out = []
        self._bubble_hwnd = 0
        try:
            out.append(_hwnd_of(self.root))
        except Exception:                       # noqa: BLE001
            pass
        bubble = getattr(self, "bubble", None)
        hwnd = getattr(bubble, "hwnd", None) if bubble is not None else None
        if hwnd:
            out.append(hwnd)
            self._bubble_hwnd = int(hwnd)
        win = getattr(self, "settings_win", None)
        win = getattr(win, "win", None) if win is not None else None
        if win is not None:
            try:
                if win.winfo_exists():
                    out.append(_hwnd_of(win))
            except tk.TclError:
                pass
        self._rescue_hwnds = [h for h in out if h]

    def _watch_rescue(self):
        """（看门狗线程）把卡住的模态循环敲一下，并把卡住的气泡先藏起来。"""
        if _user32 is None:
            return
        now = time.monotonic()
        if now - self._rescue_at < 2.0:
            return
        self._rescue_at = now
        self._refresh_requested = True
        fg = 0
        try:
            fg = _user32.GetForegroundWindow()
        except Exception:                       # noqa: BLE001
            pass
        for hwnd in list(self._rescue_hwnds):
            if not hwnd:
                continue
            try:
                # WM_CANCELMODE 能打断菜单/拖动这类内建的模态循环
                _user32.PostMessageW(hwnd, WM_CANCELMODE, 0, 0)
                if fg == hwnd:
                    _user32.PostMessageW(hwnd, WM_KEYDOWN, VK_ESCAPE, 0)
                    _user32.PostMessageW(hwnd, WM_KEYUP, VK_ESCAPE, 0)
            except Exception:                   # noqa: BLE001
                pass
        # 气泡句柄是主线程算好存下来的 int，这里绝对不能再走 bubble.hwnd
        bubble_hwnd = getattr(self, "_bubble_hwnd", 0) or 0
        if bubble_hwnd:
            try:
                _user32.ShowWindow(bubble_hwnd, SW_HIDE)
            except Exception:                   # noqa: BLE001
                pass

    def open_image_folder(self):
        """打开 image/ 文件夹，方便用户往里丢图片。"""
        try:
            os.makedirs(self.image_dir, exist_ok=True)
            os.startfile(self.image_dir)        # noqa: S606 - Windows 专用
        except Exception as exc:                # noqa: BLE001
            self.speak("打不开文件夹：%s" % exc)

    def reload_images(self):
        """重新扫描 image/，菜单立刻反映新丢进去的图片。"""
        keep = self.image_name
        self.images = scan_images(self.image_dir)
        names = [im.name for im in self.images]
        self._fill_image_menu()
        if keep in names:
            self.image_var.set(keep)
        else:
            self.set_image(names[0] if names else DEFAULT_IMAGE)
        self.speak("扫到 %d 张图。" % len(self.images))

    def _update_affection_menu(self):
        """菜单里那个"好感度: N / 100"跟着变（冷战/吃醋时后面挂个状态）。"""
        menu = getattr(self, "_affection_menu", None)
        if menu is None:
            return
        try:
            for i in range(menu.index("end") + 1):
                label = menu.entrycget(i, "label")
                if label.startswith("好感度"):
                    text = "好感度: %d / 100" % self.affection
                    if self.mood.state != pet_mood.NORMAL:
                        text += " · " + self.mood.label()
                    menu.entryconfigure(i, label=text)
                    break
        except tk.TclError:
            pass

    def _style_for(self, img):
        """按图片挑渲染后端。

        以前：带真实透明通道的图默认走 layered（alpha 最干净）。
        现在：layered 在某些机器上整层不合成（窗口在、画面全空），
        所以**默认一律 colorkey**，带 alpha 的图会把 alpha 压平到抠底色上
        （见 sprite_for：硬边遮罩 + flatten_to），效果够用且哪里都能显示。
        想要 layered 得显式选：命令行 --style layered（配置里那个 style
        只记上次实际用的后端，不作为下次的意图 —— 否则一次走岔就永久空白）。
        """
        if self.force_colorkey:
            return "colorkey"
        if self.want_layered:
            return "layered"
        return "colorkey"

    def _active_image(self):
        for img in self.images:
            if img.name == self.image_name:
                return img
        return self.images[0]

    def set_image(self, name):
        """切换立绘：按新图重算抠底色（和渲染后端）。

        整个过程包在 try 里：中途失败（图坏了、内存不够、句柄拿不到）也要
        把 image_name 退回上一个能用的形象，别让菜单显示的和实际画的对不上。
        """
        names = [im.name for im in self.images]
        if name not in names or name == self.image_name:
            return
        old_name = self.image_name
        try:
            self._set_image_impl(name)
        except Exception:                   # noqa: BLE001 - 换形象失败不该拖垮程序
            _log_exception()
            # 回滚：先把名字退回原来那张（_active_image() 是按 image_name 找的，
            # 不先退回去就会"回滚"到刚失败的那张），再按它重建精灵和尺寸
            self.image_name = old_name
            try:
                self.sprite = sprite_for(self._active_image(), self.layered)
                self._apply_size()
                self._build_frames()
                if not self.layered:
                    self.canvas.configure(width=self.win_w, height=self.win_h)
                self._mount_sprite()
                self._redraw()
            except Exception:                # noqa: BLE001
                _log_exception()
            if self.image_var.get() != self.image_name:
                self.image_var.set(self.image_name)
            self.speak("这张图换不了，先用「%s」。" % self.image_name)

    def _set_image_impl(self, name):
        self.image_name = name
        if not self.danmaku_allowed():
            self.danmaku.clear()
            if getattr(self, "shoot_fx", None) is not None:
                self.shoot_fx.clear()
            self.shooting_until = 0.0
            self._restore_shoot_home()
        img = self._active_image()
        style = self._style_for(img)
        if style != self.backend.style:
            # 换了渲染方式：重建窗口层（图有透明通道时必须走 layered 才好看）
            defer_photo_free(getattr(self.backend, "_photo", None))
            self.backend = make_window_backend(self, style)
            self.layered = self.backend.style == "layered"
            if self.layered:
                self.root.attributes("-topmost", self.topmost)
                self.root.geometry("1x1+0+0")
            else:
                # 从 layered 切回 colorkey：窗口之前被 geometry("1x1+0+0")
                # 钉死了，得先把显式几何清掉，Tk 才会重新按画布的实际大小摆
                # 窗口 —— 否则宠物变成 1x1，直接从屏幕上消失
                self.root.geometry("")
        self.sprite = sprite_for(img, self.layered)
        self._apply_size()
        self._build_frames()
        if not self.layered:
            self.canvas.configure(width=self.win_w, height=self.win_h)
        self.backend.apply_key(img.key or "#ffffff")
        self._mount_sprite()
        if self.bubble:
            self.bubble.set_key(img.key or "#ffffff")
        self._redraw()
        self.move(*self.clamp_pos(self.win_x, self.win_y))
        if not self.topmost:
            self.lower_to_desktop()
        # 形象换了 -> AI 人设、记忆、好感度都跟着换（闷骚少年 vs 话痨朋友）
        self._apply_persona()
        self._save_config()
        self.sync_settings()
        self.speak("换成「%s」。" % name)

    def reset_position(self):
        """右键「回到右下角」：和开机位置用同一套坐标。"""
        self.move(*self.bottom_right_pos())
        self._save_config()

    # ------------------------------------------------------------ 交互
    def _on_press(self, event):
        self._note_interaction()
        self._press_at = self._now()
        self._hold_petted = False
        self.press_pos = (event.x_root, event.y_root, self.win_x, self.win_y)
        self.moved = False

    def _on_drag(self, event):
        if not getattr(self, "press_pos", None):
            return
        dx = event.x_root - self.press_pos[0]
        dy = event.y_root - self.press_pos[1]
        if abs(dx) > 3 or abs(dy) > 3:
            self.moved = True
        self.move(self.press_pos[2] + dx, self.press_pos[3] + dy, clamp=True)
        if self.bubble:
            self.bubble.follow(self.head_anchor())

    def _on_release(self, event):
        if getattr(self, "press_pos", None) and not self.moved:
            if self.click_speak:
                self.speak_random()
            else:
                # 关掉「点击说话」后单击只跳一下：有反馈，但不弹气泡
                self.jump = max(self.jump, 0.85)
        self.press_pos = None
        self._save_config()

    def _on_double(self, event):
        """双击 = 打开对话输入框（比"跳一下"有用；跳一下保留在菜单里）。"""
        self.jump = 1.0
        self.open_chat()

    # ------------------------------------------------------------ 说话
    def _context_from_worker(self, text):
        """AI 线程里回调（摘要更新）：只把值排队送回主线程写。

        以前是直接 self.cfg["context"] = text —— 主线程正在 _save_config() 里
        序列化这个 dict，另一个线程同时改它，撞上就是 "dictionary changed size
        during iteration" 之类的随机异常，正好都发生在改大小 / 换形象的时候。
        """
        self._main_thread(self._apply_context, text)

    def _apply_context(self, text):
        self.cfg["context"] = text

    def _main_thread(self, func, *args):
        """把回调从工作线程送回 Tk 主线程。

        不能用 root.after()：从别的线程调 Tk 是不可靠的（实测回调根本没被派发，
        表现就是 AI 回复永远不出现）。这里改成塞进队列，由 _tick 在主线程里排空。
        """
        if not self._alive:
            return
        self._callbacks.put((func, args))

    def _async(self, work, apply, lane="default", epoch=None):
        """后台跑 work()，回主线程执行 apply(result)。

        同一个 lane 同时只允许一个请求，避免把 API 打爆。
        epoch 不为 None 表示这是用户发起的对话，回复必须显示出来。
        """
        if lane in self._ai_lanes:
            return False
        self._ai_lanes.add(lane)
        my_speech = self._speech_seq

        def runner():
            try:
                result = work()
            except Exception as exc:            # noqa: BLE001 - 线程里绝不能抛出去
                result = exc
            self._main_thread(self._finish, lane, my_speech, epoch, apply, result)

        threading.Thread(target=runner, daemon=True,
                         name="pet-ai-%s" % lane).start()
        return True

    def _finish(self, lane, my_speech, my_epoch, apply, result):
        self._ai_lanes.discard(lane)
        if not self._alive:
            return
        if my_epoch is not None:
            # 用户发起的对话：只要没有更新的一次用户请求，这句就必须回。
            # 注意不能拿 my_speech 去卡——中途随便冒出来的一句话不该把回复吃掉。
            if my_epoch != self._owned_epoch:
                return
        elif my_speech != self._speech_seq:
            return                              # 闲话：气泡已经不是自己那句了就算了
        if isinstance(result, Exception):       # pragma: no cover - 兜底
            result = "（%s）" % ai_client.PetBrain.describe_error(result)
        apply(result)

    @property
    def user_busy(self):
        """用户发起的对话正在等回复 —— 这期间闲话要让路。"""
        return self._owned_epoch > self._owned_shown

    def say_line(self, text, background=False):
        """显示一句话。background=True 表示闲话，用户忙时自动让路。"""
        if background and self.user_busy:
            return False
        self.speak(text)
        return True

    def _chat_rect(self):
        """聊天窗口在屏幕上的矩形（逻辑坐标）；没开就返回 None。

        气泡摆放时拿它当"避开区"：否则气泡正好压在聊天窗的输入框和发送键上，
        看着是挡住的，点也点不到。
        """
        win = self.chat_win
        if win is None:
            return None
        try:
            w = win.win
            if w is None or not w.winfo_exists():
                return None
            x = w.winfo_rootx()
            y = w.winfo_rooty()
            return (x, y, x + max(1, w.winfo_width()),
                    y + max(1, w.winfo_height()))
        except tk.TclError:
            return None

    # ---------------------------------------------------------------- 音乐
    def _fill_music_menu(self):
        """按 music/ 里现有的歌刷新"音乐"子菜单。"""
        menu = getattr(self, "music_menu", None)
        if menu is None:
            return
        try:
            menu.delete(0, "end")
            menu.add_command(label="在线电台…  （不用 music 文件夹）",
                             command=lambda: self._defer(self.open_radio))
            if self.music_online and self.radio_station:
                menu.add_command(
                    label="正在收听：%s" % self.radio_station.get("name", ""),
                    state="disabled")
            menu.add_separator()
            for title, path in self.music_files:
                menu.add_radiobutton(
                    label=title, value=os.path.basename(path),
                    variable=self.music_var,
                    command=lambda p=path: self._defer(self.play_music, p))
            if not self.music_files:
                menu.add_command(label="（music 文件夹里还没有歌）",
                                 state="disabled")
            menu.add_separator()
            menu.add_command(label="上一首  [",
                             command=lambda: self._defer(self._switch_music, -1))
            menu.add_command(label="下一首  ]",
                             command=lambda: self._defer(self._switch_music, 1))
            menu.add_command(label="暂停 / 继续",
                             command=lambda: self._defer(self.toggle_music))
            menu.add_command(label="停止",
                             command=lambda: self._defer(self.stop_music))
            menu.add_separator()
            menu.add_command(label="音量 +10",
                             command=lambda: self._defer(self._music_volume, 10))
            menu.add_command(label="音量 -10",
                             command=lambda: self._defer(self._music_volume, -10))
            menu.add_command(label="音量: %d%%" % self.music_volume,
                             state="disabled")
            menu.add_separator()
            menu.add_command(label="重新扫描 music 文件夹",
                             command=lambda: self._defer(self.rescan_music))
            menu.add_command(label="打开 music 文件夹",
                             command=lambda: self._defer(self.open_music_folder))
        except tk.TclError:
            pass

    def _music_log(self, message):
        try:
            print(message, file=sys.stderr)
        except Exception:               # noqa: BLE001
            pass

    # ------------------------------------------------------- 放歌时的常驻气泡
    MUSIC_BUBBLE_IDLE_S = 2.5       # 别的话说完多久后，把控制条挂回来

    def show_music_bubble(self):
        """头顶常驻「正在播放：歌名」+ 一排按钮（上一首/←15s/停止/15s→/下一首）。"""
        if self.bubble is None or not self._music_active():
            return False
        if self.music_online and self.radio_station:
            title = "电台：%s" % self.radio_station.get("name", "在线电台")
            state = self.stream.status()
            if state == "opening":
                # Windows 的 MCI 开网络流要 20~30 秒，把秒数写出来，
                # 不然用户会以为卡死在这个「连接中」
                title += "（连接中 %d 秒…）" % int(self.stream.waited())
            elif state in ("error", "stopped"):
                title += "（断了）"
            self._music_bubble_wanted = True
            buttons = [("«", self.prev_station),
                       ("停止", self.stop_music),
                       ("»", self.next_station)]
        else:
            title = "正在播放：%s" % pet_music.title_of(self.music.path)
            self._music_bubble_wanted = True
            buttons = [("«", self.prev_music),
                       ("←15s", lambda: self.seek_music(-15)),
                       ("停止", self.stop_music),
                       ("15s→", lambda: self.seek_music(15)),
                       ("»", self.next_music)]
        keymap = {"<space>": self._key_stop_music,
                  "<Left>": lambda e: self._key_seek(-15),
                  "<Right>": lambda e: self._key_seek(15),
                  "<KeyPress-bracketleft>": self._key_switch_music(-1),
                  "<KeyPress-bracketright>": self._key_switch_music(1)}
        ok = self.bubble.show_controls(title, buttons,
                                       self.head_anchor(), want_layered=self.layered,
                                       avoid=self._chat_rect(), keymap=keymap)
        self._music_bubble_at = self._now() + self.MUSIC_BUBBLE_IDLE_S
        return ok

    def _guarded_call(self, fn, timeout, label):
        """在后台线程里跑一次"可能卡住"的系统调用，最多等 timeout 秒。

        ShellExecute（打开网页）这类调用一旦卡住（默认浏览器没响应），主线程就
        再也回不来 —— 连看门狗发的消息都要等主线程回来才会被取走，于是整个
        桌宠"死"在那里。放到守护线程里等，超时就当失败往上抛：界面继续跑。

        **不要**拿它包 MCI 的放歌/暂停/seek/close：MCI 的设备句柄是按线程记的，
        在别的线程 open 出来的 alias，主线程再调用会报"设备未打开"（rc=263）。
        音乐那几条只能留在主线程里同步做。
        """
        box = {}

        def work():
            try:
                box["value"] = fn()
            except BaseException as exc:        # noqa: BLE001
                box["error"] = exc

        th = threading.Thread(target=work, name="pet-%s" % label, daemon=True)
        th.start()
        th.join(timeout)
        if th.is_alive():
            raise RuntimeError("%s 没有响应" % label)
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def seek_music(self, delta):
        """delta 秒：负数是后退，正数是快进。"""
        if self.music_online or not self.music.is_open:
            return False
        try:
            pos = self.music.seek(delta)
        except (pet_music.MusicError, RuntimeError) as exc:
            self._music_log("music: seek %+d failed %r" % (delta, exc))
            return False
        self._music_log("music: seek %+ds -> %ss" % (delta, pos))
        # 快进/后退之后如果控制条被别的话顶掉了，就重新挂回来
        if self._music_bubble_wanted and self.bubble is not None \
                and not self.bubble.visible():
            self.show_music_bubble()
        return True

    def _key_stop_music(self, event=None):
        if self._music_active():
            self.stop_music()
            return "break"
        return None

    def _key_seek(self, delta):
        if self._music_active() and not self.music_online:
            self.seek_music(delta)
            return "break"
        return None

    def _hide_music_bubble(self):
        self._music_bubble_wanted = False
        if self.bubble is not None:
            self.bubble.hide()

    def play_music(self, path=None, announce=True):
        """放一首歌（没给 path 就放上次那首，再不行放第一首），气泡报歌名。"""
        if path is None:
            if not self.music_files:
                self.speak("music 文件夹里还没有歌～")
                return False
            path = self.music_files[0][1]
            for _title, candidate in self.music_files:
                if os.path.basename(candidate) == self.music_name:
                    path = candidate
                    break
        try:
            self.music.play(path)
        except (pet_music.MusicError, RuntimeError) as exc:
            self.speak("（这首放不了：%s）" % exc)
            self._music_log("music: play failed %r" % (exc,))
            return False
        try:
            self.music.set_volume(self.music_volume)
        except (pet_music.MusicError, RuntimeError) as exc:
            self._music_log("music: volume failed %r" % (exc,))
        self.music_online = False
        self.radio_station = None
        self._radio_retry = 0
        self.music_name = os.path.basename(path)
        self.music_paused = False
        try:
            self.music_var.set(self.music_name)
        except tk.TclError:
            pass
        if announce:
            # 放歌期间头顶一直挂着「歌名 + 控制按钮」，不再只是闪一下就没了
            self.show_music_bubble()
        self._save_config()
        return True

    def play_radio(self, station, stations=None, announce=True):
        """放一个在线电台（station 是 dict：name / url / tags）。"""
        station = station if isinstance(station, dict) else {}
        url = str(station.get("url") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            return False
        try:
            self.music.close()      # 本地歌先关掉，免得两个设备一起响
        except (pet_music.MusicError, RuntimeError):
            pass
        try:
            # 立刻返回；真正的 MCI open 在 StreamPlayer 的线程里（可能要几十秒）
            self.stream.play(url)
        except (pet_music.MusicError, RuntimeError) as exc:
            self._music_log("radio: play %r failed %r" % (url, exc))
            self.speak("（这个台放不出来：%s）" % exc)
            return False
        try:
            self.stream.set_volume(self.music_volume)
        except (pet_music.MusicError, RuntimeError) as exc:
            self._music_log("radio: volume failed %r" % (exc,))
        name = str(station.get("name") or "在线电台")
        self.music_online = True
        self.music_paused = False
        self._radio_retry = 0
        self.radio_station = {"name": name, "url": url,
                              "tags": station.get("tags", "")}
        if stations:
            self.radio_list = list(stations)
            self.radio_index = -1
            for i, st in enumerate(self.radio_list):
                if str(st.get("url")) == url:
                    self.radio_index = i
                    break
        self.music_name = name
        try:
            self.music_var.set(name)
        except (tk.TclError, AttributeError):
            pass
        if announce:
            self.speak("♪ 连接中：%s" % name)
            self.show_music_bubble()
        self._save_config()
        return True

    def _radio_switch(self, step, announce=True):
        """在 radio_list 里换台（首尾相接）；没有列表就重放当前台。"""
        if not self.radio_list:
            if self.radio_station:
                return self.play_radio(self.radio_station, announce=announce)
            return False
        n = len(self.radio_list)
        cur = (self.radio_station or {}).get("url")
        idx = self.radio_index if 0 <= self.radio_index < n else -1
        for k in range(1, n + 1):
            st = self.radio_list[(idx + int(step) * k) % n]
            if n > 1 and str(st.get("url")) == cur:
                continue
            if self.play_radio(st, stations=self.radio_list, announce=announce):
                return True
        return False

    def next_station(self):
        return self._radio_switch(1)

    def prev_station(self):
        return self._radio_switch(-1)

    def open_radio(self):
        """打开「在线电台」窗口（右键 → 音乐 → 在线电台…）。"""
        try:
            if self._radio_dialog is None:
                self._radio_dialog = pet_radio.RadioDialog(self)
            self._radio_dialog.show()
        except Exception as exc:            # noqa: BLE001
            self.speak("（电台窗口没打开：%s）" % exc)
            return False
        return True

    def toggle_music(self):
        if self.music_online:
            state = self.stream.status()
            if state == "paused":
                self.stream.resume()
                self.music_paused = False
                self.show_music_bubble()
            elif state in ("playing", "opening"):
                self.stream.pause()
                self.music_paused = True
                self._hide_music_bubble()
                self.speak("先停一下：%s" % (self.radio_station or {}).get("name", "电台"))
            else:
                return self.play_radio(self.radio_station or {}, announce=False)
            return True
        if not self.music.is_open:
            return self.play_music()
        if self.music_paused:
            try:
                self.music.resume()
            except (pet_music.MusicError, RuntimeError) as exc:
                self._music_log("music: resume failed %r" % (exc,))
                return False
            self.music_paused = False
            # 继续放：控制条直接挂回来（不另外说一句，免得两个气泡打架）
            self.show_music_bubble()
        else:
            try:
                self.music.pause()
            except (pet_music.MusicError, RuntimeError) as exc:
                self._music_log("music: pause failed %r" % (exc,))
                return False
            self.music_paused = True
            self._hide_music_bubble()
            self.speak("先停一下：%s" % pet_music.title_of(self.music.path))
        return True

    def stop_music(self):
        try:
            self.music.close()
        except (pet_music.MusicError, RuntimeError) as exc:
            self._music_log("music: close failed %r" % (exc,))
        try:
            self.stream.close()
        except (pet_music.MusicError, RuntimeError) as exc:
            self._music_log("radio: close failed %r" % (exc,))
        self.music_paused = False
        self.music_online = False
        self._radio_retry = 0
        self._hide_music_bubble()
        self.speak("不放了。")

    def _switch_music(self, step):
        """切歌：step=+1 下一首，-1 上一首；首尾相接（到底了绕回另一头）。

        原来在放就接着放；原来是暂停状态，就停在新歌的开头（不擅自开始放）。
        """
        if self.music_online:
            return self._radio_switch(step)
        if not self.music_files:
            return False
        names = [os.path.basename(p) for _t, p in self.music_files]
        index = names.index(self.music_name) if self.music_name in names else -1
        target = self.music_files[(index + int(step)) % len(self.music_files)][1]
        was_paused = self.music_paused
        if not self.play_music(target):
            return False
        if was_paused:
            try:
                self.music.pause()
            except (pet_music.MusicError, RuntimeError) as exc:
                self._music_log("music: pause after switch failed %r" % (exc,))
            self.music_paused = True
            self._hide_music_bubble()
            self.speak("停在新的一首：%s" % pet_music.title_of(target))
        else:
            self.show_music_bubble()
        return True

    def _key_switch_music(self, step):
        def handler(event=None):
            if self._music_active():
                self._switch_music(step)
                return "break"
            return None
        return handler

    def next_music(self):
        return self._switch_music(1)

    def prev_music(self):
        return self._switch_music(-1)

    def open_web(self, url, name=""):
        """用系统默认浏览器打开一个网址。"""
        url = normalize_url(url) or url

        def launch():
            import webbrowser
            if not webbrowser.open(url, new=2):
                raise RuntimeError("webbrowser.open 返回 False")

        try:
            # 浏览器没响应时 ShellExecute 会一直等，别把 UI 拖住
            self._guarded_call(launch, 8.0, "浏览器")
        except Exception as exc:            # noqa: BLE001
            self._music_log("web: open %r failed %r" % (url, exc))
            self.speak("（这个网页没打开：%s）" % (name or url))
            return False
        self.speak("给你打开%s了。" % (name or url))
        return True

    # ---- 自定义快捷网页 -------------------------------------------------
    def web_links(self):
        """菜单里要列的站点：内置那几个 + 用户自己加的（同名的不重复）。"""
        out = [{"name": n, "url": u} for n, u in DEFAULT_WEB_LINKS]
        seen = {n.lower() for n, _u in DEFAULT_WEB_LINKS}
        for item in self.cfg.get("web_links") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            url = normalize_url(str(item.get("url", "")))
            if not name or not url or name.lower() in seen:
                continue
            seen.add(name.lower())
            out.append({"name": name, "url": url})
        return out

    def _custom_web_links(self):
        builtin = {n.lower() for n, _u in DEFAULT_WEB_LINKS}
        return [x for x in self.web_links() if x["name"].lower() not in builtin]

    def _fill_web_menu(self):
        """重建「打开网页」子菜单（放在点完之后执行，不在菜单弹出时改）。"""
        menu = getattr(self, "web_menu", None)
        if menu is None:
            return
        menu.delete(0, "end")
        for item in self.web_links():
            menu.add_command(
                label=item["name"],
                command=lambda u=item["url"], n=item["name"]:
                    self._defer(self.open_web, u, n))
        custom = self._custom_web_links()
        menu.add_separator()
        menu.add_command(label="＋ 添加网页…",
                         command=lambda: self._defer(self.ask_add_web))
        if custom:
            sub = tk.Menu(menu, tearoff=0)
            for item in custom:
                sub.add_command(
                    label=item["name"],
                    command=lambda n=item["name"]:
                        self._defer(self.remove_web_link, n))
            menu.add_cascade(label="删除自己加的网页", menu=sub)

    def ask_add_web(self):
        """右键「打开网页 → ＋ 添加网页…」：弹窗填名字 + 网址。"""
        dlg = WebLinkDialog(self)
        dlg.show()

    def add_web_link(self, name, url):
        """记住一个快捷网页；网址不像样就拒绝（返回 False）。"""
        url = normalize_url(url)
        name = (name or "").strip() or url.split("://", 1)[-1].split("/")[0]
        if not url or not name:
            self.speak("这个网址没看懂，写成 www.example.com 这样再试一次？")
            return False
        links = [dict(x) for x in (self.cfg.get("web_links") or [])
                 if isinstance(x, dict)]
        links = [x for x in links
                 if str(x.get("name", "")).strip().lower() != name.lower()]
        links.append({"name": name, "url": url})
        self.cfg["web_links"] = links
        self._save_config()
        self._fill_web_menu()
        self.speak("记住了：%s。右键「打开网页」里就能点。" % name)
        return True

    def remove_web_link(self, name):
        links = [dict(x) for x in (self.cfg.get("web_links") or [])
                 if isinstance(x, dict)]
        keep = [x for x in links
                if str(x.get("name", "")).strip().lower() != (name or "").strip().lower()]
        if len(keep) == len(links):
            return False
        self.cfg["web_links"] = keep
        self._save_config()
        self._fill_web_menu()
        self.speak("删掉了：%s。" % name)
        return True

    def _music_volume(self, delta):
        self.music_volume = max(0, min(100, self.music_volume + delta))
        self.music.set_volume(self.music_volume)
        try:
            self.stream.set_volume(self.music_volume)
        except (pet_music.MusicError, RuntimeError):
            pass
        self._fill_music_menu()
        self.speak("音量 %d%%" % self.music_volume)
        self._save_config()

    def rescan_music(self):
        self.music_files = pet_music.scan_music(MUSIC_DIR)
        self._fill_music_menu()
        self.speak("扫到 %d 首歌。" % len(self.music_files))

    def open_music_folder(self):
        try:
            os.makedirs(MUSIC_DIR, exist_ok=True)
            os.startfile(MUSIC_DIR)       # noqa: S606 - 就是要打开资源管理器
        except Exception as exc:          # noqa: BLE001
            self._music_log("music: open folder failed %r" % (exc,))

    def _music_tick(self, now):
        """一首放完了自动接下一首；在线电台连接超时/断了就换台。"""
        if self.music_online:
            if self.music_paused:
                return
            state = self.stream.status()
            if state != getattr(self, "_radio_was", ""):
                self._radio_was = state
                if state == "playing":
                    # 连上了：把「连接中」的气泡换成正式标题
                    self._radio_retry = 0
                    self._radio_tick_at = 0.0
                    if self._music_bubble_wanted:
                        self.show_music_bubble()
            if state == "playing":
                self._radio_retry = 0
                return
            if state == "opening":
                # 开流可能要 25 秒；超过 OPEN_TIMEOUT 就当这个台连不上
                if self.stream.waited() < pet_music.StreamPlayer.OPEN_TIMEOUT:
                    if self._music_bubble_wanted and now >= self._radio_tick_at:
                        self._radio_tick_at = now + 2.0
                        self.show_music_bubble()
                    return
                self.stream.give_up("连接超时")
                state = "error"
            if now < self._radio_tick_at:
                return
            self._radio_tick_at = now + 3.0
            self._music_log("radio: %s" % (state or "idle"))
            if state == "error" and self._radio_retry < 1 and self.radio_station:
                self._radio_retry += 1
                try:
                    self.stream.play(self.radio_station["url"])
                    self.stream.set_volume(self.music_volume)
                    return
                except (pet_music.MusicError, RuntimeError) as exc:
                    self._music_log("radio: retry failed %r" % (exc,))
            self._radio_retry = 0
            if state == "error":
                self.speak("这个台连不上，换一个。")
            if not self._radio_switch(1, announce=False):
                self.speak("电台断了。")
                self.stop_music()
            else:
                self.show_music_bubble()
            return
        if not self.music_files:
            return
        if not self.music.is_open or self.music_paused:
            return
        if self.music.mode() != "stopped":
            return
        names = [os.path.basename(p) for _t, p in self.music_files]
        index = names.index(self.music_name) if self.music_name in names else -1
        nxt = self.music_files[(index + 1) % len(self.music_files)][1]
        self.play_music(nxt)

    def _music_active(self):
        """本地歌或电台，只要有一个在放/暂停/连接中，就算"音乐在跑"。"""
        if self.music_online:
            return self.stream.is_open
        return self.music.is_open

    def _kaomoji_line(self, text, mood=None, rate=1.0):
        """给它自己说的话贴一个颜文字（关掉就原样返回）。"""
        if not getattr(self, "kaomoji_enabled", True) or not text:
            return text
        return kaomoji.decorate(
            text, mood or kaomoji.mood_for_affection(self.affection), rate=rate)

    def set_kaomoji_enabled(self, on, quiet=False):
        on = bool(on)
        changed = on != self.kaomoji_enabled
        self.kaomoji_enabled = on
        if changed:
            self._save_config()
        if not quiet:
            if not on:
                self.speak("好，不戴这些奇怪的表情了。")
            else:
                self.speak(self._kaomoji_line("戴回来，这样说话顺眼多了。"))
        self.sync_settings()
        return on

    def toggle_kaomoji(self):
        return self.set_kaomoji_enabled(not self.kaomoji_enabled)

    def say_kaomoji(self):
        """右键「来一个颜文字」：纯展示，不动别的状态。"""
        mood = kaomoji.mood_for_affection(self.affection)
        self.speak("喏，" + kaomoji.pick(mood) + "（" + mood + "）")

    def speak(self, text, ms=None, background=False):
        """直接显示一句话（不走闲话让路逻辑）。"""
        if self.bubble is None or self._fs_paused:
            # 全屏暂停期间一句话都不冒（气泡会挂在别人全屏画面上）
            return
        if background and self.user_busy:
            return
        self._speech_seq += 1
        text = jp_gloss.add_gloss(text)
        if text == PENDING_TEXT:
            self.pending = text
            ms = ms or PENDING_MS
        else:
            self.pending = None
            # 没指定就按设置里的「气泡停留时长」
            ms = ms or (AI_REPLY_MS if self.pending == PENDING_TEXT
                        else self.bubble_ms)
        try:
            self.bubble.say(text, self.head_anchor(), ms=ms,
                            want_layered=self.layered,
                            avoid=self._chat_rect())
        except Exception:                       # noqa: BLE001
            # 气泡是"锦上添花"：说话失败不能连累点击/菜单/动画
            _log_exception()
        self.jump = max(self.jump, 0.55)

    def _think(self, lane, work, fallback=None, owned=False):
        """显示省略号 -> 后台请求 -> 结果写回气泡。返回是否真的发出去了。"""
        if self.bubble is None or self._fs_paused:
            return False
        if not (self.ai_enabled and self.brain.enabled):
            if fallback:
                self.speak(fallback())
            return False
        if lane in self._ai_lanes:
            return False
        if owned:
            self._owned_epoch += 1
            my_epoch = self._owned_epoch
        else:
            my_epoch = None

        def apply(text):
            self._owned_shown = max(self._owned_shown, my_epoch or 0)
            self.speak(text)

        self.speak(PENDING_TEXT)                 # 占住说话权
        return self._async(work, apply, lane=lane, epoch=my_epoch)

    def speak_random(self):
        """点一下宠物才说话：先用手上备好的 AI 句子，没有就现要一句。"""
        if self.bubble is None:
            return
        # 冷战期不主动找话题：点它也只给一两个字的冷场
        if not self.mood.allow_initiative():
            self.prefetched = None
            if self.chat_win is not None:
                self.chat_win.add_reply(self.mood.idle_line(), [])
            self.speak(self.mood.idle_line())
            return
        if self.prefetched:
            line, self.prefetched = self.prefetched, None
            # 攒的时候可能还没吃醋，拿出来先按现在的脾气剪一刀
            line = self.mood.shape(line)
            if jp_gloss.has_kana(line):
                self.speak(line)
            else:
                self.speak(self._kaomoji_line(line))
            return
        if not self._think("chatter", lambda: self.brain.chatter(),
                           fallback=lambda: random.choice(PHRASES)):
            self.speak(self._kaomoji_line(random.choice(PHRASES)))

    def _prefetch_chatter(self):
        """后台攒一句待机用语，等用户点的时候立刻能显示（不占屏、不打搅）。"""
        # 冷战期不攒待机话：攒下来也会被丢掉，还白花一次请求
        if not self.mood.allow_initiative():
            self.prefetched = None
            return
        # AI 关掉就一句都不该发出去（说明里承诺"完全不联网"）。_maybe_greet
        # 的定时器走的是这条路径，之前少了这道判断，--no-ai 启动照样会
        # 请求一次 DeepSeek
        if not (self.ai_enabled and self.brain.enabled):
            return
        if "chatter" in self._ai_lanes or self.prefetched:
            return
        seed = ("现在时间 %s，已经陪了对方 %d 分钟。"
                % (time.strftime("%H:%M"), max(1, int((self._now() - self.started) / 60))))

        def apply(line):
            line = self.mood.shape(line or "")
            self.prefetched = line or None

        self._async(lambda: self.brain.chatter(seed), apply, lane="chatter")

    def _maybe_greet(self):
        """启动时不弹气泡——气泡只在用户点它的时候出现，免得白占屏幕。"""
        if self.bubble is None:
            return
        self.prefetched = None
        # 句柄要存下来：quit() 靠 _greet_job 取消这个定时器，不存的话提前
        # 退出时它还会去跑已销毁窗口的 after 脚本（stderr 里一堆
        # "invalid command name ..._prefetch_chatter"）
        self._greet_job = self.root.after(900, self._prefetch_chatter)

    # ------------------------------------------------------------ 对话
    def open_chat(self):
        """右键 -> 对话… / 双击：打开常驻聊天窗口（红白窗 + 三个候选回复）。"""
        if self.chat_win is not None:
            self.chat_win.show()            # 已经开着就提到前面
            return
        if not self.ai_enabled:
            self.speak("AI 关掉了，右键「设置…」→「对话」里可以再打开。")
            return
        if not self.brain.enabled:
            self.speak("没配 API Key，右键「AI 设置 → 设置 API Key…」。")
            return
        self.chat_win = ChatDialog(self, title="跟%s说句话" % ai_client.persona_display_name(self._persona))
        self.chat_win.show()                # 常驻：不阻塞、聊完整轮

    def _install_tray(self):
        """系统托盘图标：右键 -> 对话 / 说话 / 退出（在右下角小箭头里那排）。

        托盘是 overrideredirect 宠物唯一稳定能挂"入口"的地方。**拿不到也不在
        任务栏留按钮**：用户要的就是它只出现在右下角「^」里；后台每隔 3 秒重试
        注册（最多 20 次），成功后会自己出现在托盘里。
        """
        try:
            tray_icon = _asset_path("school_badge.ico")
            if not os.path.exists(tray_icon):
                tray_icon = _asset_path("pet.ico")
            self.tray = TrayIcon(
                "桌面宠物（右键：设置 / 退出）", tray_icon,
                [(1, "跟它说话"), (2, "对话…"), (3, "设置…"),
                 (4, "刷新一下"), (5, "取消鼠标穿透"), (6, "退出")],
                self._tray_event, on_ready=self._tray_late_ok)
            if self.tray.start():
                return True
            # 注册没成也别丢对象：后台 WM_TIMER 还在重试，成功后会撤占位窗口
        except Exception:                       # noqa: BLE001
            _log_exception()
            self.tray = None
        return False

    def _tray_late_ok(self):
        """托盘线程调：后台重试终于注册成功了。

        以前这里要撤掉「任务栏占位窗口」；现在不再建那个窗口（用户只要右下角
        小箭头里的图标），所以只需要让设置窗口/菜单里的状态保持最新。
        """
        self._main_thread(self.sync_settings)

    def _tray_event(self, what):
        """托盘线程回调：一律排到 Tk 主线程再动界面。"""
        self._main_thread(self._tray_event_main, what)

    def _tray_event_main(self, what):
        if what == "jump" or what == 1:
            self.jump = 1.0
            self.speak("我在这儿。")
        elif what == 2:
            self.open_chat()
        elif what == 3:
            self.open_settings()
        elif what == 4:
            self.request_refresh()
        elif what == 5:
            # 开了鼠标穿透就点不到宠物本体了，这里留一条后路
            self.set_click_through(False)
        elif what == 6:
            self.quit()

    def _chat_closed(self, win):
        if self.chat_win is win:
            self.chat_win = None

    # ------------------------------------------------------------ 形象人设
    def _persona_state(self, key=None):
        """取（必要时建）某套人设的记忆槽：历史 / 摘要 / 好感度。"""
        chats = self.cfg.get("chats")
        if not isinstance(chats, dict):
            chats = {}
            self.cfg["chats"] = chats
        key = key or self._persona
        state = chats.get(key)
        if not isinstance(state, dict):
            state = {}
            chats[key] = state
        return state

    def _stash_persona(self):
        """把当前记忆/好感度存回当前人设的槽里（切形象前调用）。"""
        state = self._persona_state()
        state["history"] = list(self.brain.history)
        state["context"] = self.brain.context
        state["affection"] = self.affection
        state["turns"] = self.brain.turns
        state["romance"] = self.romance
        state["mood"] = self.mood.dump()

    def _reset_persona_state(self):
        """把当前人设的记忆清空、好感度回到初始值。"""
        self.brain.history = []
        self.brain.context = ""
        self.brain.turns = 0
        self.affection = AFFECTION_START
        self.romance = False
        self.mood.reset()
        self._sync_mood_hint(None)
        self._stash_persona()

    def _apply_persona(self, load=False):
        """按当前形象设置 AI 人设（提示词 + 记忆 + 好感度）。

        每个形象一套人设和一份记忆：捧花少年是闷骚少年、内置那三张是话痨朋友；
        互不串味，好感度也各算各的。
        """
        key = persona_key_for(self.image_name, self.cfg)
        if key == getattr(self, "_persona", None) and not load:
            self.brain.system_prompt = ai_client.persona_prompt(
                key, romance=self.romance)
            self._update_persona_menu()
            return
        if getattr(self, "_persona", None) is not None:
            self._stash_persona()
        self._persona = key
        state = self._persona_state(key)
        fresh = state.get("affection") is None and state.get("history") is None
        if fresh:
            if load:
                # 启动时：配置里那份（老版本只有单份记忆）就当成这套人设的
                self._stash_persona()
            else:
                # 第一次用这套人设：白纸开局（不继承上一个形象的好感度/记忆）
                self._reset_persona_state()
        else:
            self.brain.history = [m for m in (state.get("history") or [])
                                  if isinstance(m, dict)]
            self.brain.context = str(state.get("context") or "")
            try:
                self.brain.turns = int(state.get("turns") or 0)
            except (TypeError, ValueError):
                self.brain.turns = 0
            try:
                self.affection = max(0, min(100, int(state.get("affection",
                                                               AFFECTION_START))))
            except (TypeError, ValueError):
                self.affection = AFFECTION_START
            # 这套人设的恋爱状态（老配置没有这个键 = 还没在一起）
            self.romance = bool(state.get("romance"))
        # 情绪状态也跟着人设走（老配置没有这个键 = 日常）
        self.mood = pet_mood.MoodEngine.load(state.get("mood"))
        self._sync_mood_hint(None)
        self.brain.system_prompt = ai_client.persona_prompt(
            key, romance=self.romance)
        self.brain.persona = key            # 好感度语气按人设选表
        if self.chat_win is not None:
            # 窗口里显示的是"上一个人设"的对话，换了人设就清掉重画
            self.chat_win.switch_persona(self._persona, self.affection)
        self._update_affection_menu()
        self._update_persona_menu()
        self._save_config()

    def set_persona(self, key):
        """把当前这张立绘指定成人设 key（写进配置的 personas，切图也记得）。"""
        key = str(key or "").strip()
        if not key:
            return
        personas = self.cfg.get("personas")
        if not isinstance(personas, dict):
            personas = {}
            self.cfg["personas"] = personas
        personas[self.image_name] = key
        self._persona = None            # 逼 _apply_persona 重新加载这一套
        self._apply_persona()
        try:
            self.persona_var.set(key)
        except Exception:               # noqa: BLE001
            pass
        self.speak("好，我是%s。" % ai_client.persona_display_name(key))

    def _update_persona_menu(self):
        menu = getattr(self, "_persona_menu", None)
        if menu is not None:
            try:
                self._reload_persona_menu()
            except tk.TclError:
                pass
        menu = getattr(self, "_affection_menu", None)
        if menu is None:
            return
        try:
            for i in range(menu.index("end") + 1):
                if str(menu.entrycget(i, "label")).startswith("人设"):
                    label = "人设: %s" % ai_client.persona_display_name(self._persona)
                    if self.romance:
                        label += " ♥ 恋人"
                    menu.entryconfigure(i, label=label)
                    break
            if getattr(self, "persona_var", None) is not None:
                self.persona_var.set(self._persona)
        except tk.TclError:
            pass

    def open_persona_editor(self):
        """打开人设编辑器（单开）。"""
        if getattr(self, "persona_editor", None) is not None:
            try:
                self.persona_editor.show()
                return
            except Exception:               # noqa: BLE001
                self.persona_editor = None
        try:
            self.persona_editor = pet_persona.PetPersonaDialog(self).show()
        except Exception as exc:            # noqa: BLE001
            self.persona_editor = None
            self.speak("人设编辑器打不开：%s" % exc)

    def _load_custom_personas(self):
        """把配置里的自定义人设注册进 ai_client（启动、改完都跑一遍）。"""
        raw = self.cfg.get("custom_personas")
        if not isinstance(raw, dict):
            raw = {}
        clean = {}
        for key, data in raw.items():
            if not isinstance(data, dict):
                continue
            key = str(key or "").strip()
            prompt = str(data.get("prompt") or "").strip()
            if not key or not prompt or key in ai_client.BUILTIN_PERSONAS:
                continue
            tones = pet_persona.normalize_tones(data.get("tones"))
            clean[key] = {
                "name": str(data.get("name") or key).strip() or key,
                "hint": str(data.get("hint") or "").strip(),
                "prompt": prompt,
                "tones": [[t, s] for t, s in tones],
                "romance_line": str(data.get("romance_line") or "").strip(),
            }
            ai_client.register_persona(
                key, name=clean[key]["name"], prompt=prompt,
                hint=clean[key]["hint"], tones=tones,
                romance_line=clean[key]["romance_line"], romance=True)
        self.custom_personas = clean

    def save_custom_persona(self, key, data):
        """存一个人设：写配置 + 注册 + 刷新菜单 + 正在用的话立刻换提示词。"""
        key = str(key or "").strip()
        if not key or key in ai_client.BUILTIN_PERSONAS:
            return False
        tones = pet_persona.normalize_tones((data or {}).get("tones"))
        item = {
            "name": str((data or {}).get("name") or key).strip() or key,
            "hint": str((data or {}).get("hint") or "").strip(),
            "prompt": str((data or {}).get("prompt") or "").strip(),
            "tones": [[t, s] for t, s in tones],
            "romance_line": str((data or {}).get("romance_line") or "").strip(),
        }
        if not item["prompt"]:
            return False
        self.custom_personas[key] = item
        ai_client.register_persona(
            key, name=item["name"], prompt=item["prompt"], hint=item["hint"],
            tones=tones, romance_line=item["romance_line"], romance=True)
        self.cfg["custom_personas"] = dict(self.custom_personas)
        self._reload_persona_menu()
        if getattr(self, "_persona", None) == key:
            self.brain.system_prompt = ai_client.persona_prompt(
                key, romance=self.romance)
            self._update_persona_menu()
        self._save_config()
        return True

    def delete_custom_persona(self, key):
        """删一个自定义人设；正在用的话退回默认人设。"""
        key = str(key or "").strip()
        if not key or key not in self.custom_personas:
            return False
        self.custom_personas.pop(key, None)
        ai_client.forget_persona(key)
        self.cfg["custom_personas"] = dict(self.custom_personas)
        personas = self.cfg.get("personas")
        if isinstance(personas, dict):
            for image, name in list(personas.items()):
                if name == key:
                    personas[image] = DEFAULT_PERSONA
        if getattr(self, "_persona", None) == key:
            self._persona = None
            self._apply_persona()
        self._reload_persona_menu()
        self._save_config()
        return True

    def _reload_persona_menu(self):
        """按当前的 PERSONA_PROMPTS 重建「这张图的人设」子菜单。"""
        menu = getattr(self, "_persona_menu", None)
        if menu is None:
            return
        menu.delete(0, "end")
        current = getattr(self, "_persona", DEFAULT_PERSONA)
        if getattr(self, "persona_var", None) is None:
            self.persona_var = tk.StringVar(value=current)
        for key in ai_client.PERSONA_PROMPTS:
            menu.add_radiobutton(
                label="%s（%s）" % (ai_client.persona_display_name(key), key),
                value=key, variable=self.persona_var,
                command=lambda k=key: self._defer(self.set_persona, k))
        menu.add_separator()
        self._menu_add(menu, "编辑人设…", icon="key",
                       command=lambda: self._defer(self.open_persona_editor))
        try:
            self.persona_var.set(current)
        except tk.TclError:
            pass

    def ask_ai(self, text):
        """把一句话发给 AI：气泡占位 -> 回复进气泡 + 聊天窗口 + 好感度。

        一次请求同时拿回：宠物的一句话、好感度变化、以及给用户的三个候选回复。
        """
        if not self._think_chat(text):
            return False
        if self.brain.needs_summary() and "summary" not in self._ai_lanes:
            self._summarize_async()
        return True

    def _chat_note(self, text):
        """在聊天窗口里补一句说明（并弹个气泡）。

        聊天窗口最怕"什么都看不到"：AI 关着、没配 key、上一句还没回来的时候
        都要留一句话，用户才知道发生了什么。选项也补满三条 —— 空着三个按钮
        比没有按钮更让人困惑。
        """
        text = self._kaomoji_line(text, rate=0.5)
        self.speak(text)
        if self.chat_win is not None:
            # 不拿兜底池凑选项：拿不到 AI 选项就收起那一排，别塞空话
            self.chat_win.add_reply(text, [])
        return False

    def _think_chat(self, text):
        """聊天用的异步请求（回复里带着选项和好感度变化）。"""
        if self.bubble is None and self.chat_win is None:
            return False
        if not (self.ai_enabled and self.brain.enabled):
            return self._chat_note(random.choice(PHRASES))
        if "chat" in self._ai_lanes:
            return self._chat_note("（上一句还在想，等我一下）")
        # 先过一遍情绪：这句话是在提别人/敷衍它/哄它，还是普通聊天。
        # 事件和状态机都记在闭包里：万一这几秒里切了人设，回复仍按这一轮
        # 的脾气剪，别拿新形象的状态去剪旧形象的回复。
        mood = self.mood
        event = mood.observe(text)
        self._sync_mood_hint(event)
        self._owned_epoch += 1
        my_epoch = self._owned_epoch
        affection = self.affection

        def work():
            reply, delta, options, err = self.brain.chat_with_options(text, affection)
            if err and not reply:
                reply = "（%s）" % err
            return {"reply": reply, "delta": delta, "options": options}

        def apply(data):
            self._owned_shown = max(self._owned_shown, my_epoch)
            if not isinstance(data, dict):
                self.speak(self._kaomoji_line(str(data), rate=0.6))
                return
            reply = str(data.get("reply") or "")
            # 冷战话多就换成短句，吃醋只留半句；冷战期连颜文字都不挂
            reply = mood.shape(reply, event)
            # 有日语的回复下面会补一行中文，再挂颜文字就太挤、也容易把颜文字
            # 折成两行；这种回复就不挂，让汉字当表情
            if mood.allows_kaomoji() and not jp_gloss.has_kana(reply):
                reply = self._kaomoji_line(reply, rate=0.7)
            self.speak(reply)
            # 生气的时候嘴上再热络也不加分：冷战只许扣不许加，吃醋最多 +1
            self._apply_affection(mood.clamp_delta(data.get("delta") or 0))
            if self.chat_win is not None:
                # 直接用 AI 现写的选项（chat_with_options 已经单独要过一轮），
                # 有几条显示几条；一条都没有就收起选项排，不再拿兜底池凑空话
                opts = [str(o).strip() for o in (data.get("options") or [])
                        if str(o).strip()][:3]
                self.chat_win.add_reply(reply, opts)
            # 冷战时偶尔"撤回一条""手滑点赞"：只写看得见的动作，不写心理
            if self.mood is mood:
                self._mood_theater(event)

        self.speak(PENDING_TEXT)             # 占住说话权
        return self._async(work, apply, lane="chat", epoch=my_epoch)

    def _sync_mood_hint(self, event=None):
        """把当前情绪翻成给模型看的表演要求（挂在 brain 上，下一句就生效）。"""
        brain = getattr(self, "brain", None)
        if brain is None:
            return
        try:
            hint = self.mood.prompt(event)
            opts = self.mood.options_hint()
        except Exception:                   # noqa: BLE001 - 情绪出岔子不能挡住聊天
            hint, opts = "", ""
        brain.mood_hint = hint
        brain.mood_options_hint = opts
        brain.mood_state = self.mood.state
        try:
            self._update_affection_menu()    # 菜单里跟上"· 冷战"这种状态
        except Exception:                   # noqa: BLE001
            pass

    def _mood_theater(self, event):
        """冷战时的那点小动作：撤回一条，或者手滑点赞很久以前的消息。"""
        if self.chat_win is None or not event:
            return
        try:
            action = self.mood.theater(event)
        except Exception:                   # noqa: BLE001
            return
        if not action:
            return
        try:
            if action == "withdraw":
                self.chat_win.withdraw_last()
            else:
                self.chat_win.add_note("（手滑点了个赞——翻的是你很久以前那条）")
        except Exception:                   # noqa: BLE001 - 界面小动作失败不影响聊天
            pass

    def set_affection(self, value):
        """修改器用：直接把好感度设成某个值（0-100），同步界面和存档。"""
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = self.affection
        self.affection = max(0, min(100, value))
        self._stash_persona()
        if self.chat_win is not None:
            self.chat_win.set_affection(self.affection)
            self.chat_win.refresh_romance()
        self._update_affection_menu()
        self._save_config()
        return self.affection

    def _apply_affection(self, delta):
        """好感度变化：夹在 0-100，存盘，并同步到聊天窗口。"""
        try:
            delta = int(delta)
        except (TypeError, ValueError):
            delta = 0
        if not delta:
            if self.chat_win is not None:
                self.chat_win.set_affection(self.affection)
            # delta 为 0 也要把这一轮历史写回人设槽；否则聊天记录只在
            # 顶层 brain 里，切形象/重开后好感度和记忆槽会对不上。
            self._stash_persona()
            self._save_config()
            return
        before = self.affection
        self.affection = max(0, min(100, self.affection + delta))
        self._stash_persona()
        if self.chat_win is not None:
            self.chat_win.set_affection(self.affection, delta)
            # 好感度刚到 100（或掉下去）时，恋爱选项要跟着出现/消失
            self.chat_win.refresh_romance()
        self._update_affection_menu()
        self._save_config()
        if before < AFFECTION_HINT_STEP <= self.affection:
            self.speak("（它好像更喜欢你了。）")

    # ------------------------------------------------------------ 恋爱
    def romance_available(self):
        """现在能不能谈恋爱：人设支持 + 好感度满 100 + 还没在一起。"""
        if self.romance or self.affection < 100:
            return False
        return getattr(self, "_persona", None) in ai_client.ROMANCE_PERSONAS

    def trigger_romance(self):
        """点了聊天窗口里的「♡ 恋爱」：它说出那句告白，之后就是恋人关系。"""
        if not self.romance_available():
            return False
        self.romance = True
        self._stash_persona()
        self.brain.system_prompt = ai_client.persona_prompt(
            self._persona, romance=True)
        self._save_config()
        line = ai_client.romance_line(self._persona)
        self.speak(line)
        if self.chat_win is not None:
            self.chat_win.set_affection(self.affection)
            self.chat_win.add_reply(line, [])
            self.chat_win.refresh_romance()
        self._update_persona_menu()
        return True

    def open_game(self, key):
        """右键 → 小游戏。玩完的好感度、成绩都在 pet_games 里处理。"""
        try:
            pet_games.open_game(self, key)
        except Exception:                       # noqa: BLE001
            _log_exception()
            self.speak("这个玩不了，等下再试。")
        else:
            self._refresh_game_stats()

    def _game_stats_text(self):
        st = self.cfg.get("games")
        if not isinstance(st, dict):
            st = {}
        parts = []
        if st.get("mole_best"):
            parts.append("打地鼠 %d" % int(st["mole_best"]))
        if st.get("guess_best"):
            parts.append("猜数字 %d 次" % int(st["guess_best"]))
        if st.get("memory_best"):
            parts.append("翻牌 %d 步" % int(st["memory_best"]))
        if st.get("rps_wins"):
            parts.append("猜拳赢 %d 次" % int(st["rps_wins"]))
        return "成绩: " + " · ".join(parts) if parts else "还没有成绩，玩一局试试"

    def _refresh_game_stats(self):
        menu = getattr(self, "_game_menu", None)
        if menu is None:
            return
        try:
            menu.entryconfigure(self._games_stats_index,
                                label=self._game_stats_text())
        except Exception:                       # noqa: BLE001
            pass

    def _summarize_async(self):
        """把老对话压成摘要，控制 token；不碰气泡，所以不参与说话权。"""
        if "summary" in self._ai_lanes:
            return
        self._ai_lanes.add("summary")

        def runner():
            try:
                self.brain.summarize_old()
            except Exception:                   # noqa: BLE001
                pass
            self._main_thread(self._summary_done)

        threading.Thread(target=runner, daemon=True, name="pet-ai-summary").start()

    def _summary_done(self):
        self._ai_lanes.discard("summary")
        self._save_config()

    def set_ai_enabled(self, on, quiet=False):
        on = bool(on)
        changed = on != self.ai_enabled
        self.ai_enabled = on
        self.cfg["ai"] = on
        if hasattr(self, "ai_var"):
            try:
                self.ai_var.set(on)
            except Exception:                   # noqa: BLE001
                pass
        if changed:
            self._save_config()
        if not quiet:
            self.speak("AI 开着呢，随时找我聊。" if on else "那我先安静一会儿。")
        self.sync_settings()
        return on

    def toggle_ai(self):
        self.set_ai_enabled(not self.ai_enabled)

    def open_modifier(self):
        """右键「修改器…」：密码解锁后改好感度。"""
        ModifierDialog(self).show()

    def confirm_reset(self):
        """右键「重置」：确认后清空对话/记忆并恢复出厂（API 保留）。"""
        text = ("会清空所有形象的对话和记忆，好感度改为 20，"
                "其余设置恢复出厂。\n\nAPI Key / 模型设置会保留。\n\n"
                "确定要重置吗？")
        with self._modal():
            ok = messagebox.askyesno("重置", text, parent=self.root)
        if ok:
            self.reset_all()

    def reset_all(self):
        """一键重置（API Key / 模型除外）。

        这个操作会真的清掉所有 personas 的记忆槽、当前 brain、恋爱状态，
        并把立绘/大小/气泡/AI/位置/置顶/透明度/点击穿透都恢复默认。
        API 只保留 key 和 model，不碰 brain.api_keys。
        """
        api_key = self.cfg.get("api_key")
        model = self.brain.model or DEFAULT_MODEL
        if not api_key:
            keys = list(getattr(self.brain, "api_keys", []) or [])
            if keys and set(keys) != set(BUILTIN_API_KEYS):
                api_key = ",".join(keys)

        self._restore_shoot_home()
        try:
            self.hearts.clear()
            self.danmaku.clear()
            self.shoot_fx.clear()
        except Exception:                       # noqa: BLE001
            pass
        self.petting_until = 0.0
        self._pet_energy = 0.0
        self._pet_press = 0.0
        self._pet_burst_pending = 0
        self._pet_sparkle_pending = 0
        self._pet_pat_points = []
        self._swipe = []
        self._pet_reset_gesture()
        self._body_track = []
        self._circle_track = []
        self._shake_track = []
        self._last_extra_gesture = 0.0
        self._pet_last_seen = 0.0
        self._spin_until = 0.0
        self._spin_angle = 0.0
        self._dodge_until = 0.0
        self._dodge_dx = 0.0
        self.shooting_until = 0.0
        self._shoot_energy = 0.0
        self._shoot_kick = 0.0
        self.squash = 0.0
        self.jump = 0.0
        self.offset = [0.0, 0.0]
        self.target = [0.0, 0.0]

        names = [im.name for im in self.images]
        name = DEFAULT_IMAGE if DEFAULT_IMAGE in names else names[0]
        chats = {}
        for persona in ai_client.PERSONA_PROMPTS:
            chats[persona] = {"history": [], "context": "",
                              "affection": AFFECTION_START, "turns": 0,
                              "romance": False, "mood": {}}
        # 先造一份干净的配置；API key 和 model 单独保留
        cfg = {
            "image": name,
            "bubble": True,
            "kaomoji": True,
            "scale": self.DEFAULT_SCALE,
            "style": "colorkey",
            "ai": True,
            "model": model,
            "context": "",
            "affection": AFFECTION_START,
            "romance": False,
            "brain": {"context": "", "turns": 0, "history": []},
            "chats": chats,
            "gestures": True,
            "click_speak": True,
            "pause_fullscreen": True,
            "auto_restart": True,
            "bubble_ms": 4000,
            "anim_level": "normal",
            "gesture_sensitivity": "normal",
            "shake_refresh": False,
            "autostart": False,
        }
        if api_key:
            cfg["api_key"] = api_key
        self.cfg = cfg
        self.affection = 20
        self.romance = False
        self.mood.reset()
        self.ai_enabled = True
        self.bubble_enabled = True
        self.topmost = False
        self.gestures_enabled = True
        self.click_speak = True
        self.pause_fullscreen = True
        self.auto_restart = True
        self.click_through = False
        self.brain.history = []
        self.brain.context = ""
        self.brain.turns = 0

        # 切回默认立绘/后端。_persona 先清空，避免把旧人设的记忆又塞回去。
        self._persona = None
        try:
            self._set_image_impl(name)
        except Exception:                       # noqa: BLE001
            _log_exception()
        try:
            if abs(self.scale - self.DEFAULT_SCALE) > 1e-6:
                self.set_scale(self.DEFAULT_SCALE)
        except Exception:                       # noqa: BLE001
            _log_exception()

        # 气泡 / AI / 置顶 / 点击穿透 / 透明度 / 位置
        self.bubble_enabled = True
        if self.bubble is None:
            self.bubble = SpeechBubble(self.root,
                                       self._active_image().key or "#ffffff")
        try:
            self.root.attributes("-topmost", False)
            self.lower_to_desktop()
        except Exception:                       # noqa: BLE001
            pass
        try:
            self.backend.set_click_through(False)
        except Exception:                       # noqa: BLE001
            pass
        try:
            self.set_opacity(1.0, quiet=True)
        except Exception:                       # noqa: BLE001
            pass

        # 再强制落一次身份/记忆/好感度（_apply_persona 可能从槽里读了旧值）
        persona = persona_key_for(name, self.cfg)
        self._persona = persona
        self.brain.history = []
        self.brain.context = ""
        self.brain.turns = 0
        self.affection = 20
        self.romance = False
        self.mood.reset()
        self.cfg["chats"] = chats
        self.cfg["context"] = ""
        self.cfg["affection"] = 20
        self.cfg["romance"] = False
        self.cfg["brain"] = {"context": "", "turns": 0, "history": []}
        self.cfg["model"] = model
        self.cfg["ai"] = True
        self.cfg["bubble"] = True
        self.cfg["scale"] = self.DEFAULT_SCALE
        self.cfg["image"] = name
        self.cfg["style"] = "colorkey"
        self._stash_persona()
        self._sync_mood_hint(None)
        self.brain.system_prompt = ai_client.persona_prompt(persona)
        if self.chat_win is not None:
            self.chat_win.switch_persona(persona, 20)
        self._update_affection_menu()
        self._update_persona_menu()
        self.reset_position()
        self._save_config()

        # 同步菜单里的勾选状态
        for attr, value in (("ai_var", True),
                            ("scale_var", self.DEFAULT_SCALE),
                            ("image_var", name)):
            var = getattr(self, attr, None)
            try:
                if var is not None:
                    var.set(value)
            except Exception:                   # noqa: BLE001
                pass
        self.sync_settings()
        self.speak("已重置为出厂设置（API 设置保留）。")

    def set_api_key(self):
        """弹输入框改 key；留空表示恢复用内置的。"""
        dlg = ChatDialog(self, title="设置 API Key",
                         hint="留空用内置（两个轮换）· 多个 key 用逗号分隔 · Enter 保存",
                         secret=True, one_shot=True)
        value = dlg.ask()
        if value is None:
            return
        value = value.strip()
        if value:
            self.cfg["api_key"] = value
            self.brain.api_key = value
            self.speak("Key 记下了，试试跟我说话。")
        else:
            self.cfg.pop("api_key", None)
            self.brain.api_key = BUILTIN_API_KEYS
            self.speak("改回内置 key 了（两个轮换）。")
        self._save_config()

    # ------------------------------------------------------------ 动画
    @staticmethod
    def _now():
        return time.monotonic()

    def _schedule_tick(self, delay=None):
        """排下一帧。

        总是先取消上一张票再排新的：嵌套事件循环（对话框、菜单）里
        after 回调也会被跑到，不取消就会越排越多，一帧抖成两帧甚至更多。
        """
        delay = self.FRAME_MS if delay is None else delay
        job, self._tick_job = self._tick_job, None
        if job is not None:
            try:
                self.root.after_cancel(job)
            except Exception:                   # noqa: BLE001
                pass
        try:
            self._tick_job = self.root.after(delay, self._tick)
        except tk.TclError:
            self._tick_job = None

    def _tick(self):
        if not self._alive:
            return
        if self._in_tick:
            # 模态对话框/右键菜单会开一层嵌套事件循环，把这帧也跑一遍。
            # 此时 _tick_body 还停在栈上，再进去就是重入（状态被改两次、
            # 气泡跟着抖、偶尔真卡住）。这里只刷心跳、把下一帧排上就走。
            self._last_tick = self._now()
            self._schedule_tick()
            return
        self._in_tick = True
        try:
            self._tick_body()
        except tk.TclError:
            pass    # 窗口正在销毁，正常
        except Exception:
            # GUI 里异常会静默消失，落一份堆栈方便排查；动画照常继续
            _log_exception()
        finally:
            self._in_tick = False
            # 摸头/爱心期间把帧率提到 40fps；平时还是 25fps 省 CPU
            delay = self.FRAME_MS
            try:
                if (self.petting_active() or self.hearts.active()
                        or self.danmaku.active() or self.shooting_active()
                        or self._now() < self._spin_until):
                    delay = min(delay, self.PET_FRAME_MS)
            except Exception:                   # noqa: BLE001 - 别让调度挂掉
                pass
            # 心跳：看门狗靠这个判断主线程有没有卡死（放在 finally 里，
            # 一帧要画很久的话它看到的是"这一帧还没画完"）
            self._last_tick = self._now()
            self._schedule_tick(delay)

    def _drain_callbacks(self):
        """在主线程里执行工作线程排进来的回调。"""
        while True:
            try:
                func, args = self._callbacks.get_nowait()
            except queue.Empty:
                return
            try:
                func(*args)
            except tk.TclError:
                return
            except Exception:                   # noqa: BLE001
                _log_exception()

    def _report_callback_exception(self, exc, val, tb):
        """Tk 回调（菜单项、按键绑定、after 脚本）里漏出来的异常。

        Tkinter 默认只往 stderr 打一份，而 exe/pythonw 根本没有控制台 ——
        "点菜单没反应"、"宠物突然不动了"这类现象就是这么消失的。这里改成
        落进 pet_error.log。
        """
        _log_exception((exc, val, tb))

    def _tick_body(self):
        self._drain_callbacks()
        flush_pending_free()             # 主线程里丢掉上一帧攒下的 Tk 图片
        now = self._now()
        dt = min(0.10, max(0.0, now - self._last_tick))
        self._last_tick = now

        # 启动时压层级、以及菜单里点的动作，都在这里做（不在菜单的模态循环里）
        if self._pending_lower:
            self._pending_lower = False
            self.lower_to_desktop()
        if now < self._pos_check_until:
            self._verify_position()
        # 「刷新一下」/看门狗急救：等回到主线程、回到 tick 里再动手
        if self._refresh_requested:
            self.refresh_pet()
        # 前台有全屏窗口就先暂停（游戏/全屏视频里不要有只猫在动）
        if now >= self._next_fs_check:
            self._next_fs_check = now + 0.3
            self._update_fullscreen(now)
        self._run_pending_action()
        if self._fs_paused:
            # 暂停期间只保留心跳、急救和音乐状态的维护，别的都别做
            return
        # 看门狗急救要用的窗口句柄，隔一会儿对齐一次（只在主线程取）
        if now >= self._hwnd_refresh_at:
            self._hwnd_refresh_at = now + 2.0
            self._refresh_hwnds()

        # 歌放完了自动接下一首（0.4 秒问一次 MCI，别每帧都问）
        if now >= self._music_next_check:
            self._music_next_check = now + 0.4
            try:
                self._music_tick(now)
            except Exception as exc:    # noqa: BLE001
                self._music_log("music tick failed %r" % (exc,))

        # 只在主线程里手动回收：Tkinter 对象的 __del__ 会在别的线程里跑成
        # "main thread is not in main loop"（Tk 图片删不掉，严重的会 Tcl_Panic
        # 直接 abort）。自动 GC 关掉后，回收时机完全由这里决定。
        # 说话/特效/摸头的时候不回收：全量 collect 要遍历所有容器，正画到一半
        # 撞上会顿一下，看起来就是"点一下气泡卡住"。忙的时候只收年轻代，
        # 而且推到下一轮；等画面安静下来再做一次彻底的。
        if now >= self._next_gc:
            busy = (self.bubble is not None and self.bubble.visible()) \
                or self.hearts.active() or self.danmaku.active()
            if busy:
                self._next_gc = now + 1.0
                gc.collect(0)
            else:
                self._next_gc = now + GC_EVERY_S
                gc.collect()

        # 被窗口完全盖住就暂停：不画动画、不调 AI，只偶尔看一眼有没有重新露出来
        # 启动那两秒定位还没稳定（第一次查询时窗口可能还在旧位置），这期间查得
        # 勤一点，否则"其实被盖住"这个状态要等半秒多才反应过来。
        interval = VISIBLE_POLL_MS if now >= self._pos_check_until else 120
        if now >= self._next_visible_check:
            self._next_visible_check = now + interval / 1000.0
            was = self.visible
            self.visible = not self.check_covered()
            if self.visible != was:
                if self.visible:
                    self.lower_to_desktop()
                    self.phase = random.uniform(0, math.tau)
                elif self.bubble:
                    self.bubble.hide()          # 被盖住了就别让气泡留在上面
        # 光标采样放在"被盖住就 return"之前：桌宠现在永远待在窗口最底层，
        # 桌面上只要开着别的窗口，visible 就可能是 False。手势判定不能跟着停
        # ——否则用户会觉得"手势失灵"（透明贴边窗口、壁纸窗口、稍微压住一点的
        # 全屏工具都会造成这种误判）。采样本身很便宜：一次 GetCursorPos 加两个
        # deque，盖住时反正也不画动画。
        self._poll_cursor()                  # 划过检测：按帧采样光标（不依赖钩子）
        # 摸头时帧率会从 25fps 提到 40fps，"每帧"动画都按真实时间折算，
        # 不然同一条呼吸/回弹在两种帧率下速度不一样，看着会一顿一顿的
        frame_k = max(0.25, min(2.5, dt * 1000.0 / self.FRAME_MS))

        # 放歌时的常驻气泡：被别的窗口盖住就跟着藏起来（上面已经 hide 过），
        # 露出来之后再挂回去；中间要是说了别的话（AI 回复等），等它说完、
        # 隔 MUSIC_BUBBLE_IDLE_S 秒再挂回来，别两个气泡来回抢。
        if (self._music_bubble_wanted and self.visible and self.bubble is not None
                and self.music.is_open and not self.music_paused
                and not self._ai_lanes and now >= self._music_bubble_at
                and not self.bubble.visible()):
            try:
                self.show_music_bubble()
            except Exception as exc:        # noqa: BLE001
                self._music_log("music bubble failed %r" % (exc,))

        # 桌宠永远待在窗口最底下：定时重新压一次层级（别的窗口新开/切换到前面
        # 时，光靠启动那一次 SetWindowPos 不一定一直保持在最底）。
        if now >= self._next_lower:
            self._next_lower = now + 1.5
            self.lower_to_desktop()
        self.phase += 0.075 * frame_k
        # 按住不动 1 秒 = 摸头（给"懒得划来划去"的人一个入口）
        if (getattr(self, "press_pos", None) is not None and not self.moved
                and not self._hold_petted and now - self._press_at >= 1.0):
            self._hold_petted = True
            px, py = self.press_pos[0], self.press_pos[1]
            if self._in_head_zone(px, py):
                self.petting_until = now + 2.2
                self._pet_energy = max(self._pet_energy, 26.0)
                self._gesture_hits["hold"] = \
                    self._gesture_hits.get("hold", 0) + 1
                try:
                    self.hearts.burst(self.head_anchor(), count=6)
                except Exception:               # noqa: BLE001
                    pass
        self._update_petting(now, dt)        # 摸头的平滑强度/位移
        self._update_shooting(now, dt)       # 打飞机的拉长变扁
        self._update_extra(now, dt)          # 躲闪位移 / 转圈角度

        if now >= self.next_shift:
            self.target = [random.uniform(-3.5, 3.5), random.uniform(-1.5, 1.5)]
            self.next_shift = now + random.uniform(2.0, 4.5)
        for i in range(2):
            self.offset[i] += (self.target[i] - self.offset[i]) * 0.06 * frame_k

        dy = self.offset[1]
        if self.jump > 0.02:
            dy -= (math.sin(self.jump * math.pi) * self.jump_px
                   * getattr(self, "_jump_gain", 1.0))
            self.jump = max(0.0, self.jump - 0.055 * frame_k)

        # 被划一下：从压扁回弹（先快后慢，带一点弹回来过头的感觉）
        if self.squash > 0.0:
            self.squash = max(0.0, self.squash - self.SQUASH_DECAY * frame_k)

        if not self.visible:
            # 被别的窗口盖住：**动作状态照常推进**（jump/squash 衰减、躲闪、
            # 转圈、摸头都在上面算过了），只是不画、不跟气泡、不冒特效。
            # 以前这里直接 return，结果右键「逗它玩」点的动作在同一帧就被
            # 搁置，用户看到的是"点了没反应"。
            if self.hearts.active():
                self.hearts.clear()
            if self.danmaku.active():
                self.danmaku.clear()
            if getattr(self, "shoot_fx", None) is not None:
                self.shoot_fx.clear()
            self._restore_shoot_home()
            return

        if (abs(self.squash) > 0.001 or self._pet_energy > 0.01
                or self._shoot_energy > 0.01
                or abs(self._spin_angle) > 0.12
                or abs(getattr(self, "_shake_angle", 0.0)) > 0.5):
            self._render_squash_frame()
        else:
            image, (fx, fy) = self._frame_for_phase()
            # 气泡挂点要跟着呼吸/跳跃/摸头一起动
            self._last_dy = dy + fy + self._pet_dy
            self.backend.set_frame(image, self.offset[0] + fx + self._pet_dx,
                                   dy + fy + self._pet_dy)

        if self.bubble and self.bubble.visible():
            # 气泡跟丢一帧不算事，但异常不能从 _tick_body 里漏出去把这一帧
            # 的剩余动画（爱心/弹幕/打飞机）全跳过
            try:
                self.bubble.follow(self.head_anchor())
            except Exception:               # noqa: BLE001
                _log_exception()

        # 继续蹭就持续冒爱心/星星；状态结束后让剩下几颗自然飘完
        if self._pet_burst_pending or self._pet_sparkle_pending:
            hearts_n = min(12, self._pet_burst_pending)
            sparkles_n = min(12, self._pet_sparkle_pending)
            self._pet_burst_pending = 0
            self._pet_sparkle_pending = 0
            if hearts_n:
                self.hearts.burst(self.head_anchor(), count=hearts_n)
            if sparkles_n:
                self.hearts.burst(self.head_anchor(), count=sparkles_n,
                                  kind="sparkle")
            # 爱心窗口是置顶的；正说着话时把气泡再抬到爱心上面，别挡字
            if self.bubble and self.bubble.visible():
                try:
                    self.bubble.win.lift()
                except tk.TclError:
                    pass
        if self._pet_pat_points:
            points = self._pet_pat_points[:6]
            self._pet_pat_points = self._pet_pat_points[6:]
            try:
                face = self.face_anchor()
                head_y = face[0][1] - face[2] * 0.58
            except Exception:                   # noqa: BLE001
                head_y = self.head_anchor()[1]
            for px in points:
                self.hearts.pat(px, head_y)
        self.hearts.update(dt, self.head_anchor(), now < self.petting_until)
        self.danmaku.update(
            dt, self.head_anchor(),
            now < self.petting_until and self.danmaku_allowed(), now)
        self.shoot_fx.update(dt, now, self)

        # 待机闲话：气泡只在有人点它的时候才弹，所以这里只生成、不显示。
        # 结果是给下一次点击用的，既不浪费 token 也不会自己冒出来占屏幕。
        if now >= self.next_talk:
            self.next_talk = now + random.uniform(180, 420)
            if self.ai_enabled and self.brain.enabled:
                self._prefetch_chatter()

    def _render_squash_frame(self):
        """画"被压扁"的那一帧：底边钉在原地，只从上面压下来。

        set_frame 的 dy 是相对窗口底边的偏移，压扁后图变矮、底边不动，
        所以这里不需要额外补偿。摸头时的轻微下压/跟手摆动也走这条路径
        （squash 为 0、只有 pet_energy 时同样需要重画缩放图）。
        """
        angle = max(-14.0, min(14.0, self._pet_angle)) \
            + getattr(self, "_shake_angle", 0.0)
        img = self.sprite.rotated(self.scale, self._squash_factor(),
                                  angle, self._wide_factor())
        dx = self.offset[0] + self._pet_dx
        dy = self.offset[1] + self._pet_dy
        self._last_dy = dy
        self.backend.set_frame(img, dx, dy)

    # ------------------------------------------------------------ 生命周期
    def quit(self):
        if not self._alive:
            return
        self._alive = False
        # 打飞机时如果宠物正滑到飞机下面，退出前先回到原位再存档
        self._restore_shoot_home()
        try:
            self.music.close()
        except Exception:               # noqa: BLE001
            pass
        self._save_config()
        if self._mouse_hook is not None:
            self._mouse_hook.remove()
            self._mouse_hook = None
        watchdog = getattr(self, "_watchdog", None)
        if watchdog is not None:
            watchdog.stop()
            self._watchdog = None
        win = getattr(self, "settings_win", None)
        if win is not None:
            try:
                win.close()
            except Exception:                   # noqa: BLE001
                pass
            self.settings_win = None
        for job in ("_tick_job", "_greet_job"):
            handle = getattr(self, job, None)
            if handle:
                try:
                    self.root.after_cancel(handle)
                except Exception:
                    pass
                setattr(self, job, None)
        if self.bubble:
            self.bubble.destroy()
        if getattr(self, "hearts", None) is not None:
            self.hearts.destroy()
            self.hearts = None
        if getattr(self, "danmaku", None) is not None:
            self.danmaku.destroy()
            self.danmaku = None
        if getattr(self, "shoot_fx", None) is not None:
            self.shoot_fx.destroy()
            self.shoot_fx = None
        tray = getattr(self, "tray", None)
        if tray is not None:                    # 把托盘图标撤掉，别留个幽灵
            tray.stop()
            self.tray = None
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def run(self):
        self.root.mainloop()


def _assets_available():
    if os.path.isdir(ASSETS):
        return True
    base = getattr(sys, "_MEIPASS", None)
    return bool(base and os.path.isdir(os.path.join(base, "assets")))


def _print_where():
    """--where：打印路径信息，用来排查打包后找不到素材/存不了配置的问题。"""
    print("frozen        :", FROZEN)
    print("executable    :", sys.executable)
    print("_MEIPASS      :", getattr(sys, "_MEIPASS", None))
    print("ROOT          :", ROOT)
    print("assets dir    :", ASSETS, "(exists: %s)" % os.path.isdir(ASSETS))
    print("config path   :", CONFIG_PATH, "(exists: %s)" % os.path.exists(CONFIG_PATH))
    print("image dir     :", IMAGE_DIR, "(exists: %s)" % os.path.isdir(IMAGE_DIR))
    for name, _b, _k, _l in BUILTIN_IMAGES:
        print("  builtin %-14s %s" % (name, os.path.exists(_asset_path(BUILTIN_RGBA[name]))))
    images = scan_images()
    print("images found  : %d" % len(images))
    for img in images:
        print("  %-24s key=%-8s alpha=%-5s %s"
              % (img.name, img.key, img.alpha, img.path))


def _gesture_probe(pet, path=None):
    """用真光标在宠物身上划一遍，把命中的手势写进日志（打包验收用）。

    走的是正常运行时的完整链路：SetCursorPos 改真实光标 -> _tick 里
    GetCursorPos 采样 -> 判定 -> 动作。大约两秒里光标会被借走，结束后
    自动退出，结果落在 pet_gesture_check.log（exe 没有控制台，只能写文件）。
    """
    path = path or os.path.join(ROOT, "pet_gesture_check.log")
    if _user32 is None:
        _probe_write(path, {"error": "user32 unavailable"})
        pet.quit()
        return

    hits = pet._gesture_hits

    def cursor(px, py):
        _user32.SetCursorPos(int(px), int(py))

    def build_seq():
        # 坐标必须在窗口真正摆好之后再算：exe 冷启动比源码慢，600ms 时
        # win_x/win_y 可能还是 0（窗口刚建出来），拿它算出来的点会落到
        # 屏幕左上角，一根手势都划不到宠物身上。
        x = pet.win_x + pet.win_w // 2
        top = pet.win_y + pet.headroom + 12
        bottom = pet.win_y + pet.win_h - 24
        seq = []
        for i in range(11):                 # 快速下滑
            seq.append((x, top + (bottom - top) * i / 10.0, 12))
        seq.append((None, None, 320))
        for i in range(11):                 # 快速上划
            seq.append((x, bottom + (top - bottom) * i / 10.0, 12))
        seq.append((None, None, 900))
        return seq

    def step(seq, i=0):
        if i >= len(seq):
            _probe_write(path, hits)
            pet.root.after(120, pet.quit)
            return
        px, py, delay = seq[i]
        if px is not None:
            cursor(px, py)
        pet.root.after(delay, lambda: step(seq, i + 1))

    def begin(tries=0):
        # 等窗口有真正的位置再开始（最多等 5 秒）
        if pet.win_w > 0 and pet.win_x > 0:
            step(build_seq())
        elif tries < 50:
            pet.root.after(100, lambda: begin(tries + 1))
        else:
            _probe_write(path, {"error": "window never got a position"})
            pet.root.after(120, pet.quit)

    pet.root.after(900, begin)


def _probe_write(path, data):
    try:
        with open(path, "w", encoding="utf-8") as fh:
            for key in ("squash", "jump", "dodge", "spin", "shake", "error"):
                if key in data:
                    fh.write("%s=%s\n" % (key, data[key]))
    except Exception:                       # noqa: BLE001 - 写不了就算了
        _log_exception()


def main(argv=None):
    # 先把崩溃信息接住：pythonw 没有控制台，abort/Tcl_Panic 那行字默认谁
    # 都看不到（事件日志里只有 ucrtbase 的 0xc0000409）
    install_crash_diagnostics()
    gc.disable()                # 回收统一放到主线程的 tick 里（见 _tick_body）
    ap = argparse.ArgumentParser(description="桌面宠物")
    ap.add_argument("--image", default=None,
                    help="用 image/ 里的哪张图（文件名，默认 中性灰.png）")
    ap.add_argument("--image-dir", default=None,
                    help="立绘目录，默认程序旁边的 image/")
    ap.add_argument("--style", choices=("auto", "layered", "colorkey"), default="auto",
                    help="渲染后端，默认 auto（带透明通道的图自动用 layered）")
    ap.add_argument("--scale", type=float, default=None,
                    help="大小比例，默认 0.5（可选 %s）"
                         % ", ".join(str(s) for s in DesktopPet.SCALES))
    ap.add_argument("--topmost", action="store_true",
                    help="（已停用）桌宠固定压在窗口最下面，这个开关不再有效")
    ap.add_argument("--no-bubble", action="store_true", help="不显示气泡")
    ap.add_argument("--no-ai", action="store_true",
                    help="关掉 AI，只用内置话术（不联网）")
    ap.add_argument("--api-key", default=None,
                    help="DeepSeek API Key（默认用配置里的或内置的）")
    ap.add_argument("--model", default=None,
                    help="模型名，默认 deepseek-chat（也可用 deepseek-reasoner）")
    ap.add_argument("--ask", default=None,
                    help="启动时先问 AI 一句，回复显示在气泡里（自检用）")
    ap.add_argument("--list-images", action="store_true",
                    help="列出 image/ 里扫到的立绘后退出")
    ap.add_argument("--selftest", type=int, default=0,
                    help="N 毫秒后自动退出（用于测试）")
    ap.add_argument("--settings", action="store_true",
                    help="启动后直接打开设置窗口（截图/自检用）")
    ap.add_argument("--gesture-selftest", action="store_true",
                    help="用真光标划一遍宠物，把命中结果写进 pet_gesture_check.log（打包验收用）")
    ap.add_argument("--where", action="store_true",
                    help="打印素材/配置路径后退出（排查打包问题）")
    ap.add_argument("--tray-check", action="store_true",
                    help="启动后把托盘注册结果写进 pet_tray_check.log 再退出（排查托盘问题）")
    args = ap.parse_args(argv)
    if args.topmost:
        print("提示：桌宠现在固定待在桌面层（窗口最下面），--topmost 已停用。")

    if args.where:
        _print_where()
        return 0
    if args.list_images:
        for img in scan_images(args.image_dir):
            print("%s\t%s" % (img.name, "透明" if img.alpha else ("抠底 %s" % img.key)))
        return 0
    if not _assets_available():
        sys.exit("找不到素材目录: %s\n请先运行 tools/build_assets.py" % ASSETS)
    new_image_folder()          # 第一次跑就把内置立绘放进 image/，用户能直接替换
    pet = DesktopPet(image=args.image, bubble=False if args.no_bubble else None,
                     style=args.style, scale=args.scale, api_key=args.api_key,
                     model=args.model, use_ai=False if args.no_ai else None,
                     image_dir=args.image_dir)
    # 启动时的模块/立绘/字体/控件对象全都活到进程结束，把它们移出 GC 的扫描
    # 范围：以后每次全量回收只扫短命对象（气泡、动画帧），又快又不容易在
    # 动画途中因为回收抖动而卡一下。必须在窗口建好之后调用。
    try:
        gc.freeze()
    except AttributeError:                  # Python < 3.7 没有 freeze
        pass
    if args.tray_check:
        def _tray_report():
            ok = bool(getattr(getattr(pet, "tray", None), "ok", False))
            hint = False        # 不再建任务栏占位窗口
            probe = "-"
            try:
                # 对照实验：拿宠物自己的 Tk 窗口句柄再注册一次
                hwnd = _hwnd_of(pet.root)
                if hwnd and _tray_shell32 is not None:
                    nid = NOTIFYICONDATAW()
                    nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
                    nid.hWnd = hwnd
                    nid.uID = 9
                    nid.uFlags = NIF_MESSAGE | NIF_TIP
                    nid.uCallbackMessage = WM_TRAY
                    nid.szTip = APP_NAME
                    got = _tray_shell32.Shell_NotifyIconW(
                        NIM_ADD, ctypes.byref(nid))
                    err = ctypes.windll.kernel32.GetLastError()
                    probe = "ok=%s err=%s" % (bool(got), err)
                    if got:
                        nid.uFlags = 0
                        _tray_shell32.Shell_NotifyIconW(
                            NIM_DELETE, ctypes.byref(nid))
            except Exception:
                _log_exception()
                probe = "exception"
            path = os.path.join(ROOT, "pet_tray_check.log")
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("tray_ok=%s\ntaskbar_hint=%s\ntray_err=%s\n"
                             "tk_hwnd_probe=%s\n"
                             % (ok, hint,
                                getattr(getattr(pet, "tray", None),
                                        "err", "-"), probe))
            except Exception:
                _log_exception()
            pet.quit()
        pet.root.after(3500, _tray_report)
    if args.settings:
        pet.root.after(500, pet.open_settings)
    if args.gesture_selftest:
        _gesture_probe(pet)
    if args.ask:
        pet.root.after(400, lambda: pet.ask_ai(args.ask))
    if args.selftest:
        pet.root.after(args.selftest, pet.quit)
    pet.run()


if __name__ == "__main__":
    main()

