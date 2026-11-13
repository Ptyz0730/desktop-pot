# -*- coding: utf-8 -*-
"""给人设编辑器截一张图（不启动整只宠物：桌面层窗口截不到，会被别的窗口盖住）。"""
import os
import sys
import time
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import ai_client                    # noqa: E402
import pet_persona                  # noqa: E402


class FakeBrain:
    enabled = True

    def __init__(self):
        self.api_key = "test"
        self.model = "demo"


class FakePet:
    """只提供人设编辑器用到的那几个接口。"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("stand-in")
        self.root.geometry("240x240+40+40")
        self.root.configure(bg="#fffdfd")
        self.custom_personas = {}
        self.brain = FakeBrain()
        self._modal_depth = 0
        self.persona_editor = None

    def save_custom_persona(self, key, data):
        tones = pet_persona.normalize_tones(data.get("tones"))
        self.custom_personas[key] = {
            "name": data.get("name") or key,
            "hint": data.get("hint") or "",
            "prompt": data.get("prompt") or "",
            "tones": [[t, s] for t, s in tones],
            "romance_line": data.get("romance_line") or "",
        }
        ai_client.register_persona(
            key, name=self.custom_personas[key]["name"],
            prompt=self.custom_personas[key]["prompt"],
            hint=self.custom_personas[key]["hint"], tones=tones,
            romance_line=self.custom_personas[key]["romance_line"],
            romance=True)
        return True

    def delete_custom_persona(self, key):
        return bool(self.custom_personas.pop(key, None))


def settle(pet, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pet.root.update()
        time.sleep(0.015)


def _blt_client(hwnd, w, h):
    """抓窗口的客户区（去掉标题栏），且不混进别的进程的窗口。"""
    import ctypes
    from ctypes import wintypes
    from PIL import Image

    u = ctypes.windll.user32
    g = ctypes.windll.gdi32
    for fn, rt, arg in (
            (u.GetWindowDC, wintypes.HDC, [wintypes.HWND]),
            (g.CreateCompatibleDC, wintypes.HDC, [wintypes.HDC]),
            (g.CreateCompatibleBitmap, wintypes.HBITMAP,
             [wintypes.HDC, ctypes.c_int, ctypes.c_int])):
        fn.restype = rt
        fn.argtypes = arg
    g.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    g.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int,
                         wintypes.DWORD]
    g.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, ctypes.c_uint,
                            ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p,
                            ctypes.c_uint]
    g.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    g.DeleteDC.argtypes = [wintypes.HDC]
    u.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]

    wr, cr = wintypes.RECT(), wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(wr))
    u.GetClientRect(hwnd, ctypes.byref(cr))
    pt = wintypes.POINT(0, 0)
    u.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    u.ClientToScreen(hwnd, ctypes.byref(pt))
    frame_x = pt.x - wr.left
    frame_y = pt.y - wr.top

    ww = wr.right - wr.left
    wh = wr.bottom - wr.top
    hdc = u.GetWindowDC(hwnd)
    mdc = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, ww, wh)
    g.SelectObject(mdc, bmp)
    g.BitBlt(mdc, 0, 0, ww, wh, hdc, 0, 0, 0x00CC0020)

    class BMI(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint), ("biWidth", ctypes.c_long),
                    ("biHeight", ctypes.c_long), ("biPlanes", ctypes.c_ushort),
                    ("biBitCount", ctypes.c_ushort), ("biCompression", ctypes.c_uint),
                    ("biSizeImage", ctypes.c_uint), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", ctypes.c_uint),
                    ("biClrImportant", ctypes.c_uint)]
    bi = BMI(ctypes.sizeof(BMI), ww, -wh, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(ww * wh * 4)
    g.GetDIBits(mdc, bmp, 0, wh, buf, ctypes.byref(bi), 0)
    img = Image.frombuffer("RGB", (ww, wh), buf, "raw", "BGRX", 0, 1).copy()
    g.DeleteObject(bmp)
    g.DeleteDC(mdc)
    u.ReleaseDC(hwnd, hdc)

    factor = ww / float(w)                    # 物理像素 / 逻辑像素
    left = int(round(frame_x * factor))
    top = int(round(frame_y * factor))
    cw, ch = cr.right - cr.left, cr.bottom - cr.top
    right = min(ww, left + int(round(cw * factor))) - 8
    bottom = min(wh, top + int(round(ch * factor))) - 8
    return img.crop((left, top, right, bottom))


def grab(pet, win, name, w, h):
    import ctypes
    from PIL import Image

    win.geometry("+140+80")
    settle(pet, 0.5)
    hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
    img = _blt_client(hwnd, w, h)
    if img.width < w * 1.5:
        img = img.resize((w * 2, h * 2), Image.NEAREST)
    path = os.path.join(ROOT, name)
    img.save(path)
    print("saved", path, img.size)
    return path


pet = FakePet()
try:
    pet.save_custom_persona("小满", {
        "name": "小满",
        "hint": "坐你旁边那个总在写题的女生",
        "prompt": ("小满，16 岁，高二，坐在你隔壁桌。说话轻轻的，句子短，"
                   "偶尔冒一句文言腔又赶紧改口。\n"
                   "被夸会低头转笔，嘴上说「哪有」；被靠近会红耳朵，"
                   "然后假装看书。\n"
                   "吃醋时不吵，只说「那你去找她吧」，然后一整天不主动说话。\n"
                   "冷战只回「嗯」「好」，但会把你落在桌上的笔收进自己笔袋。\n"
                   "旁白只写看得见的动作，不写心理。"),
        "tones": ["陌生期：叫「同学」，客气，说话会顿一下。",
                  "熟悉期：叫名字，开始借你的笔记，偶尔怼你一句。",
                  "朋友期：主动问你写没写作业，嘴硬但会帮你带水。",
                  "暧昧期：被夸会红耳朵，吃醋只说「那你去找她吧」。",
                  "恋人期：叫「我的同桌」，撒娇但嘴硬，会靠在你肩上装作睡着。"],
        "romance_line": "那你……以后都坐我旁边吧。",
    })
    editor = pet_persona.PetPersonaDialog(pet).show()
    settle(pet, 0.5)
    editor._reload_list(select="小满")
    settle(pet, 0.3)
    grab(pet, editor.win, "persona_editor.png", editor.W, editor.H)
    editor.close()
    settle(pet, 0.2)
finally:
    try:
        pet.root.destroy()
    except Exception:                       # noqa: BLE001
        pass
