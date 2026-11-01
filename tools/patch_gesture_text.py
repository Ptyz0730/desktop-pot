# -*- coding: utf-8 -*-
"""修正手势页说明文案（摇一摇不再是默认刷新）。"""
import io

P = 'desktop_pet.py'
s = io.open(P, encoding='utf-8').read()
old = '鼠标从身上划过时会压扁、跳一下、躲开、转圈和摸头；"\n                      "在它身上左右摇一摇等于点一次「刷新一下」。'
new = '鼠标从身上划过时会压扁、跳一下、躲开、转圈和摸头。'
assert old in s
s = s.replace(old, new, 1)
io.open(P, 'w', encoding='utf-8', newline='').write(s)
print('desc fixed')
