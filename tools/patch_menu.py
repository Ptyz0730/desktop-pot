# -*- coding: utf-8 -*-
"""把右键菜单从"系统灰"改成有分组、有图标、有配色的版本。"""
import io

P = 'desktop_pet.py'
s = io.open(P, encoding='utf-8').read()

# 1) 配色常量
anchor = 'SET_LINE = "#dbe8f7"'
assert anchor in s, 'SET_LINE anchor missing'
s = s.replace(anchor, anchor + '''
MENU_BG = "#fdfeff"
MENU_FG = "#243546"
MENU_HI = "#e8f2fd"
MENU_FG_HI = "#1466c8"
MENU_ACCENT = "#f4789f"
MENU_ICON = "#7fa2c6"
MENU_HEAD = "#9db4cd"''', 1)

# 2) 整段替换 _build_menu 的前半（到"只绑一次"注释前）
start = s.index('    def _build_menu(self):')
end = s.index('        # 只绑一次！', start)
old = s[start:end]

new = '''    # ------------------------------------------------------------ 右键菜单
    def _menu_font(self, size=10, bold=False):
        return (FONT_FAMILY, size, "bold" if bold else "normal")

    def _style_menu(self, menu):
        """统一菜单配色：Tk 默认的灰底黑字太朴素。"""
        try:
            menu.configure(font=self._menu_font(10),
                           bg=MENU_BG, fg=MENU_FG,
                           activebackground=MENU_HI,
                           activeforeground=MENU_FG_HI,
                           bd=0, relief="flat", activeborderwidth=0,
                           selectcolor=MENU_ACCENT)
        except tk.TclError:
            pass
        return menu

    def _menu_icon(self, name):
        """菜单左边的小图标。PhotoImage 必须留引用，不然会被回收成空白。"""
        try:
            photo = self._photo(_icon_pil(name, 17, MENU_ICON), page=False)
        except Exception:                       # noqa: BLE001
            return None
        self._menu_photos.append(photo)
        return photo

    def _menu_add(self, menu, label, command=None, icon=None,
                  accel=None, state=None):
        kwargs = {"label": label}
        if command is not None:
            kwargs["command"] = command
        if accel:
            kwargs["accelerator"] = accel
        if state:
            kwargs["state"] = state
        photo = self._menu_icon(icon) if icon else None
        if photo is not None:
            kwargs["image"] = photo
            kwargs["compound"] = "left"
        menu.add_command(**kwargs)

    def _menu_head(self, menu, title):
        """分组标题：一条分隔线 + 一行浅蓝小字。"""
        menu.add_separator()
        menu.add_command(label="  " + title, state="disabled",
                         font=(FONT_FAMILY, 8), foreground=MENU_HEAD)

    def _build_menu(self):
        self._menu_photos = []
        self.menu = self._style_menu(tk.Menu(self.root, tearoff=0))
        self.image_menu = self._style_menu(tk.Menu(self.menu, tearoff=0))
        self.image_var = tk.StringVar(value=self.image_name)
        self._fill_image_menu()
        size_menu = self._style_menu(tk.Menu(self.menu, tearoff=0))
        self.scale_var = tk.DoubleVar(value=self.scale)
        for s in self.SCALES:
            size_menu.add_radiobutton(
                label="%d%%" % round(s * 100), value=s,
                variable=self.scale_var,
                command=lambda v=s: self._defer(self.set_scale, v))
        opacity_menu = self._style_menu(tk.Menu(self.menu, tearoff=0))
        self.opacity_var = tk.DoubleVar(value=self.opacity)
        for value in OPACITY_STEPS:
            opacity_menu.add_radiobutton(
                label="%d%%" % round(value * 100), value=value,
                variable=self.opacity_var,
                command=lambda v=value: self._defer(self.set_opacity, v))
        opacity_menu.add_separator()
        opacity_menu.add_command(label="Ctrl + 滚轮 也能调", state="disabled")

        ai_menu = self._style_menu(tk.Menu(self.menu, tearoff=0))
        self.ai_var = tk.BooleanVar(value=self.ai_enabled)
        # 「启用 AI」是设置项，放在设置窗口的「对话」页，这里只留功能入口
        self._menu_add(ai_menu, "设置 API Key…", icon="key",
                       command=lambda: self._defer(self.set_api_key))
        self._menu_add(ai_menu, "清空对话记忆", icon="refresh",
                       command=lambda: self._defer(self.forget_chat))
        self.model_label = "模型: %s" % self.brain.model
        ai_menu.add_command(label=self.model_label, state="disabled")
        self.affection_label = "好感度: %d / 100" % self.affection
        ai_menu.add_command(label=self.affection_label, state="disabled")
        ai_menu.add_command(
            label="人设: %s" % ai_client.persona_display_name(
                getattr(self, "_persona", DEFAULT_PERSONA)),
            state="disabled")
        persona_menu = self._style_menu(tk.Menu(ai_menu, tearoff=0))
        self.persona_var = tk.StringVar(
            value=getattr(self, "_persona", DEFAULT_PERSONA))
        for key in ai_client.PERSONA_PROMPTS:
            persona_menu.add_radiobutton(
                label="%s（%s）" % (ai_client.persona_display_name(key), key),
                value=key, variable=self.persona_var,
                command=lambda k=key: self._defer(self.set_persona, k))
        ai_menu.add_cascade(label="这张图的人设", menu=persona_menu)
        self._affection_menu = ai_menu

        self.music_menu = self._style_menu(tk.Menu(self.menu, tearoff=0))
        self.music_var = tk.StringVar(value=self.music_name)
        self._fill_music_menu()
        self.web_menu = self._style_menu(tk.Menu(self.menu, tearoff=0))
        self._fill_web_menu()

        play_menu = self._style_menu(tk.Menu(self.menu, tearoff=0))
        for label, key, icon in (("摸头", "head", "paw"),
                                 ("跳一下", "jump", "jump"),
                                 ("压扁", "squash", "squash"),
                                 ("转圈圈（晕）", "spin", "spin"),
                                 ("躲一下", "dodge", "dodge")):
            self._menu_add(play_menu, label, icon=icon,
                           command=lambda k=key: self._defer(self.do_gesture, k))
        play_menu.add_separator()
        self._menu_add(play_menu, "打飞机（chm）", icon="shoot",
                       command=lambda: self._defer(self.trigger_shooting))
        self._play_menu = play_menu

        # 顶栏：最常用的三个入口
        self._menu_add(self.menu, "跟它说话", icon="bubble", accel="点一下",
                       command=lambda: self._defer(self.speak_random))
        self._menu_add(self.menu, "对话…", icon="cat", accel="双击",
                       command=lambda: self._defer(self.open_chat))
        self._menu_add(self.menu, "设置…", icon="window", accel="Esc",
                       command=lambda: self._defer(self.open_settings))

        self._menu_head(self.menu, "形象")
        self.menu.add_cascade(label="形象", menu=self.image_menu,
                              image=self._menu_icon("image"), compound="left")
        self.menu.add_cascade(label="大小", menu=size_menu,
                              image=self._menu_icon("size"), compound="left")
        self.menu.add_cascade(label="不透明度", menu=opacity_menu,
                              image=self._menu_icon("eye"), compound="left")

        self._menu_head(self.menu, "玩法")
        self.menu.add_cascade(label="逗它玩", menu=play_menu,
                              image=self._menu_icon("sparkle"), compound="left")
        self._menu_add(self.menu, "说点什么", icon="smile",
                       command=lambda: self._defer(self.speak_random))
        self._menu_add(self.menu, "来一个颜文字", icon="face",
                       command=lambda: self._defer(self.say_kaomoji))

        self._menu_head(self.menu, "声音与网页")
        self.menu.add_cascade(label="音乐", menu=self.music_menu,
                              image=self._menu_icon("note"), compound="left")
        self.menu.add_cascade(label="打开网页", menu=self.web_menu,
                              image=self._menu_icon("globe"), compound="left")

        self._menu_head(self.menu, "维护")
        self.menu.add_cascade(label="AI 设置", menu=ai_menu,
                              image=self._menu_icon("sparkle"), compound="left")
        self._menu_add(self.menu, "刷新一下（卡死急救）", icon="refresh",
                       command=lambda: self._defer(self.request_refresh))
        self._menu_add(self.menu, "修改器…", icon="key",
                       command=lambda: self._defer(self.open_modifier))
        self._menu_add(self.menu, "重置", icon="refresh",
                       command=lambda: self._defer(self.confirm_reset))
        self._menu_add(self.menu, "回到右下角", icon="pin",
                       command=lambda: self._defer(self.reset_position))
        self._menu_add(self.menu, "打开图片文件夹", icon="image",
                       command=lambda: self._defer(self.open_image_folder))
        self.menu.add_command(
            label="渲染后端: %s" % self.backend.style, state="disabled")

        self.menu.add_separator()
        self._menu_add(self.menu, "退出", icon="power",
                       command=lambda: self._defer(self.quit))

'''
s = s[:start] + new + s[end:]
io.open(P, 'w', encoding='utf-8', newline='').write(s)
print('menu rebuilt, chars:', len(new))
