"""自检：设置窗口能开、开关能同步、刷新能把气泡救回来。

跑法（要能弹窗的桌面会话）：
    python tools/check_settings.py [--shot]
带 --shot 会给每一页留一张 settings_preview_<tab>.png。
"""
import ctypes
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import desktop_pet as dp                                    # noqa: E402
from PIL import Image, ImageGrab                           # noqa: E402

SHOT = "--shot" in sys.argv


def settle(pet, seconds):
    end = time.time() + seconds
    while time.time() < end:
        try:
            pet.root.update()
        except Exception:                                   # noqa: BLE001
            return
        time.sleep(0.015)


def win_rect(win):
    hwnd = dp._hwnd_of(win)
    rect = ctypes.wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def grab_window(win):
    """用 PrintWindow 抓窗口本身：不会被别的窗口、输入法候选框糊住。"""
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    handle = ctypes.c_void_p
    user32.GetWindowDC.restype = handle
    user32.GetWindowDC.argtypes = [handle]
    gdi32.CreateCompatibleDC.restype = handle
    gdi32.CreateCompatibleDC.argtypes = [handle]
    gdi32.CreateCompatibleBitmap.restype = handle
    gdi32.CreateCompatibleBitmap.argtypes = [handle, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.restype = handle
    gdi32.SelectObject.argtypes = [handle, handle]
    gdi32.GetDIBits.argtypes = [handle, handle, ctypes.c_uint, ctypes.c_uint,
                                ctypes.c_void_p,
                                ctypes.POINTER(dp.BITMAPINFOHEADER),
                                ctypes.c_uint]
    gdi32.DeleteObject.argtypes = [handle]
    gdi32.DeleteDC.argtypes = [handle]
    user32.ReleaseDC.argtypes = [handle, handle]
    user32.PrintWindow.argtypes = [handle, handle, ctypes.c_uint]
    user32.PrintWindow.restype = ctypes.c_int
    hwnd = ctypes.c_void_p(dp._hwnd_of(win))
    left, top, right, bottom = win_rect(win)
    w, h = max(1, right - left), max(1, bottom - top)
    src = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(src)
    bmp = gdi32.CreateCompatibleBitmap(src, w, h)
    old = gdi32.SelectObject(mem, bmp)
    try:
        user32.PrintWindow(hwnd, mem, 2)        # PW_RENDERFULLCONTENT
        header = dp.BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(dp.BITMAPINFOHEADER)
        header.biWidth = w
        header.biHeight = -h                    # 负数 = 自上而下
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = 0
        buf = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(header), 0)
    finally:
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(hwnd, src)
    return Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")


def grab(pet, win, path):
    pet.root.withdraw()
    if pet.bubble is not None:
        pet.bubble.hide()
    time.sleep(0.25)
    img = grab_window(win)
    img.save(path)
    print("shot ->", path, img.size)
    pet.root.deiconify()


