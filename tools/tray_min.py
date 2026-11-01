# -*- coding: utf-8 -*-
"""最小复现：创建隐藏窗口 + Shell_NotifyIcon(NIM_ADD)，把结果写文件。

用 python.exe 跑一次、用 PyInstaller 打包再跑一次，用来判断
"托盘注册失败"是打包环境的问题还是我们结构体/窗口的问题。
"""
import ctypes
import os
import sys
from ctypes import wintypes

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32

NIM_ADD = 0
NIM_DELETE = 2
NIF_MESSAGE = 0x1
NIF_ICON = 0x2
NIF_TIP = 0x4
WM_TRAY = 0x0400 + 1024
WS_POPUP = 0x80000000
WS_EX_TOOLWINDOW = 0x80


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


def main():
    base = (os.path.dirname(os.path.abspath(sys.executable))
            if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(base, "tray_min.log")
    lines = ["frozen=%s" % getattr(sys, "frozen", False),
             "python=%s" % sys.version.split()[0],
             "size=%d" % ctypes.sizeof(NOTIFYICONDATAW)]
    try:
        hinst = kernel32.GetModuleHandleW(None)
        hwnd = user32.CreateWindowExW(WS_EX_TOOLWINDOW, "STATIC", "trayprobe",
                                      WS_POPUP, 0, 0, 0, 0, None, 0, hinst,
                                      None)
        lines.append("hwnd=%s" % hwnd)
        hicon = user32.LoadIconW(None, ctypes.c_void_p(32512))  # IDI_APPLICATION
        lines.append("hicon=%s" % hicon)
        for flags, name in ((NIF_MESSAGE | NIF_TIP, "tip-only"),
                            (NIF_MESSAGE | NIF_ICON | NIF_TIP, "icon+tip")):
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = hwnd
            nid.uID = 7
            nid.uFlags = flags
            nid.uCallbackMessage = WM_TRAY
            nid.hIcon = hicon
            nid.szTip = "tray probe"
            ok = shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
            err = kernel32.GetLastError()
            lines.append("%s ok=%s err=%s" % (name, bool(ok), err))
            if ok:
                nid.uFlags = 0
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        user32.DestroyWindow(hwnd)
    except Exception as exc:                                # noqa: BLE001
        lines.append("exception: %r" % (exc,))
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
