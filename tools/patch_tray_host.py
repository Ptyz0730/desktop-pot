# -*- coding: utf-8 -*-
"""托盘宿主窗口改用"隐藏的普通窗口"。

Win11 上 Shell_NotifyIcon(NIM_ADD) 对 HWND_MESSAGE（message-only）窗口
会直接返回 FALSE，而 GetLastError 还是 0 —— 日志里看不出原因。源码版偶尔
能成，打包版稳定失败。改成一个永远不显示的 WS_POPUP 工具窗口，仍然收
得到托盘回调消息；万一还是不行，再退回 message-only 窗口重试一次。
"""
import io

P = 'desktop_pet.py'
s = io.open(P, encoding='utf-8').read()

old = '''            # 消息窗口：HWND_MESSAGE 的窗口不可见、也不会出现在任务栏
            self._hwnd = user32.CreateWindowExW(0, self.class_name, self.class_name,
                                                0, 0, 0, 0, 0, wintypes.HWND(HWND_MESSAGE),
                                                0, wc.hInstance, None)
            if not self._hwnd:
                self._ready.set()
                return'''

new = '''            # 托盘宿主窗口：先用"隐藏的普通 popup 窗口"（WS_POPUP +
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
                return'''

assert old in s
s = s.replace(old, new, 1)

if 'WS_POPUP =' not in s:
    s = s.replace('HWND_MESSAGE = -3',
                  'WS_POPUP = 0x80000000\nHWND_MESSAGE = -3', 1)

io.open(P, 'w', encoding='utf-8', newline='').write(s)
print('tray host window patched')
