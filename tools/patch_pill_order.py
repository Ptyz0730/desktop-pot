# -*- coding: utf-8 -*-
"""修正外观页胶囊的 (文字, 值) 顺序（PillGroup 是 text,val）。"""
import io

P = 'desktop_pet.py'
s = io.open(P, encoding='utf-8').read()

pairs = [
    ('''                     [(2000, "2 秒"), (4000, "4 秒"), (6000, "6 秒"),
                      (8000, "8 秒")],''',
     '''                     [("2 秒", 2000), ("4 秒", 4000), ("6 秒", 6000),
                      ("8 秒", 8000)],'''),
    ('''                     [("calm", "安静"), ("normal", "正常"), ("lively", "活泼")],''',
     '''                     [("安静", "calm"), ("正常", "normal"),
                      ("活泼", "lively")],'''),
    ('''                     [("low", "迟钝"), ("normal", "正常"), ("high", "灵敏")],''',
     '''                     [("迟钝", "low"), ("正常", "normal"),
                      ("灵敏", "high")],'''),
]
for old, new in pairs:
    assert old in s, old[:50]
    s = s.replace(old, new, 1)

io.open(P, 'w', encoding='utf-8', newline='').write(s)
print('pill order fixed')
