# -*- coding: utf-8 -*-
"""第十一轮：更多手势 + 更多设置项（桌宠侧）。"""
import io

P = 'desktop_pet.py'
s = io.open(P, encoding='utf-8').read()


def rep(old, new, count=1):
    global s
    assert old in s, 'missing anchor: %r' % old[:60]
    s = s.replace(old, new, count)


# ---------------------------------------------------------------- 1) 新配置项
rep('''        self.pause_fullscreen = bool(self.cfg.get("pause_fullscreen", True))
        self._alive = True''',
    '''        self.pause_fullscreen = bool(self.cfg.get("pause_fullscreen", True))
        # 更多设置：气泡停留时长 / 动作幅度 / 手势灵敏度 / 摇一摇刷新 / 开机自启
        try:
            self.bubble_ms = max(1000, min(12000,
                                          int(self.cfg.get("bubble_ms", 4000))))
        except (TypeError, ValueError):
            self.bubble_ms = 4000
        self.anim_level = str(self.cfg.get("anim_level") or "normal")
        self.gesture_sensitivity = str(
            self.cfg.get("gesture_sensitivity") or "normal")
        self.shake_refresh = bool(self.cfg.get("shake_refresh", False))
        self.autostart = bool(self.cfg.get("autostart", False))
        self._shake_angle = 0.0
        self._shake_head_until = 0.0
        self._shake_ready_at = 0.0
        self._shake_track = []
        self._last_squash_at = 0.0
        self._press_at = 0.0
        self._hold_petted = False
        self._apply_gesture_tuning()
        self._alive = True''')

# ---------------------------------------------------------------- 2) 存盘
rep('''                         "pause_fullscreen": bool(self.pause_fullscreen),''',
    '''                         "pause_fullscreen": bool(self.pause_fullscreen),
                         "bubble_ms": int(self.bubble_ms),
                         "anim_level": self.anim_level,
                         "gesture_sensitivity": self.gesture_sensitivity,
                         "shake_refresh": bool(self.shake_refresh),
                         "autostart": bool(self.autostart),''')

# ---------------------------------------------------------------- 3) speak 用 bubble_ms
rep('''        else:
            self.pending = None
            ms = ms or (AI_REPLY_MS if self.ai_enabled else None)''',
    '''        else:
            self.pending = None
            # 没指定就按设置里的「气泡停留时长」
            ms = ms or (AI_REPLY_MS if self.pending == PENDING_TEXT
                        else self.bubble_ms)''')

