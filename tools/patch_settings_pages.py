# -*- coding: utf-8 -*-
"""第十一轮：设置窗口加校徽、加「外观」「关于」两页、补新开关。"""
import io

P = 'desktop_pet.py'
s = io.open(P, encoding='utf-8').read()


def rep(old, new, count=1):
    global s
    assert old in s, 'missing anchor: %r' % old[:70]
    s = s.replace(old, new, count)


# ---------------------------------------------------------------- 1) 校徽位图
rep('''def _logo_pil(size=62):''',
    '''_BADGE_CACHE = {}


def _badge_pil(size=64, faded=False):
    """校徽（圆形，四角透明）。faded=True 给大尺寸水印用。"""
    key = (int(size), bool(faded))
    if key in _BADGE_CACHE:
        return _BADGE_CACHE[key]
    path = _asset_path("school_badge_faded.png" if faded else "school_badge.png")
    try:
        img = Image.open(path).convert("RGBA").resize((int(size), int(size)),
                                                      Image.LANCZOS)
    except Exception:                       # noqa: BLE001 - 缺图也要能开设置
        img = Image.new("RGBA", (int(size), int(size)), (244, 120, 159, 255))
    _BADGE_CACHE[key] = img
    return img


def _logo_pil(size=62):''')

# ---------------------------------------------------------------- 2) 五个分类
rep('''    TABS = (("prefs", "偏好", "cat"),
            ("gestures", "手势", "paw"),
            ("talk", "对话", "bubble"))''',
    '''    TABS = (("prefs", "偏好", "cat"),
            ("gestures", "手势", "paw"),
            ("look", "外观", "eye"),
            ("talk", "对话", "bubble"),
            ("about", "关于", "image"))''')

# ---------------------------------------------------------------- 3) 侧栏校徽
rep('''        tk.Label(side, text="v1.0", bg=SET_SIDE, fg="#c9dbec",
                 font=(FONT_FAMILY, 8)).pack(side="bottom", pady=14)''',
    '''        tk.Label(side, text="v1.1", bg=SET_SIDE, fg="#c9dbec",
                 font=(FONT_FAMILY, 8)).pack(side="bottom", pady=(0, 12))
        tk.Label(side, text="莆田第一中学", bg=SET_SIDE, fg="#c6a6b2",
                 font=(FONT_FAMILY, 8)).pack(side="bottom", pady=(0, 6))
        badge = ImageTk.PhotoImage(_badge_pil(56), master=win)
        self._photos.append(badge)
        tk.Label(side, image=badge, bg=SET_SIDE).pack(side="bottom", pady=(0, 4))''')

# ---------------------------------------------------------------- 4) 偏好页：开机自启
rep('''        self._section(parent, "卡死急救", "shield")''',
    '''        self._section(parent, "启动", "power")
        self._setting(parent, "power", "开机自动启动",
                      "开机后自己出现在桌面上（写的是当前用户的启动项，不需要管理员）。",
                      lambda: pet.autostart, pet.set_autostart)
        self._section(parent, "卡死急救", "shield")''')

# ---------------------------------------------------------------- 5) 手势页：摇一摇
rep('''        self._setting(parent, "click", "点击说话",''',
    '''        self._setting(parent, "refresh", "摇一摇刷新",
                      "在身上快速左右摇一摇：开着就直接刷新（卡死时也能摇），"
                      "关掉它只是摇头撒娇。",
                      lambda: pet.shake_refresh, pet.set_shake_refresh)
        self._setting(parent, "click", "点击说话",''')

rep('''        self._note(parent, "下滑压扁 / 上划跳一下 / 身体横划躲开 / 绕圈转晕 / "
                           "头顶来回蹭是摸头 / 身上左右摇一摇是刷新。"''',
    '''        self._note(parent, "下滑压扁 / 连着下滑两次弹一下 / 上划跳一下 / "
                           "身体横划躲开 / 绕圈转晕 / 头顶来回蹭是摸头 / "
                           "按住不动一秒也是摸头 / 身上左右摇一摇看上面的开关。"''')

# ---------------------------------------------------------------- 6) 外观页
rep('''    def _page_talk(self, parent):''',
    '''    def _page_look(self, parent):
        pet = self.pet
        self._section(parent, "气泡", "bubble")
        self._choice(parent, "bubble", "停留时长",
                     "一句话在屏幕上停留多久。",
                     [(2000, "2 秒"), (4000, "4 秒"), (6000, "6 秒"),
                      (8000, "8 秒")],
                     lambda: pet.bubble_ms, pet.set_bubble_ms, "bubble_ms")
        self._section(parent, "动作", "sparkle")
        self._choice(parent, "sparkle", "动作幅度",
                     "跳多高、晃多明显。安静一点适合上班摸鱼。",
                     [("calm", "安静"), ("normal", "正常"), ("lively", "活泼")],
                     lambda: pet.anim_level, pet.set_anim_level, "anim_level")
        self._choice(parent, "paw", "手势灵敏度",
                     "划动要多快、多远才算一个手势。",
                     [("low", "迟钝"), ("normal", "正常"), ("high", "灵敏")],
                     lambda: pet.gesture_sensitivity,
                     pet.set_gesture_sensitivity, "gesture")
        self._note(parent, "灵敏度调高以后轻轻一划就有反应，但打字时手从屏幕上"
                           "扫过也可能被当成手势；调低更稳。")

    def _page_about(self, parent):
        pet = self.pet
        box = tk.Frame(parent, bg=SET_BG)
        box.pack(fill="x", pady=(18, 4))
        badge = ImageTk.PhotoImage(_badge_pil(104), master=self.win)
        self._page_photos.append(badge)
        tk.Label(box, image=badge, bg=SET_BG).pack()
        tk.Label(box, text="莆田第一中学", bg=SET_BG, fg="#22344a",
                 font=(FONT_FAMILY, 13, "bold")).pack(pady=(8, 0))
        tk.Label(box, text="桌面宠物 · 校徽纪念版", bg=SET_BG, fg="#8aa6c9",
                 font=(FONT_FAMILY, 9)).pack(pady=(2, 0))
        self._section(parent, "关于", "cat")
        holder = self._row_shell(parent, "image", "素材目录",
                                 "立绘放在 image/，音乐放在 music/，换图不用改代码。")
        PillButton(holder, "打开 image", kind="white", size="s",
                   command=lambda: self._apply(pet.open_image_folder, None)
                   ).pack(side="left")
        self._note(parent, "版本 v1.1   渲染后端 %s   配置文件 pet_config.json"
                   % getattr(getattr(pet, "backend", None), "style", "auto"))

    def _page_talk(self, parent):''')

# ---------------------------------------------------------------- 7) 重置
rep('''            "auto_restart": True,''',
    '''            "auto_restart": True,
            "bubble_ms": 4000,
            "anim_level": "normal",
            "gesture_sensitivity": "normal",
            "shake_refresh": False,
            "autostart": False,''')

io.open(P, 'w', encoding='utf-8', newline='').write(s)
print('settings pages patched')
