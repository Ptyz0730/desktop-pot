# -*- coding: utf-8 -*-
"""给 --tray-check 加对照探针：用宠物自己的 Tk 窗口句柄注册一次托盘。"""
import io

P = 'desktop_pet.py'
lines = io.open(P, encoding='utf-8').read().splitlines(True)

start = None
for i, line in enumerate(lines):
    if line.strip() == 'def _tray_report():':
        start = i
        break
assert start is not None
end = None
for j in range(start + 1, start + 30):
    if lines[j].strip() == 'pet.quit()':
        end = j
        break
assert end is not None

new = '''        def _tray_report():
            ok = bool(getattr(getattr(pet, "tray", None), "ok", False))
            hint = getattr(pet, "taskbar_win", None) is not None
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
                    fh.write("tray_ok=%s\\ntaskbar_hint=%s\\ntray_err=%s\\n"
                             "tk_hwnd_probe=%s\\n"
                             % (ok, hint,
                                getattr(getattr(pet, "tray", None),
                                        "err", "-"), probe))
            except Exception:
                _log_exception()
            pet.quit()
'''

lines[start:end + 1] = [new]
io.open(P, 'w', encoding='utf-8', newline='').write(''.join(lines))
print('tray probe added')