# ---------------------------------------------------------------- 4) 设置项方法
rep('''    def set_auto_restart(self, on, quiet=False):''',
    '''    def _apply_gesture_tuning(self):
        """按「手势灵敏度」「动作幅度」算出阈值与跳跃幅度。"""
        table = {"low": (125.0, 390.0), "normal": (90.0, 300.0),
                 "high": (65.0, 235.0)}
        min_px, speed = table.get(self.gesture_sensitivity, table["normal"])
        self.swipe_min_px = min_px
        self.swipe_speed = speed
        self._jump_gain = {"calm": 0.72, "normal": 1.0,
                           "lively": 1.32}.get(self.anim_level, 1.0)

    def set_bubble_ms(self, value, quiet=True):
        """气泡停留时长（毫秒）。"""
        try:
            value = max(1000, min(12000, int(value)))
        except (TypeError, ValueError):
            return False
        if value == self.bubble_ms:
            return True
        self.bubble_ms = value
        self._save_config()
        if not quiet:
            self.speak("气泡会停 %d 秒。" % round(value / 1000.0), background=True)
        return True

    def set_anim_level(self, value, quiet=False):
        """动作幅度：calm / normal / lively。"""
        if value not in ("calm", "normal", "lively"):
            return False
        self.anim_level = value
        self._apply_gesture_tuning()
        self._save_config()
        if not quiet:
            self.speak({"calm": "那我安静一点。", "normal": "好，正常幅度。",
                        "lively": "那我活泼一点！"}[value], background=True)
        return True

    def set_gesture_sensitivity(self, value, quiet=False):
        """手势灵敏度：low / normal / high。"""
        if value not in ("low", "normal", "high"):
            return False
        self.gesture_sensitivity = value
        self._apply_gesture_tuning()
        self._save_config()
        if not quiet:
            self.speak({"low": "手势要划得久一点我才懂。",
                        "normal": "手势灵敏度正常。",
                        "high": "轻轻一划我就有反应。"}[value], background=True)
        return True

    def set_shake_refresh(self, on, quiet=False):
        """摇一摇：关 = 摇头撒娇，开 = 摇一次就刷新。"""
        self.shake_refresh = bool(on)
        self._save_config()
        if not quiet:
            self.speak("摇一摇就刷新。" if self.shake_refresh
                       else "摇一摇就是摇头。", background=True)
        return True

    def set_autostart(self, on, quiet=False):
        """开机自启：写 HKCU 的 Run 项（不需要管理员）。"""
        on = bool(on)
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\\Microsoft\\Windows\\CurrentVersion\\Run",
                                 0, winreg.KEY_SET_VALUE)
            try:
                if on:
                    winreg.SetValueEx(key, "DesktopPet", 0, winreg.REG_SZ,
                                      self._launch_command())
                else:
                    try:
                        winreg.DeleteValue(key, "DesktopPet")
                    except FileNotFoundError:
                        pass
            finally:
                winreg.CloseKey(key)
        except Exception:                       # noqa: BLE001
            _log_exception()
            return False
        self.autostart = on
        self._save_config()
        if not quiet:
            self.speak("开机我就自己出来。" if on else "开机我先不出来。",
                       background=True)
        return True

    def _launch_command(self):
        """开机自启要执行的命令行（打包版直接跑 exe，源码版跑 pythonw + 脚本）。"""
        if FROZEN:
            return '"%s"' % sys.executable
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pyw):
            pyw = sys.executable
        return '"%s" "%s"' % (pyw, os.path.join(ROOT, "desktop_pet.py"))

    def set_auto_restart(self, on, quiet=False):''')

# ---------------------------------------------------------------- 5) 跳跃幅度
rep('''            dy -= math.sin(self.jump * math.pi) * self.jump_px''',
    '''            dy -= (math.sin(self.jump * math.pi) * self.jump_px
                   * getattr(self, "_jump_gain", 1.0))''')

# ---------------------------------------------------------------- 6) 摇一摇 / 双下滑 / 长按
rep('''    def _track_extra_gestures(self, now, x, y):
        # 绕圈先记采样：后面几个判定都要看"手是不是在绕圈"，
        # 采样得先把当前这一笔算进去
        self._track_circle(now, x, y)
        # 横划躲一下接着判：这一笔最短，最容易被别的判定吃掉
        self._track_body_swipe(now, x, y)''',
    '''    def _track_extra_gestures(self, now, x, y):
        # 绕圈先记采样：后面几个判定都要看"手是不是在绕圈"，
        # 采样得先把当前这一笔算进去
        self._track_circle(now, x, y)
        # 摇一摇（来回至少 4 次）判在最前：它本身就是一串横向移动，
        # 要是先判横划躲闪，会被"躲一下"吃掉。
        if self._track_shake_head(now, x, y):
            return
        # 横划躲一下接着判：这一笔最短，最容易被别的判定吃掉
        self._track_body_swipe(now, x, y)

    def _track_shake_head(self, now, x, y):
        """在身上快速左右摇 -> 摇头（设置里可改成刷新）。"""
        if not self._in_body_zone(x, y):
            if self._shake_track and now - self._shake_track[-1][0] > 0.3:
                self._shake_track = []
            return False
        track = self._shake_track
        if track and track[-1][1] == x:          # 手没动：别把静止帧算进时长
            return False
        track.append((now, x, y))
        cutoff = now - 1.0
        while track and track[0][0] < cutoff:
            track.pop(0)
        if len(track) < 6:
            return False
        reversals = 0
        travel = 0.0
        last_dir = 0
        last_x = track[0][1]
        for _t, sx, _sy in track[1:]:
            step = sx - last_x
            travel += abs(step)
            if abs(step) >= 6:
                direction = 1 if step > 0 else -1
                if last_dir and direction != last_dir:
                    reversals += 1
                last_dir = direction
            last_x = sx
        span = now - track[0][0]
        if (reversals < 4 or travel < max(150.0, self.win_w * 0.9)
                or span > 1.0 or now < self._shake_ready_at
                or now < self.petting_until):
            return False
        self._shake_track = []
        self._body_track = []
        self._shake_ready_at = now + 5.0
        self._gesture_hits["shake"] = self._gesture_hits.get("shake", 0) + 1
        if self.shake_refresh:
            self.request_refresh()
        else:
            self._shake_head(now)
        return True

    def _shake_head(self, now):
        """摇头：0.7 秒里左右摆几下。"""
        self._shake_head_until = now + 0.7
        self.speak("别、别摇啦～", background=True)''')

