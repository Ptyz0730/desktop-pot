# -*- coding: utf-8 -*-
"""补一条"从桌面目录运行会导致托盘被拦"的说明。"""
import io

P = '使用说明.txt'
s = io.open(P, encoding='utf-8').read()

old = '''  exe 挪到 C:\\ 下就正常）。放在桌面上的话宠物能跑，但托盘图标会加不上（程序会
  自动退回"任务栏按钮"方案）。
'''

new = '''  exe 挪到 C:\\ 下就正常）。放在桌面上的话宠物能跑，但托盘图标会加不上（程序会
  自动退回"任务栏按钮"方案）。

  2026-10 实测：连 `C:\\Users\\...\\Desktop\\desktop-pet\\dist\\桌面宠物\\桌面宠物.exe`
  这种"桌面下面的构建目录"也会被拦（托盘 tray_ok=False）；同一份 exe 放到
  `C:\\桌面宠物` 就 tray_ok=True、图标出现在右下角「^」里。所以**日常请从
  C:\\桌面宠物 启动**，dist 那个目录只当构建产物看。
'''

assert old in s
s = s.replace(old, new, 1)
io.open(P, 'w', encoding='utf-8', newline='').write(s)
print('manual tray note added')
