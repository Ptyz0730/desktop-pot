# -*- coding: utf-8 -*-
"""摇一摇进行中时别再判"横划躲闪"（否则摇一下先躲一下）。"""
import io

P = 'desktop_pet.py'
s = io.open(P, encoding='utf-8').read()


def rep(old, new):
    global s
    assert old in s, old[:60]
    s = s.replace(old, new, 1)


rep('''        self._shake_track = []
        self._last_squash_at = 0.0''',
    '''        self._shake_track = []
        self._shake_rev = 0
        self._last_squash_at = 0.0''')

rep('''        span = now - track[0][0]
        if (reversals < 4 or travel < max(150.0, self.win_w * 0.9)''',
    '''        self._shake_rev = reversals
        span = now - track[0][0]
        if (reversals < 4 or travel < max(150.0, self.win_w * 0.9)''')

rep('''            if self._shake_track and now - self._shake_track[-1][0] > 0.3:
                self._shake_track = []
            return False''',
    '''            if self._shake_track and now - self._shake_track[-1][0] > 0.3:
                self._shake_track = []
                self._shake_rev = 0
            return False''')

rep('''    def _track_body_swipe(self, now, x, y):
        """在身体上快速横划 -> 往反方向躲一下。"""''',
    '''    def _track_body_swipe(self, now, x, y):
        """在身体上快速横划 -> 往反方向躲一下。"""
        if getattr(self, "_shake_rev", 0) >= 2:
            # 正在左右摇（方向已经在反转）：那是"摇一摇"，不是横划躲闪
            return''')

io.open(P, 'w', encoding='utf-8', newline='').write(s)
print('shake/dodge guard patched')