# 双下滑弹一下
rep('''            self._gesture_hits["squash"] += 1
            self.squash = 1.0''',
    '''            self._gesture_hits["squash"] += 1
            self.squash = 1.0
            # 0.9 秒内连着两次下滑 = 弹一下（压扁 + 跳起来 + 冒爱心）
            if now - self._last_squash_at <= 0.9:
                self._gesture_hits["bounce"] = \\
                    self._gesture_hits.get("bounce", 0) + 1
                self.jump = max(self.jump, 0.9)
                try:
                    self.hearts.burst(self.head_anchor(), count=5)
                except Exception:               # noqa: BLE001
                    pass
            self._last_squash_at = now''')

# 长按不动 = 摸头
rep('''    def _on_press(self, event):
        self._note_interaction()''',
    '''    def _on_press(self, event):
        self._note_interaction()
        self._press_at = self._now()
        self._hold_petted = False''')

rep('''        self.phase += 0.075 * frame_k
        self._update_petting(now, dt)        # 摸头的平滑强度/位移''',
    '''        self.phase += 0.075 * frame_k
        # 按住不动 1 秒 = 摸头（给"懒得划来划去"的人一个入口）
        if (self.press_pos is not None and not self.moved
                and not self._hold_petted and now - self._press_at >= 1.0):
            self._hold_petted = True
            px, py = self.press_pos[0], self.press_pos[1]
            if self._in_head_zone(px, py):
                self.petting_until = now + 2.2
                self._pet_energy = max(self._pet_energy, 26.0)
                self._gesture_hits["hold"] = \\
                    self._gesture_hits.get("hold", 0) + 1
                try:
                    self.hearts.burst(self.head_anchor(), count=6)
                except Exception:               # noqa: BLE001
                    pass
        self._update_petting(now, dt)        # 摸头的平滑强度/位移''')

# ---------------------------------------------------------------- 7) 摇头角度
rep('''        if now < self._dodge_until:''',
    '''        if now < self._shake_head_until:
            total = 0.7
            p = 1.0 - (self._shake_head_until - now) / total
            self._shake_angle = math.sin(p * math.pi * 7.0) * 15.0 * (1.0 - p)
        else:
            self._shake_angle = 0.0
        if now < self._dodge_until:''')

rep('''        angle = max(-14.0, min(14.0, self._pet_angle))''',
    '''        angle = max(-14.0, min(14.0, self._pet_angle)) \\
            + getattr(self, "_shake_angle", 0.0)''')

rep('''        if (abs(self.squash) > 0.001 or self._pet_energy > 0.01
                or self._shoot_energy > 0.01
                or abs(self._spin_angle) > 0.12):''',
    '''        if (abs(self.squash) > 0.001 or self._pet_energy > 0.01
                or self._shoot_energy > 0.01
                or abs(self._spin_angle) > 0.12
                or abs(getattr(self, "_shake_angle", 0.0)) > 0.5):''')

io.open(P, 'w', encoding='utf-8', newline='').write(s)
print('gestures/settings patched')
