# -*- coding: utf-8 -*-
"""使用说明：托盘只有校徽图标、任务栏不再有按钮。按行号定位，避免全角空格差异。"""
import io

P = '使用说明.txt'
lines = io.open(P, encoding='utf-8').read().splitlines(True)

start = next(i for i, l in enumerate(lines) if l.startswith('  托盘/任务栏'))
end = next(i for i, l in enumerate(lines) if l.startswith('  被划一下'))

new = '''  托盘        启动后只在**系统托盘**（右下角小箭头「^」里面那排）放一个图标，
              图标就是**莆田一中校徽**：右键 -> 跟它说话 / 对话… / 设置… /
              刷新一下 / 取消鼠标穿透 / 退出；左键点它，宠物跳一下。
              它**不会**出现在任务栏里（任务栏上不再有按钮），Alt+Tab 也看不到。
              如果系统不让加托盘图标（有些管控软件会拦，pet_stderr.log 里会写
              "tray: NIM_ADD failed"），程序每 3 秒自动重试、最多 1 分钟；
              仍然失败也不往任务栏塞按钮 —— 把 exe 放到 C:\\桌面宠物 再启动就行
              （桌面目录会被拦，见上面的 ⚠）。
'''
lines[start:end] = [new]
s = ''.join(lines)

s = s.replace('3. 关掉它：直接右键任务栏里那个图标 ->「关闭窗口」，或右键宠物 -> 退出。',
              '3. 关掉它：右键宠物 ->「退出」，或右键右下角「^」里的校徽图标 ->「退出」。', 1)
s = s.replace('放到桌面上的话宠物能跑，但托盘图标会加不上（程序会\n  自动退回"任务栏按钮"方案）。',
              '放到桌面上的话宠物能跑，但托盘图标会加不上（不会再\n  退回任务栏按钮，后台会一直重试）。', 1)

io.open(P, 'w', encoding='utf-8', newline='').write(s)
print('manual updated')