def main():
    backup = os.path.join(ROOT, "pet_config.check_backup.json")
    cfg = dp.CONFIG_PATH
    if os.path.exists(cfg):
        os.replace(cfg, backup)
    pet = None
    try:
        pet = dp.DesktopPet(use_ai=False, bubble=True)
        settle(pet, 0.5)
        print("pet up, scale=%.2f topmost=%s" % (pet.scale, pet.topmost))
        assert pet.topmost is False, "pet must always stay at the bottom layer"

        pet.open_settings()
        settle(pet, 0.9)
        sw = pet.settings_win
        assert sw is not None and sw.win is not None, "settings window missing"
        print("settings up:", sw.win.winfo_width(), "x", sw.win.winfo_height())
        print("tabs:", [k for k, _l, _i in sw.TABS])

        # 每一页都画一遍，确认没有 TclError / 布局崩掉
        for key, _label, _icon in sw.TABS:
            sw.set_tab(key)
            settle(pet, 0.25)
            kids = len(sw._body.winfo_children())
            print("page %-8s children=%d switches=%d pills=%d"
                  % (key, kids, len(sw._switches), len(sw._pills)))
            assert kids > 0, "page %s is empty" % key

        # 功能性操作（形象/大小/不透明度）不该再出现在设置窗口里
        kinds = [k for k, _g, _grp in sw._pills]
        assert not kinds, "settings window should not contain 形象/大小/不透明度: %r" % (kinds,)
        print("no functional rows in settings ok")

        # 开关：改状态 -> 界面同步 -> 再改回来
        pet.set_bubble_enabled(False)
        settle(pet, 0.2)
        assert pet.bubble is None, "bubble should be destroyed when disabled"
        pet.set_bubble_enabled(True)
        settle(pet, 0.3)
        assert pet.bubble is not None, "bubble should come back"
        pet.set_gestures_enabled(False)
        pet.set_gestures_enabled(True)
        pet.set_click_speak(False)
        pet.set_click_speak(True)
        pet.set_kaomoji_enabled(False)
        pet.set_kaomoji_enabled(True)
        pet.set_pause_fullscreen(False)
        pet.set_pause_fullscreen(True)
        pet.set_auto_restart(False)
        pet.set_auto_restart(True)
        print("toggles ok")

        # 真的点界面上的开关，确认命令链一路通到宠物
        sw.set_tab("prefs")
        settle(pet, 0.2)
        bubble_switch = sw._switches[1][1]      # 显示气泡
        bubble_switch._on_click()
        settle(pet, 0.3)
        assert pet.bubble_enabled is False, "clicking 显示气泡 should turn it off"
        bubble_switch._on_click()
        settle(pet, 0.3)
        assert pet.bubble_enabled is True, "clicking again should turn it back on"
        full_switch = sw._switches[2][1]        # 全屏时停用
        full_switch._on_click()
        settle(pet, 0.3)
        assert pet.pause_fullscreen is False, "全屏时停用 应该被点掉"
        full_switch._on_click()
        settle(pet, 0.3)
        assert pet.pause_fullscreen is True
        print("ui click ok")

        # 全屏暂停：造一个真正的无边框全屏窗口，主循环应该自己发现并躲起来
        full = dp.tk.Toplevel(pet.root)
        dp.set_overrideredirect(full, True)
        full.geometry("%dx%d+0+0" % (pet.root.winfo_screenwidth(),
                                     pet.root.winfo_screenheight()))
        full.configure(bg="#101418")
        full.update()
        full.lift()
        full.focus_force()
        settle(pet, 0.9)
        hwnd = dp.foreground_fullscreen()
        print("foreground_fullscreen ->", hex(hwnd) if hwnd else 0)
        assert hwnd, "a borderless fullscreen window should be detected"
        assert pet._fs_paused is True, "pet should pause while fullscreen"
        assert pet.root.state() == "withdrawn", "pet window should hide while paused"
        pet.speak("暂停期间不该出现。")
        settle(pet, 0.2)
        assert not (pet.bubble and pet.bubble.visible()), "no bubble while fullscreen"
        full.destroy()
        settle(pet, 1.2)
        assert pet._fs_paused is False, "pet should resume after fullscreen closes"
        assert pet.root.state() == "normal", "pet window should come back"
        # 恢复后可见性只取决于"有没有被别的窗口盖住"，不硬要求露出来
        assert pet.visible == (not pet.check_covered())
        print("fullscreen pause ok")

        # 刷新：气泡被"卡住"（手动 destroy 半成品）后应该能重建
        pet.bubble.destroy()
        pet.speak("这句话应该显示出来。")
        settle(pet, 0.3)
        pet.request_refresh()
        # 前台窗口会把它判成"被盖住"（气泡随即被藏起来），这里当作人正看着它
        pet._note_interaction()
        settle(pet, 0.6)
        assert pet._alive, "pet died during refresh"
        assert pet.bubble is not None, "bubble missing after refresh"
        # 刷新重建了气泡；再让它说一句，确认新气泡真的能显示
        pet._note_interaction()
        pet.speak("刷新之后再说一句。")
        settle(pet, 0.35)
        assert pet.bubble.visible(), "bubble should be showing after refresh"
        print("refresh ok")

        # 看门狗急救路径（主线程里直接调，只验证不抛异常）。
        # 注意它会给前台/急救窗口发 Esc —— 设置窗口绑了 Esc 关闭，所以先截图。
        sw = pet.settings_win
        if SHOT:
            for key, _label, _icon in sw.TABS:
                sw.set_tab(key)
                settle(pet, 0.45)
                grab(pet, sw.win,
                     os.path.join(ROOT, "settings_preview_%s.png" % key))

        pet._refresh_hwnds()
        print("rescue hwnds:", [hex(h) for h in pet._rescue_hwnds])
        pet._watch_rescue()
        settle(pet, 0.3)
        print("watchdog rescue ok")

        # 关窗口 -> 再开一次，确认单例逻辑
        sw = pet.settings_win
        if sw is not None:
            sw.close()
        settle(pet, 0.2)
        assert pet.settings_win is None, "settings_win should be cleared"
        pet.open_settings()
        settle(pet, 0.5)
        assert pet.settings_win is not None, "settings should reopen"
        print("reopen ok")
        pet.settings_win.close()
        return 0
    finally:
        if pet is not None:
            try:
                pet.quit()
            except Exception:                               # noqa: BLE001
                pass
        if os.path.exists(backup):
            os.replace(backup, cfg)


if __name__ == "__main__":
    sys.exit(main())
