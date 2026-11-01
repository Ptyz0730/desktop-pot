# -*- coding: utf-8 -*-
"""初始化 press_pos / moved 与 _gesture_hits 的新键（长按摸头用）。"""
import io

P = 'desktop_pet.py'
s = io.open(P, encoding='utf-8').read()


def rep(old, new):
    global s
    assert old in s, old[:70]
    s = s.replace(old, new, 1)


rep('''        self._press_at = 0.0
        self._hold_petted = False''',
    '''        self._press_at = 0.0
        self._hold_petted = False
        self.press_pos = None            # 按下时的 (x, y, win_x, win_y)
        self.moved = False''')

rep('''        if (self.press_pos is not None and not self.moved''',
    '''        if (getattr(self, "press_pos", None) is not None and not self.moved''')

rep('''self._gesture_hits = {"squash": 0, "jump": 0, "dodge": 0, "spin": 0,
                              "shake": 0}''',
    '''self._gesture_hits = {"squash": 0, "jump": 0, "dodge": 0, "spin": 0,
                              "shake": 0, "bounce": 0, "hold": 0}''')

io.open(P, 'w', encoding='utf-8', newline='').write(s)
print('init patched')
