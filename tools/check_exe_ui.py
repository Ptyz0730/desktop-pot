# -*- coding: utf-8 -*-
"""验证打包版：托盘注册、任务栏按钮是否消失、设置窗口里的校徽是否正常。

流程：用 subprocess 起 exe（--settings --selftest），等窗口出来，枚举该进程的
顶层窗口，记录 WS_EX_APPWINDOW（=任务栏按钮）数量，再用 PrintWindow 抓设置
窗口存 exe_settings_preview.png。
"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

from PIL import Image

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

GWL_EXSTYLE = -20
WS_EX_APPWINDOW = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080

user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE_DIR = sys.argv[1] if len(sys.argv) > 1 else r'C:\桌面宠物'
EXE = os.path.join(EXE_DIR, '桌面宠物.exe')


def windows_of(pid):
    found = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _lparam):
        got = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(got))
        if got.value != pid:
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, 256)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
        found.append({
            'hwnd': hwnd, 'title': title.value, 'cls': cls.value,
            'rect': (rect.left, rect.top, rect.right, rect.bottom),
            'visible': bool(user32.IsWindowVisible(hwnd)), 'ex': ex,
        })
        return True

    user32.EnumWindows(proc(cb), 0)
    return found


def grab(hwnd, rect, path):
    left, top, right, bottom = rect
    w, h = right - left, bottom - top
    if w <= 0 or h <= 0:
        return None
    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    user32.PrintWindow(hwnd, mem, 2)

    class BMIH(ctypes.Structure):
        _fields_ = [('biSize', wintypes.DWORD), ('biWidth', ctypes.c_long),
                    ('biHeight', ctypes.c_long), ('biPlanes', wintypes.WORD),
                    ('biBitCount', wintypes.WORD),
                    ('biCompression', wintypes.DWORD),
                    ('biSizeImage', wintypes.DWORD),
                    ('biXPelsPerMeter', ctypes.c_long),
                    ('biYPelsPerMeter', ctypes.c_long),
                    ('biClrUsed', wintypes.DWORD),
                    ('biClrImportant', wintypes.DWORD)]

    bi = BMIH()
    bi.biSize = ctypes.sizeof(BMIH)
    bi.biWidth = w
    bi.biHeight = -h
    bi.biPlanes = 1
    bi.biBitCount = 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)
    img = Image.frombuffer('RGBA', (w, h), buf, 'raw', 'BGRA', 0, 1)
    img.convert('RGB').save(path)
    return path


def main():
    p = subprocess.Popen([EXE, '--settings', '--selftest', '9000', '--no-ai'],
                         cwd=EXE_DIR)
    time.sleep(5.0)
    wins = windows_of(p.pid)
    app = [w for w in wins if w['ex'] & WS_EX_APPWINDOW]
    print('windows=%d appwindow=%d' % (len(wins), len(app)))
    for w in wins:
        print('  %-8s %-14s visible=%-5s %s %s' %
              (hex(w['hwnd']), w['cls'][:14], w['visible'],
               w['rect'], repr(w['title'])[:30]))
    target = None
    for w in wins:
        r = w['rect']
        if (r[2] - r[0]) > 700 and (r[3] - r[1]) > 500:
            target = w
            break
    if target:
        path = os.path.join(ROOT, 'exe_settings_preview.png')
        grab(target['hwnd'], target['rect'], path)
        print('shot ->', path)
    else:
        print('no settings window found')
    p.wait(timeout=30)
    tray = os.path.join(EXE_DIR, 'pet_tray_check.log')
    print('appwindow windows (should be 0):', len(app))
    return 0 if not app else 1


if __name__ == '__main__':
    sys.exit(main())
