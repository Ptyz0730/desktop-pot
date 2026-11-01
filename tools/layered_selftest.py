# -*- coding: utf-8 -*-
"""Does UpdateLayeredWindow paint at all in this session?

Paints a solid magenta square three ways and reads each result back with
GetDIBits, so we can tell a broken pipeline from an invisible one.
"""
import ctypes
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ctypes import wintypes  # noqa: E402
from PIL import Image  # noqa: E402
import desktop_pet as dp  # noqa: E402

W = H = 64
MAGENTA = (255, 0, 255)


def dibits_from(data, w, h):
    """Create a DIB section holding `data` (BGRA) and return (memdc, bmp, buf)."""
    u, g = dp._user32, dp._gdi32
    info = dp.BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(dp.BITMAPINFOHEADER)
    info.bmiHeader.biWidth = w
    info.bmiHeader.biHeight = -h
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = 0
    buf = ctypes.create_string_buffer(data, len(data))
    bits = ctypes.c_void_p()
    sdc = u.GetDC(0)
    bmp = g.CreateDIBSection(sdc, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
    ctypes.memmove(bits, buf, len(data))
    mdc = g.CreateCompatibleDC(sdc)
    old = g.SelectObject(mdc, bmp)
    return sdc, mdc, bmp, old, bits


def read_back(mdc, w, h):
    u, g = dp._user32, dp._gdi32
    info = dp.BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(dp.BITMAPINFOHEADER)
    info.bmiHeader.biWidth = w
    info.bmiHeader.biHeight = -h
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    g.GetDIBits(mdc, ctypes.c_void_p(0), 0, h, buf, ctypes.byref(info), 0)
    return buf


def main():
    import tkinter as tk
    u, g = dp._user32, dp._gdi32
    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry("1x1+0+0")
    tk.Canvas(root, width=1, height=1, highlightthickness=0).pack()
    root.update()
    hwnd = u.GetParent(root.winfo_id()) or root.winfo_id()
    u.SetWindowLongW(hwnd, -20, u.GetWindowLongW(hwnd, -20) | 0x80000)
    print("hwnd", hwnd, "exstyle 0x%X" % u.GetWindowLongW(hwnd, -20))

    cases = {
        "opaque magenta (alpha=255)": bytes([255, 0, 255, 255]) * (W * H),
        "premultiplied magenta": bytes([255, 0, 255, 255]) * (W * H),  # same when a=255
        "alpha=0 (should be invisible)": bytes([255, 0, 255, 0]) * (W * H),
    }
    sdc0 = u.GetDC(0)
    for name, data in cases.items():
        sdc, mdc, bmp, old, bits = dibits_from(data, W, H)
        blend = dp.BLENDFUNCTION(0, 0, 255, 1)
        dst = wintypes.POINT(300, 300)
        src = wintypes.POINT(0, 0)
        size = wintypes.SIZE(W, H)
        ok = u.UpdateLayeredWindow(hwnd, sdc0, ctypes.byref(dst), ctypes.byref(size),
                                   mdc, ctypes.byref(src), 0, ctypes.byref(blend), 2)
        root.update()
        time.sleep(0.15)
        # verify the DIB really holds what we wrote (read the raw bits back, not GetDIBits)
        pixel = bytes((ctypes.cast(bits, ctypes.POINTER(ctypes.c_ubyte))[4 * (5 * W + 5) + i]
                       for i in range(4)))
        print("%-30s ULW=%s  source_bit(5,5) BGRA=%s" % (name, ok, tuple(pixel)))
        g.SelectObject(mdc, old)
        g.DeleteObject(bmp)
        g.DeleteDC(mdc)
        u.ReleaseDC(0, sdc)
    u.ReleaseDC(0, sdc0)
    print("lasterr", ctypes.GetLastError())
    root.destroy()


if __name__ == "__main__":
    main()
