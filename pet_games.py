# -*- coding: utf-8 -*-
"""桌宠小游戏（右键 → 玩法 → 小游戏）。

四个都是点着玩、几秒钟一局的小东西，适合挂在桌宠旁边：

* 猜拳     —— 三局两胜，它自己出手势
* 猜数字   —— 1~100，看几次能猜到（数字键盘 + 键盘输入）
* 翻牌记忆 —— 4x3 十二张牌，六对图案（翻牌有动画）
* 打地鼠   —— 30 秒，九宫格里冒头就点

界面全部用 Canvas 画：圆角卡片、悬停浮起、按下回弹、粒子、震动、
标题栏可拖动、开窗淡入。每个窗口都贴着宠物放（上面放不下就挪到下面），
Esc / 右上角 ✕ 关掉；玩完它会在气泡里点评一句，好感度给一点点（每局一次）。
"""
import math
import sys
import os
import random
import time
import tkinter as tk

FONT = "Microsoft YaHei UI"          # 正文（启动时按系统字体再挑一次）
TITLE_FONT = "Microsoft YaHei UI"    # 标题（挑不到圆体就退回正文字体）

# 配色：卡通纸片风 —— 奶油纸底、粗描边、糖霜色块
BG = "#fff7ea"          # 纸底
SHELL = "#ffe6bf"       # 外框（奶油）
PAPER = "#fffdf6"
CARD = "#ffffff"
INK = "#3b2b3a"         # 深巧克力：描边 + 正文
INK_SOFT = "#6d5b6b"
MUTED = "#a08e9c"
OUTLINE = "#3b2b3a"     # 统一描边色
ACCENT = "#ff6f61"      # 珊瑚红
ACCENT_DK = "#d94f43"
PEACH = "#ffe1cf"
PEACH_DK = "#ffc3a8"
MINT = "#c8f0d4"
MINT_DK = "#7ed3a1"
SKY = "#c7e9ff"
SUN = "#ffd166"
GOLD = "#f4a62a"
SHADOW = "#e2c9b4"
DIRT = "#a9785a"
DIRT_DK = "#7b5540"
FIELD = "#f4e7d6"
BODY = "#c08a63"


def _detect_fonts(root):
    """挑一套圆乎乎的字体（幼圆/华文琥珀），没有就用雅黑。"""
    global FONT, TITLE_FONT
    try:
        import tkinter.font as tkfont
        fams = set(tkfont.families(root))
    except Exception:                            # noqa: BLE001
        return
    for name in ("幼圆", "YouYuan", "微软雅黑", "Microsoft YaHei UI"):
        if name in fams:
            FONT = name
            break
    for name in ("幼圆", "YouYuan", "微软雅黑", "Microsoft YaHei UI"):
        if name in fams:
            TITLE_FONT = name
            break


def _ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def _ease_in_out(t):
    t = max(0.0, min(1.0, t))
    return 3 * t * t - 2 * t * t * t


def _mix(color, other, k):
    """把两个 #rrggbb 按 k 混合。"""
    try:
        a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
        b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    except (ValueError, IndexError):
        return color
    return "#%02x%02x%02x" % tuple(
        int(round(a[i] + (b[i] - a[i]) * k)) for i in range(3))


EMOJI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "assets", "emoji")

HAND_FILES = {"石头": "fist.png", "剪刀": "scissors.png", "布": "hand.png"}
SYMBOL_FILES = {"♠": "spade.png", "♥": "heart.png", "♦": "diamond.png",
                "♣": "club.png", "★": "star.png", "●": "circle.png"}

_EMOJI_CACHE = {}


def _emoji_path(name):
    """素材可能在项目里，也可能被打进 exe（_MEIPASS）。"""
    bases = [EMOJI_DIR]
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        bases.insert(0, os.path.join(mei, "assets", "emoji"))
    for base in bases:
        path = os.path.join(base, name)
        if os.path.isfile(path):
            return path
    return None


def emoji_image(master, name, size):
    """按尺寸缓存的 PhotoImage；素材缺失时返回 None（调用方退回画矢量）。

    PhotoImage 一定要挂在**主 root** 上：挂在游戏窗口上时，窗口一关图片就被
    销毁，别的画布还引用着它就变成野指针（Tk 会直接崩）。
    """
    key = (name, int(size))
    img = _EMOJI_CACHE.get(key)
    if img is not None:
        return img
    path = _emoji_path(name)
    if path is None:
        return None
    try:
        from PIL import Image, ImageTk
        root = getattr(tk, "_default_root", None) or master
        im = Image.open(path).convert("RGBA")
        im = im.resize((int(size), int(size)), Image.LANCZOS)
        img = ImageTk.PhotoImage(im, master=root)
    except Exception:                       # noqa: BLE001
        return None
    _EMOJI_CACHE[key] = img
    return img


def _work_area(root):
    try:
        import desktop_pet
        return desktop_pet.work_area(root)
    except Exception:                            # noqa: BLE001
        return (0, 0, root.winfo_screenwidth(), root.winfo_screenheight())


def stats_of(pet):
    st = pet.cfg.get("games")
    if not isinstance(st, dict):
        st = {}
        pet.cfg["games"] = st
    return st


def save_stats(pet):
    try:
        pet._save_config()
    except Exception:                            # noqa: BLE001
        pass
    try:
        refresh = getattr(pet, "_refresh_game_stats", None)
        if refresh is not None:
            refresh()
    except Exception:                            # noqa: BLE001
        pass


LINES = {
    "闷骚少年": {
        "win": "基操勿六。",
        "lose": "……再来。",
        "tie": "平了，接着来。",
        "done": "还行吧。",
        "great": "手气不错嘛。",
        "open": "陪你玩会儿。",
    },
    "骚话少年": {
        "win": "バカ，我赢了。",
        "lose": "もう一回，再来一次。",
        "tie": "同点。気持ちいい。",
        "done": "気持ちいい…我是说这局。",
        "great": "君だけよ，你最厉害。",
        "open": "陪你玩会儿，気持ちいい",
    },
    "话痨朋友": {
        "win": "我厉害吧！",
        "lose": "哎呀，再来再来！",
        "tie": "平手，接着来！",
        "done": "玩得不错！",
        "great": "你也太强了吧！",
        "open": "来来来，陪你玩！",
    },
}


class Pill:
    """画布上的圆角按钮：悬停浮起、按下回弹。

    注意：悬停只改颜色和坐标，**不删除重建**画布元素。以前这里重建，
    鼠标底下的元素会反复消失又出现，Enter/Leave 来回触发把主线程打满，
    看门狗就会判定卡死并重启进程。
    """

    def __init__(self, game, x, y, w, h, text, command,
                 fill=ACCENT, fg="#ffffff", size=11, radius=None):
        self.g = game
        self.x, self.y, self.w, self.h = x, y, w, h
        self.text = text
        self.command = command
        self.fill, self.fg, self.size = fill, fg, size
        self.radius = h // 2 if radius is None else radius
        self.enabled = True
        self.hover = False
        self.tag = "pill%d" % id(self)
        self._ids = None
        self._draw()

    # ------------------------------------------------------------------ 画
    def _points(self, x0, y0, x1, y1, r):
        r = max(1, min(r, (x1 - x0) / 2.0, (y1 - y0) / 2.0))
        pts = []
        for cx, cy, start in ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0),
                              (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)):
            for i in range(5):
                a = math.radians(start + 90.0 * i / 4.0)
                pts.extend((cx + r * math.cos(a), cy + r * math.sin(a)))
        return pts

    def _draw(self):
        c = self.g.c
        if c is None:
            return
        try:
            if self._ids is None:
                pts = self._points(self.x + 1, self.y + 4,
                                   self.x + self.w + 1, self.y + self.h + 4,
                                   self.radius)
                shadow = c.create_polygon(pts, smooth=True, splinesteps=12,
                                          fill=OUTLINE, tags=(self.tag,))
                pts = self._points(self.x, self.y, self.x + self.w,
                                   self.y + self.h, self.radius)
                body = c.create_polygon(pts, smooth=True, splinesteps=12,
                                        fill=self.fill, outline=OUTLINE,
                                        width=3, tags=(self.tag,))
                text = c.create_text(self.x + self.w / 2.0,
                                     self.y + self.h / 2.0, text=self.text,
                                     fill=self.fg,
                                     font=(FONT, self.size, "bold"),
                                     tags=(self.tag,))
                self._ids = (shadow, body, text)
                c.tag_bind(self.tag, "<Enter>", self._on_enter)
                c.tag_bind(self.tag, "<Leave>", self._on_leave)
                c.tag_bind(self.tag, "<Button-1>", self._on_click)
        except tk.TclError:
            self._ids = None
            return
        self._apply()

    def _apply(self):
        c = self.g.c
        if c is None or self._ids is None:
            return
        shadow, body, text = self._ids
        dy = 0
        fill = self.fill
        if not self.enabled:
            fill = "#efe4dc"
        elif self.hover:
            fill = _mix(self.fill, "#ffffff", 0.22)
        fg = self.fg if self.enabled else "#b3a5a0"
        x, y, w, h = self.x, self.y + dy, self.w, self.h
        try:
            c.coords(shadow, *self._points(x + 1, y + 4, x + w + 1,
                                           y + h + 4, self.radius))
            c.coords(body, *self._points(x, y, x + w, y + h, self.radius))
            c.itemconfigure(body, fill=fill)
            c.coords(text, x + w / 2.0, y + h / 2.0)
            c.itemconfigure(text, text=self.text, fill=fg)
        except tk.TclError:
            pass

    def _on_enter(self, _e=None):
        if not self.enabled or self.hover:
            return
        self.hover = True
        self._apply()

    def _on_leave(self, _e=None):
        if not self.hover:
            return
        self.hover = False
        self._apply()

    def _on_click(self, _e=None):
        if not self.enabled:
            return
        self.g.click_ring(self.x + self.w / 2.0, self.y + self.h / 2.0)
        if self.command:
            self.command()

    # --------------------------------------------------------------- 状态
    def set_enabled(self, on):
        if self.enabled != bool(on):
            self.enabled = bool(on)
            if not self.enabled:
                self.hover = False
            self._apply()

    def set_text(self, text):
        if text != self.text:
            self.text = text
            self._apply()

    def place(self, x, y, w=None, h=None):
        self.x, self.y = x, y
        if w is not None:
            self.w = w
            self.radius = h // 2 if h is None else h // 2
        if h is not None:
            self.h = h
        self._apply()

    def destroy(self):
        self._ids = None
        try:
            self.g.c.delete(self.tag)
        except (tk.TclError, AttributeError):
            pass


class GameWindow:
    """小游戏窗口：一个画布画到底，带标题条、贴边摆放、淡入。"""

    W, H = 430, 380
    TITLE = "小游戏"
    SUB = ""
    HINT = ""
    ICON = "●"
    ICON_COLOR = ACCENT
    KEY = ""

    def __init__(self, pet, key):
        self.pet = pet
        self.key = key
        self.win = None
        self.c = None
        self._jobs = []
        self._awarded = 0
        self._stat = stats_of(pet)
        self.top = 74                       # 标题条以下就是游戏区
        self._last = time.monotonic()
        self._fade = 0.0
        self._fade_on = False
        self._drag_from = None

    # ------------------------------------------------------------ 生命周期
    def show(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.deiconify()
            self.win.lift()
            return self
        try:
            self.pet._drop_menu()
        except Exception:                        # noqa: BLE001
            pass
        self.win = tk.Toplevel(self.pet.root)
        self.win.overrideredirect(True)
        try:
            import ai_client
            who = ai_client.persona_display_name(
                getattr(self.pet, "_persona", ""))
        except Exception:                        # noqa: BLE001
            who = "桌宠"
        self.win.title("%s · %s" % (self.TITLE, who))
        self.win.configure(bg=SHELL)
        self.win.attributes("-topmost", True)
        self.win.geometry("%dx%d" % (self.W, self.H))
        try:
            self.win.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        self.c = tk.Canvas(self.win, width=self.W, height=self.H, bg=SHELL,
                           highlightthickness=0, bd=0)
        self.c.pack(fill="both", expand=True)
        self._draw_shell()
        self.build()
        self.c.bind("<ButtonPress-1>", self._drag_start)
        self.c.bind("<B1-Motion>", self._drag_move)
        self.c.bind("<ButtonRelease-1>", self._drag_end)
        self.win.bind("<Escape>", lambda e: self.close())
        self.c.bind("<Escape>", lambda e: self.close())
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self._place()
        self.after(180, lambda: self.say(None, "open"))
        self._fade_on = True
        self._last = time.monotonic()
        self._loop()
        try:
            self.win.focus_force()
            self.c.focus_set()
        except tk.TclError:
            pass
        return self

    # ------------------------------------------------------------ 画外壳
    def _draw_shell(self):
        c = self.c
        _detect_fonts(self.win)
        c.create_rectangle(0, 0, self.W, self.H, fill=SHELL, outline="")
        # 纸片外框（粗描边）
        self.rrect(5, 5, self.W - 5, self.H - 5, 22, fill=BG,
                   outline=OUTLINE, width=3)
        self._draw_doodles()
        # 图标（贴纸）
        self.rrect(19, 22, 63, 66, 15, fill=OUTLINE)
        self.rrect(17, 18, 61, 62, 15, fill=self.ICON_COLOR,
                   outline=OUTLINE, width=3)
        c.create_text(39, 40, text=self.ICON, fill="#ffffff",
                      font=(FONT, 17, "bold"))
        # 标题（描边字）
        self.c.create_text(75, 32, text=self.TITLE, fill=INK, anchor="w",
                           font=(TITLE_FONT, 17, "bold"))
        if self.SUB:
            c.create_text(75, 55, text=self.SUB, fill=INK_SOFT, anchor="w",
                          font=(FONT, 9))
        # 关闭按钮
        self._close_pill = Pill(self, self.W - 44, 22, 28, 28, "✕",
                                self.close, fill=CARD, fg=INK_SOFT,
                                size=11, radius=14)
        # 顶部分隔（虚线）+ 底部提示
        c.create_line(18, self.top - 8, self.W - 18, self.top - 8,
                      fill=SHADOW, width=2, dash=(6, 5))
        if self.HINT:
            c.create_text(20, self.H - 15, text=self.HINT, fill=MUTED,
                          anchor="w", font=(FONT, 8))
        c.create_text(self.W - 20, self.H - 15, text="拖动标题栏可以挪走",
                      fill=MUTED, anchor="e", font=(FONT, 8))

    def _draw_doodles(self):
        """角落里的纸片小装饰：星星、小圆点、云。"""
        c = self.c
        star = getattr(self, "_star", None)
        if star is None:
            return
        for cx, cy, r, fill in ((self.W - 33, self.H - 40, 7, SUN),
                                (26, self.H - 44, 5, PEACH_DK)):
            star(cx, cy, r, fill)
        for cx, cy in ((52, self.H - 36), (self.W - 46, self.H - 30)):
            c.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill=SKY,
                          outline=OUTLINE, width=2)

    def _star(self, cx, cy, r, fill, tags=()):
        pts = []
        for i in range(10):
            a = math.radians(-90 + 36 * i)
            rr = r if i % 2 == 0 else r * 0.45
            pts.extend((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        return self.c.create_polygon(pts, fill=fill, outline=OUTLINE, width=2,
                                     tags=tags)

    # ------------------------------------------------------------ 画图工具
    def rrect(self, x0, y0, x1, y1, r=12, **kw):
        """圆角矩形（用平滑多边形近似）。"""
        r = max(1, min(r, (x1 - x0) / 2.0, (y1 - y0) / 2.0))
        pts = []
        for cx, cy, start in ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0),
                              (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)):
            for i in range(5):
                a = math.radians(start + 90.0 * i / 4.0)
                pts.extend((cx + r * math.cos(a), cy + r * math.sin(a)))
        return self.c.create_polygon(pts, smooth=True, splinesteps=12, **kw)

    def capsule(self, x0, y0, x1, y1, width, **kw):
        kw.pop("capstyle", None)
        return self.c.create_line(x0, y0, x1, y1, width=width,
                                  capstyle=tk.ROUND, **kw)

    def capsule_ol(self, x0, y0, x1, y1, width, fill, outline=OUTLINE,
                   outline_width=3, tags=()):
        """带描边的圆头线（卡通手/手指用）。"""
        self.c.create_line(x0, y0, x1, y1, width=width + outline_width * 2,
                           fill=outline, capstyle=tk.ROUND, tags=tags)
        return self.c.create_line(x0, y0, x1, y1, width=width, fill=fill,
                                  capstyle=tk.ROUND, tags=tags)

    def txt(self, x, y, text, size=11, fill=INK, weight="normal",
            anchor="center", **kw):
        return self.c.create_text(x, y, text=text, fill=fill, anchor=anchor,
                                  font=(FONT, size, weight), **kw)

    def txt_out(self, x, y, text, size=15, fill=INK, anchor="center",
                outline=OUTLINE, weight="bold", tags=()):
        """描边字：先用描边色在四周画一遍，再把字盖上去。

        返回一个 tag 字符串（不是 item id），这样 itemconfigure(tag, ...)
        能同时改到描边层和字面层。
        """
        self._ot_seq = getattr(self, "_ot_seq", 0) + 1
        tag = "ot%d" % self._ot_seq
        all_tags = tuple(tags) + (tag,)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            self.c.create_text(x + dx, y + dy, text=text, fill=outline,
                               anchor=anchor, font=(FONT, size, weight),
                               tags=all_tags)
        self.c.create_text(x, y, text=text, fill=fill, anchor=anchor,
                           font=(FONT, size, weight), tags=all_tags)
        return tag

    def card(self, x0, y0, x1, y1, r=14, fill=CARD, outline=OUTLINE,
             shadow=True, shadow_dy=4, tags=()):
        if shadow:
            self.rrect(x0, y0 + shadow_dy, x1, y1 + shadow_dy, r,
                       fill=SHADOW if isinstance(shadow, bool) else str(shadow),
                       outline="", tags=tags)
        return self.rrect(x0, y0, x1, y1, r, fill=fill,
                          outline=outline or "", width=3 if outline else 0,
                          tags=tags)

    # ------------------------------------------------------------ 动效
    def click_ring(self, x, y, color=None):
        color = color or PEACH_DK
        ring = self.c.create_oval(x - 6, y - 6, x + 6, y + 6,
                                  outline=color, width=2)

        def step(i=0):
            if self.c is None:
                return
            i += 1
            if i > 9:
                try:
                    self.c.delete(ring)
                except tk.TclError:
                    pass
                return
            r = 6 + i * 5
            try:
                self.c.coords(ring, x - r, y - r, x + r, y + r)
                self.c.itemconfigure(ring, width=max(1, 3 - i // 4),
                                     outline=_mix(color, BG, i / 10.0))
            except tk.TclError:
                return
            self.after(16, step)

        step()

    def float_text(self, x, y, text, color=ACCENT, size=12):
        item = self.c.create_text(x, y, text=text, fill=color,
                                  font=(FONT, size, "bold"))

        def step(i=0):
            if self.c is None:
                return
            i += 1
            if i > 26:
                try:
                    self.c.delete(item)
                except tk.TclError:
                    pass
                return
            try:
                self.c.move(item, 0, -1.6)
                self.c.itemconfigure(item, fill=_mix(color, BG, i / 30.0))
            except tk.TclError:
                return
            self.after(20, step)

        step()

    def burst(self, x, y, color=GOLD, n=8, spread=34):
        parts = []
        for _ in range(n):
            a = random.uniform(0, math.tau)
            r = random.uniform(4, spread)
            parts.append((self.c.create_oval(x - 3, y - 3, x + 3, y + 3,
                                             fill=color, outline=""),
                          math.cos(a) * r / 12.0, math.sin(a) * r / 12.0))

        def step(i=0):
            if self.c is None:
                return
            i += 1
            if i > 18:
                for item, _dx, _dy in parts:
                    try:
                        self.c.delete(item)
                    except tk.TclError:
                        pass
                return
            for item, dx, dy in parts:
                try:
                    self.c.move(item, dx, dy + 0.35)
                    self.c.itemconfigure(item, fill=_mix(color, BG, i / 20.0))
                except tk.TclError:
                    return
            self.after(20, step)

        step()

    def shake(self, item, amp=6):
        base = self.c.coords(item)
        if not base:
            return

        def step(i=0):
            if self.c is None:
                return
            i += 1
            if i > 10:
                try:
                    self.c.coords(item, *base)
                except tk.TclError:
                    pass
                return
            dx = amp * math.sin(i * 1.9) * (1 - i / 11.0)
            try:
                self.c.coords(item, base[0] + dx, *base[1:])
            except tk.TclError:
                return
            self.after(16, step)

        step()

    # ------------------------------------------------------------ 主循环
    def _loop(self):
        if self.win is None or not self.win.winfo_exists():
            return
        now = time.monotonic()
        dt = min(0.06, now - self._last)
        self._last = now
        if self._fade_on:
            self._fade = min(1.0, self._fade + dt * 6.0)
            try:
                self.win.attributes("-alpha", _ease_out(self._fade))
            except tk.TclError:
                self._fade_on = False
            if self._fade >= 1.0:
                self._fade_on = False
        try:
            self.tick(dt, now)
        except Exception:                        # noqa: BLE001
            pass
        try:
            self._jobs.append(self.win.after(16, self._loop))
        except tk.TclError:
            pass

    def tick(self, dt, now):
        """子类按帧更新动画。"""
        return None

    # ------------------------------------------------------------ 位置/拖动
    def _place(self):
        """贴宠物放：上 / 下 / 左 / 右，都不行才硬塞进屏幕里。"""
        root = self.pet.root
        left, top, right, bottom = _work_area(root)
        px, py = self.pet.win_x, self.pet.win_y
        pw, ph = self.pet.win_w, self.pet.win_h
        gap = 10
        ax = px + pw // 2
        cx = int(min(max(left + 8, ax - self.W // 2), max(left + 8, right - self.W - 8)))
        cy = int(min(max(top + 8, py + ph // 2 - self.H // 2),
                     max(top + 8, bottom - self.H - 8)))
        spots = []
        if py - self.H - gap >= top + 8:
            spots.append((cx, py - self.H - gap))          # 上方
        if py + ph + gap + self.H <= bottom - 8:
            spots.append((cx, py + ph + gap))              # 下方
        if px - gap - self.W >= left + 8:
            spots.append((px - gap - self.W, cy))          # 左边
        if px + pw + gap + self.W <= right - 8:
            spots.append((px + pw + gap, cy))              # 右边
        x, y = spots[0] if spots else (cx, cy)
        self.win.geometry("%dx%d+%d+%d" % (self.W, self.H, x, y))

    def _drag_start(self, e):
        if getattr(e, "y", 0) > self.top - 2:
            return
        self._drag_from = (e.x_root - self.win.winfo_x(),
                           e.y_root - self.win.winfo_y())

    def _drag_move(self, e):
        if not self._drag_from:
            return
        dx, dy = self._drag_from
        self.win.geometry("+%d+%d" % (e.x_root - dx, e.y_root - dy))

    def _drag_end(self, _e=None):
        self._drag_from = None

    def close(self):
        for job in self._jobs:
            try:
                self.win.after_cancel(job)
            except Exception:                    # noqa: BLE001
                pass
        self._jobs = []
        try:
            self.on_close()
        except Exception:                        # noqa: BLE001
            pass
        win = self.win
        self.win = None
        self.c = None
        if win is not None and win.winfo_exists():
            try:
                win.destroy()
            except tk.TclError:
                pass

    # ---------------------------------------------------------------- 小工具
    def after(self, ms, fn):
        if self.win is None:
            return None
        try:
            job = self.win.after(ms, fn)
        except tk.TclError:
            return None
        self._jobs.append(job)
        return job

    def line(self, kind):
        name = getattr(self.pet, "_persona", "") or ""
        table = LINES.get(name) or LINES["话痨朋友"]
        return table.get(kind) or LINES["话痨朋友"].get(kind, "")

    def say(self, text, kind=None):
        if kind:
            text = self.line(kind)
        if not text:
            return
        try:
            self.pet.speak(text)
        except Exception:                        # noqa: BLE001
            pass

    def award(self, delta):
        if self._awarded or not delta:
            return
        self._awarded = delta
        try:
            self.pet._apply_affection(delta)
        except Exception:                        # noqa: BLE001
            pass

    # 子类实现
    def build(self):
        raise NotImplementedError

    def on_close(self):
        pass


# ================================================================== 猜拳
class RPSGame(GameWindow):
    W, H = 430, 430
    TITLE = "猜拳"
    SUB = "三局两胜，先赢两把"
    ICON = "✊"
    ICON_COLOR = "#e8734f"
    HINT = "点手势 · Esc 关掉 · 每局只加一次好感"
    HANDS = ("石头", "剪刀", "布")
    BEATS = {("石头", "剪刀"), ("剪刀", "布"), ("布", "石头")}

    def build(self):
        self.you = self.it = self.rounds = 0
        self.done = False
        self.busy = False
        self.hover_ids = {}
        self.card_ids = {}
        self._awarded = 0
        self._shake_item = None
        self._reveal = 1.0
        self._pet_hand = None
        self._my_hand = None

        # 比分
        self._chip("你", 22)
        self._chip("它", self.W - 118, right=True)
        self.score_you = self.txt(92, 98, "0", 20, ACCENT, "bold")
        self.score_it = self.txt(self.W - 48, 98, "0", 20, INK, "bold")

        # 舞台：我方手 — VS — 它
        self.rrect(self.W / 2 - 94, 126, self.W / 2 + 94, 234, 40,
                   fill="#fff1e6", outline=OUTLINE, width=3)
        self.my_slot = (self.W / 2 - 58, 180)
        self.pet_slot = (self.W / 2 + 58, 180)
        self.txt_out(self.W / 2, 180, "VS", 12, "#ffffff", weight="bold")
        self.my_hand_ids = []
        self.pet_hand_ids = []
        self.result = self.txt(self.W / 2, 252, "出个手势吧", 11, INK_SOFT)

        # 三个手势按钮
        self.tiles = {}
        tile_w, gap = 118, 10
        x0 = (self.W - (tile_w * 3 + gap * 2)) / 2.0
        for i, hand in enumerate(self.HANDS):
            x = x0 + i * (tile_w + gap)
            tag = "tile%d" % i
            self.card(x, 278, x + tile_w, 356, 16, fill=CARD, tags=(tag,))
            cx, cy = x + tile_w / 2.0, 316
            self._hand_art(cx, cy - 2, hand, 54, tag)
            self.txt(cx, 344, hand, 9, MUTED, tags=(tag,))
            # 悬停只改这张卡片的描边颜色（不能在光标底下新建 item：
            # 新 item 会盖住卡片，Tk 就在 Enter/Leave 之间来回抖成死循环）
            self.card_ids[hand] = self.c.find_withtag(tag)[0]
            self.c.tag_bind(tag, "<Enter>",
                            lambda e, h=hand: self._hover_tile(h, True))
            self.c.tag_bind(tag, "<Leave>",
                            lambda e, h=hand: self._hover_tile(h, False))
            self.c.tag_bind(tag, "<Button-1>",
                            lambda e, h=hand: self.play(h))
            self.tiles[hand] = (x, tile_w, tag)

        self.again = Pill(self, (self.W - 132) / 2.0, self.H - 58, 132, 30, "再来一局",
                          self.reset, fill=PEACH, fg=INK, size=10)
        self.again.set_enabled(False)

    def _chip(self, label, x, right=False):
        w = 96
        self.card(x, 78, x + w, 120, 14, fill=CARD)
        self.txt(x + 16, 99, label, 9, MUTED, anchor="w")

    def _hover_tile(self, hand, on):
        if self.busy or self.done:
            return
        item = self.card_ids.get(hand)
        if item is not None:
            try:
                self.c.itemconfigure(item, outline=ACCENT if on else OUTLINE,
                                     width=3)
            except tk.TclError:
                pass

    # ------------------------------------------------------------ 画手
    def _hand_art(self, cx, cy, kind, size, tag):
        """手势用 OpenMoji 图；素材缺失时才退回矢量画。"""
        img = emoji_image(self.win, HAND_FILES.get(kind, ""), size)
        if img is not None:
            return [self.c.create_image(cx, cy, image=img, tags=(tag,))]
        return [self.draw_hand(cx, cy, size * 0.42, kind, ACCENT_DK, tags=(tag,))]

    def _hand_art_big(self, cx, cy, kind, color, tags=()):
        img = emoji_image(self.win, HAND_FILES.get(kind, ""), 104)
        if img is not None:
            return [self.c.create_image(cx, cy, image=img, tags=tags)]
        return self.draw_hand(cx, cy, 30, kind, color, tags=tags)

    def draw_hand(self, cx, cy, size, kind, color, tags=()):
        ids = []
        s = size
        ow = 3
        if kind == "石头":
            ids.append(self.rrect(cx - s * 0.78, cy - s * 0.72,
                                  cx + s * 0.78, cy + s * 0.74, s * 0.5,
                                  fill=color, outline=OUTLINE, width=ow,
                                  tags=tags))
            for i in (-1, 0, 1):
                ids.append(self.c.create_oval(
                    cx + i * s * 0.42 - s * 0.16, cy - s * 0.92,
                    cx + i * s * 0.42 + s * 0.16, cy - s * 0.6,
                    fill=_mix(color, "#ffffff", 0.1), outline=OUTLINE,
                    width=ow, tags=tags))
        elif kind == "剪刀":
            for dx in (-1, 1):
                ids.append(self.capsule_ol(
                    cx + dx * s * 0.12, cy + s * 0.42,
                    cx + dx * s * 0.52, cy - s * 0.72, int(s * 0.34),
                    fill=color, tags=tags))
            ids.append(self.c.create_oval(cx - s * 0.34, cy + s * 0.34,
                                          cx + s * 0.34, cy + s * 0.82,
                                          fill=color, outline=OUTLINE,
                                          width=ow, tags=tags))
        else:
            for i in range(4):
                fx = cx - s * 0.5 + i * s * 0.34
                ids.append(self.capsule_ol(
                    fx, cy - s * 0.2, fx, cy - s * 0.86, int(s * 0.28),
                    fill=color, tags=tags))
            ids.append(self.rrect(cx - s * 0.66, cy - s * 0.34,
                                  cx + s * 0.66, cy + s * 0.78, s * 0.34,
                                  fill=color, outline=OUTLINE, width=ow,
                                  tags=tags))
        return ids

    def _clear(self, ids):
        for i in ids:
            try:
                self.c.delete(i)
            except tk.TclError:
                pass
        return []

    def _set_hand(self, who, kind, color):
        slot = self.my_slot if who == "me" else self.pet_slot
        if who == "me":
            self.my_hand_ids = self._clear(self.my_hand_ids)
            if kind:
                self.my_hand_ids = self._hand_art_big(slot[0], slot[1], kind,
                                                  color)
        else:
            self.pet_hand_ids = self._clear(self.pet_hand_ids)
            if kind:
                self.pet_hand_ids = self._hand_art_big(slot[0], slot[1], kind,
                                                   color)

    # ------------------------------------------------------------ 一局
    def play(self, hand):
        if self.done or self.busy or hand not in self.HANDS:
            return
        self.busy = True
        self._set_hand("me", hand, ACCENT_DK)
        self.c.itemconfigure(self.result, text="石头…剪刀…布！", fill=MUTED)
        self.after(60, lambda: self._reveal_round(hand))

    def _reveal_round(self, hand):
        theirs = random.choice(self.HANDS)
        self.rounds += 1
        self._set_hand("pet", theirs, INK)
        if hand == theirs:
            text, color = "都是%s，平了。" % hand, INK_SOFT
        elif (hand, theirs) in self.BEATS:
            self.you += 1
            text, color = "你%s，它%s —— 你赢这局。" % (hand, theirs), ACCENT
            self.burst(self.my_slot[0], self.my_slot[1] - 26, GOLD, 10)
        else:
            self.it += 1
            text, color = "你%s，它%s —— 它赢这局。" % (hand, theirs), INK
        self.c.itemconfigure(self.result, text=text, fill=color)
        self.c.itemconfigure(self.score_you, text=str(self.you))
        self.c.itemconfigure(self.score_it, text=str(self.it))
        self.busy = False
        if self.you >= 2 or self.it >= 2 or (self.rounds >= 3 and self.you == self.it):
            self.after(220, self._finish)
        else:
            self.after(220, lambda: self._set_hand("me", None, ACCENT_DK))

    def _finish(self):
        self.done = True
        self.again.set_enabled(True)
        st = self._stat
        if self.you > self.it:
            self.c.itemconfigure(self.result, text="你赢了！%d : %d" % (self.you, self.it),
                                 fill=ACCENT)
            st["rps_wins"] = int(st.get("rps_wins") or 0) + 1
            self.award(1)
            self.say(None, "great" if self.you >= 2 else "win")
            self.burst(self.W / 2, 200, ACCENT, 14, 60)
        elif self.you < self.it:
            self.c.itemconfigure(self.result, text="它赢了。%d : %d" % (self.you, self.it),
                                 fill=INK_SOFT)
            self.say(None, "lose")
        else:
            self.c.itemconfigure(self.result, text="平手收场。", fill=INK_SOFT)
            self.say(None, "tie")
        save_stats(self.pet)

    def reset(self):
        self.you = self.it = self.rounds = 0
        self.done = False
        self.busy = False
        self._awarded = 0
        self.again.set_enabled(False)
        self.c.itemconfigure(self.result, text="出个手势吧", fill=INK_SOFT)
        self.c.itemconfigure(self.score_you, text="0")
        self.c.itemconfigure(self.score_it, text="0")
        self._set_hand("me", None, ACCENT_DK)
        self._set_hand("pet", None, INK)


# ================================================================== 猜数字
class GuessGame(GameWindow):
    W, H = 430, 520
    TITLE = "猜数字"
    SUB = "1 ~ 100，看几次能猜到"
    ICON = "?"
    ICON_COLOR = "#4f86c6"
    HINT = "点数字键 / 直接敲键盘 · Enter 猜 · Esc 关掉"

    def build(self):
        self.target = random.randint(1, 100)
        self.lo, self.hi = 1, 100
        self.tries = 0
        self.done = False
        self.buf = ""
        self._awarded = 0
        self.history = []

        # 大数字显示
        self.card(22, 84, self.W - 22, 164, 18, fill=CARD)
        self.disp = self.txt(self.W / 2, 124, "?", 42, ACCENT, "bold")
        self.hint = self.txt(self.W / 2, 176, "在 1 ~ 100 之间", 10, INK_SOFT)

        # 范围条
        self.bar_ids = []
        self.bar_y = 200
        self.c.create_line(30, self.bar_y, self.W - 30, self.bar_y,
                           fill=OUTLINE, width=14, capstyle=tk.ROUND)
        self.c.create_line(30, self.bar_y, self.W - 30, self.bar_y,
                           fill=SHADOW, width=8, capstyle=tk.ROUND)
        self.bar = self.c.create_line(30, self.bar_y, self.W - 30, self.bar_y,
                                      fill=MINT_DK, width=8, capstyle=tk.ROUND)
        self.lo_txt = self.txt(30, self.bar_y + 15, "1", 8, INK_SOFT,
                               anchor="w")
        self.hi_txt = self.txt(self.W - 30, self.bar_y + 15, "100", 8,
                               INK_SOFT, anchor="e")

        # 记录点
        self.hist_txt = self.txt(self.W / 2, 228, "", 9, INK_SOFT)

        # 数字键盘
        keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", "猜"]
        kw, kh, gap = 100, 48, 7
        x0 = (self.W - (kw * 3 + gap * 2)) / 2.0
        self.keys = {}
        for i, k in enumerate(keys):
            r, c = divmod(i, 3)
            x = x0 + c * (kw + gap)
            y = 240 + r * (kh + gap)
            primary = (k == "猜")
            pill = Pill(self, x, y, kw, kh, k,
                        (self.submit if primary else
                         (self.backspace if k == "⌫" else
                          (lambda kk=k: self.press(kk)))),
                        fill=ACCENT if primary else CARD,
                        fg="#ffffff" if primary else INK,
                        size=15 if primary else 16, radius=16)
            self.keys[k] = pill

        self.again = Pill(self, (self.W - 104) / 2.0, self.H - 58, 104, 30,
                          "换一个数", self.reset, fill=PEACH,
                          fg=INK, size=9)
        self.again.set_enabled(False)
        for seq, fn in (("1", lambda e: self.press("1")),
                        ("2", lambda e: self.press("2")),
                        ("3", lambda e: self.press("3")),
                        ("4", lambda e: self.press("4")),
                        ("5", lambda e: self.press("5")),
                        ("6", lambda e: self.press("6")),
                        ("7", lambda e: self.press("7")),
                        ("8", lambda e: self.press("8")),
                        ("9", lambda e: self.press("9")),
                        ("0", lambda e: self.press("0")),
                        ("<BackSpace>", lambda e: self.backspace()),
                        ("<Return>", lambda e: self.submit()),
                        ("<KP_Enter>", lambda e: self.submit())):
            self.win.bind(seq, fn)

    # ------------------------------------------------------------ 输入
    def press(self, digit):
        if self.done or len(self.buf) >= 3:
            return
        if self.buf == "0":
            self.buf = ""
        self.buf += digit
        self._refresh()

    def backspace(self):
        if self.done:
            return
        self.buf = self.buf[:-1]
        self._refresh()

    def _refresh(self):
        self.c.itemconfigure(self.disp, text=self.buf or "?")

    def _range_bar(self):
        w = self.W - 60
        a = (self.lo - 1) / 99.0
        b = (self.hi - 1) / 99.0
        self.c.coords(self.bar, 30 + w * a, self.bar_y, 30 + w * b, self.bar_y)
        self.c.itemconfigure(self.lo_txt, text=str(self.lo))
        self.c.itemconfigure(self.hi_txt, text=str(self.hi))

    def submit(self):
        if self.done:
            return
        if not self.buf:
            self.c.itemconfigure(self.hint, text="先点几个数字。")
            return
        n = int(self.buf)
        if n < 1 or n > 100:
            self.c.itemconfigure(self.hint, text="超出范围了，1 ~ 100。")
            self.shake(self.disp, 5)
            self.buf = ""
            self._refresh()
            return
        self.buf = ""
        self._refresh()
        self.tries += 1
        self.history.append(n)
        if n == self.target:
            self._win()
            return
        if n < self.target:
            self.lo = max(self.lo, n + 1)
            self.c.itemconfigure(self.hint, text="%d 小了。" % n)
        else:
            self.hi = min(self.hi, n - 1)
            self.c.itemconfigure(self.hint, text="%d 大了。" % n)
        self._range_bar()
        recent = "  ".join(str(x) for x in self.history[-6:])
        self.c.itemconfigure(self.hist_txt, text=recent and ("猜过：" + recent))

    def _win(self):
        self.done = True
        self.again.set_enabled(True)
        st = self._stat
        prev = int(st.get("guess_best") or 0)
        new_best = (not prev) or self.tries < prev
        if new_best:
            st["guess_best"] = self.tries
        st["guess_plays"] = int(st.get("guess_plays") or 0) + 1
        save_stats(self.pet)
        self.c.itemconfigure(self.disp, text=str(self.target), fill=ACCENT)
        self.c.itemconfigure(self.hint,
                             text="猜对了，用了 %d 次%s" % (
                                 self.tries, "（新纪录）" if new_best else ""))
        self.burst(self.W / 2, 126, GOLD, 16, 70)
        self.award(2 if self.tries <= 5 else 1)
        self.say(None, "great" if self.tries <= 5 else "done")

    def reset(self):
        self.target = random.randint(1, 100)
        self.lo, self.hi = 1, 100
        self.tries = 0
        self.done = False
        self._awarded = 0
        self.buf = ""
        self.history = []
        self._refresh()
        self.c.itemconfigure(self.disp, text="?", fill=INK)
        self.c.itemconfigure(self.hint, text="在 1 ~ 100 之间")
        self.c.itemconfigure(self.hist_txt, text="")
        self.again.set_enabled(False)
        self._range_bar()


# ================================================================== 翻牌记忆
class MemoryGame(GameWindow):
    W, H = 450, 486
    TITLE = "翻牌记忆"
    SUB = "六对图案，翻到一样的就配对"
    ICON = "♥"
    ICON_COLOR = "#7b5aa6"
    HINT = "点牌翻开 · 步数越少越好 · Esc 关掉"
    SYMBOLS = ("♠", "♥", "♦", "♣", "★", "●")
    COLS, ROWS = 4, 3
    CW, CH, GAP = 92, 92, 10

    def build(self):
        self.moves = 0
        self.done = False
        self._awarded = 0
        self.first = None
        self.locked = False
        self.flips = {}              # idx -> {"t": 进度, "open": bool}

        self.status = self.txt(self.W / 2, 96, "点一张牌开始", 10, INK_SOFT)
        self.symbols = []
        self.cards = {}
        self._deal()

        self.again = Pill(self, (self.W - 132) / 2.0, self.H - 58, 132, 30,
                          "重新洗牌", self.reset, fill=PEACH,
                          fg=INK, size=10)
        self.again.set_enabled(False)

    def _deal(self):
        symbols = list(self.SYMBOLS) * 2
        random.shuffle(symbols)
        self.symbols = symbols
        self.matched = set()
        self.flips = {i: {"t": 0.0, "open": False} for i in range(len(symbols))}
        grid_w = self.COLS * self.CW + (self.COLS - 1) * self.GAP
        x0 = (self.W - grid_w) / 2.0
        y0 = 116
        for i in range(len(symbols)):
            r, c = divmod(i, self.COLS)
            x = x0 + c * (self.CW + self.GAP)
            y = y0 + r * (self.CH + self.GAP)
            self.cards[i] = (x, y)
            self._draw_card(i)

    def _draw_card(self, i):
        x, y = self.cards[i]
        tag = "card%d" % i
        self.c.delete(tag)
        f = self.flips[i]
        t = f["t"]
        # 翻牌：宽度先压扁再展开，翻到一半换面
        k = abs(math.cos(math.pi * t))
        w = self.CW * (0.08 + 0.92 * k)
        cx = x + self.CW / 2.0
        matched = i in self.matched
        if t < 0.5:
            fill = "#8f7ae0" if not matched else "#cbbcff"
            self.card(cx - w / 2, y, cx + w / 2, y + self.CH, 16, fill=fill,
                      shadow=False, tags=(tag,))
            if w > self.CW * 0.4:
                self.txt(cx, y + self.CH / 2 - 2, "✦", 17, "#ffffff",
                         tags=(tag,))
                for dx in (-24, 24):
                    self.c.create_oval(cx + dx - 3, y + self.CH - 22,
                                       cx + dx + 3, y + self.CH - 16,
                                       fill="#ffffff", outline="", tags=(tag,))
        else:
            sym = self.symbols[i]
            fill = MINT if matched else CARD
            self.card(cx - w / 2, y, cx + w / 2, y + self.CH, 16, fill=fill,
                      shadow=not matched, tags=(tag,))
            if w > self.CW * 0.4:
                img = emoji_image(self.win, SYMBOL_FILES.get(sym, ""), 52)
                if img is not None:
                    self.c.create_image(cx, y + self.CH / 2, image=img,
                                        tags=(tag,))
                else:
                    color = MINT_DK if matched else ACCENT
                    self.txt(cx, y + self.CH / 2, sym, 28, color, "bold",
                             tags=(tag,))
        self.c.tag_bind(tag, "<Button-1>", lambda e, ii=i: self.flip(ii))


    def flip(self, idx):
        if self.done or self.locked or idx in self.matched:
            return
        f = self.flips[idx]
        if f["open"] and f["t"] >= 1.0:
            return
        if f["open"]:
            return
        f["open"] = True
        self._animate(idx)
        if self.first is None:
            self.first = idx
            self.c.itemconfigure(self.status, text="再翻一张")
            return
        a, b = self.first, idx
        self.first = None
        self.moves += 1
        if self.symbols[a] == self.symbols[b]:
            self.matched.update((a, b))
            self.after(300, lambda: self._pop_pair(a, b))
            self.c.itemconfigure(self.status, text="配上了（%d 步）" % self.moves)
            if len(self.matched) == len(self.symbols):
                self.after(420, self._finish)
            return
        self.locked = True
        self.c.itemconfigure(self.status, text="不一样，翻回去…")
        self.after(760, lambda: self._hide(a, b))

    def _animate(self, idx):
        f = self.flips[idx]
        if f["t"] >= 1.0:
            return
        f["t"] = min(1.0, f["t"] + 0.18)
        self._draw_card(idx)
        if f["t"] < 1.0:
            self.after(16, lambda: self._animate(idx))

    def _pop_pair(self, a, b):
        for idx in (a, b):
            f = self.flips[idx]
            f["t"] = 1.0
            self._draw_card(idx)
        self.burst(self.cards[a][0] + self.CW / 2.0,
                   self.cards[a][1] + self.CH / 2.0, MINT_DK, 6, 26)

    def _hide(self, a, b):
        for idx in (a, b):
            if idx in self.matched:
                continue
            self.flips[idx]["open"] = False
            self.flips[idx]["t"] = 0.0
            self._draw_card(idx)
        self.locked = False
        self.c.itemconfigure(self.status,
                             text="再试试（已翻 %d 步）" % self.moves)

    def _finish(self):
        self.done = True
        self.again.set_enabled(True)
        st = self._stat
        prev = int(st.get("memory_best") or 0)
        new_best = (not prev) or self.moves < prev
        if new_best:
            st["memory_best"] = self.moves
        st["memory_plays"] = int(st.get("memory_plays") or 0) + 1
        save_stats(self.pet)
        self.c.itemconfigure(
            self.status, fill=ACCENT,
            text="全配上了！%d 步%s" % (self.moves,
                                      "（新纪录）" if new_best else ""))
        self.burst(self.W / 2, 200, GOLD, 18, 90)
        self.award(2 if self.moves <= 10 else 1)
        self.say(None, "great" if self.moves <= 10 else "done")

    def reset(self):
        self.moves = 0
        self.done = False
        self._awarded = 0
        self.first = None
        self.locked = False
        for i in list(self.cards):
            self.c.delete("card%d" % i)
        self._deal()
        self.c.itemconfigure(self.status, text="点一张牌开始", fill=INK_SOFT)
        self.again.set_enabled(False)


# ================================================================== 打地鼠
class MoleGame(GameWindow):
    W, H = 450, 470
    TITLE = "打地鼠"
    SUB = "30 秒，冒头就点"
    ICON = "◎"
    ICON_COLOR = "#5f9e6e"
    HINT = "点洞里冒头的地鼠 · 15 分以上算赢 · Esc 关掉"
    SECONDS = 30.0
    RISE = 34.0              # 地鼠从洞里升起的像素

    def build(self):
        self.score = 0
        self.done = False
        self._awarded = 0
        self.time_left = self.SECONDS
        self.moles = []
        self.holes = []
        self._spawn_acc = 0.0

        # 顶部计分 + 时间条
        self.score_txt = self.txt(28, 96, "得分 0", 12, INK, "bold",
                                  anchor="w")
        self.time_txt = self.txt(self.W - 26, 96, "30 秒", 10, INK_SOFT,
                                 anchor="e")
        self.c.create_line(26, 114, self.W - 26, 114, fill=OUTLINE, width=14,
                           capstyle=tk.ROUND)
        self.c.create_line(26, 114, self.W - 26, 114, fill=SHADOW, width=8,
                           capstyle=tk.ROUND)
        self.tbar = self.c.create_line(26, 114, self.W - 26, 114,
                                       fill=GOLD, width=8, capstyle=tk.ROUND)

        # 草地 + 九个洞
        self.rrect(20, 132, self.W - 20, self.H - 78, 22, fill=FIELD,
                   outline=OUTLINE, width=3)
        for i in range(0, 5):
            gx = 52 + i * 88
            self.c.create_polygon(gx - 7, 136, gx, 124, gx + 7, 136,
                                  fill=MINT_DK, outline=OUTLINE, width=2)
        for i in range(9):
            r, c = divmod(i, 3)
            cx = 95 + c * 130
            cy = 204 + r * 80
            self.c.create_oval(cx - 54, cy - 20, cx + 54, cy + 28,
                               fill=_mix(DIRT, "#ffffff", 0.25), outline="")
            self.c.create_oval(cx - 50, cy - 17, cx + 50, cy + 24,
                               fill=DIRT_DK, outline=OUTLINE, width=3)
            self.c.create_oval(cx - 45, cy - 13, cx + 45, cy + 20,
                               fill="#3a2a22", outline="")
            self.holes.append((cx, cy))
        self.c.tag_bind("all", "<Button-1>", self._on_click, add="+")

        self.again = Pill(self, (self.W - 132) / 2.0, self.H - 58, 132, 30,
                          "再来一局", self.reset, fill=PEACH,
                          fg=INK, size=10)
        self.again.set_enabled(False)

    # ------------------------------------------------------------ 画地鼠
    def _draw_mole(self, cx, cy):
        """地鼠 + 盖住洞口的一层，出洞时只露上半截。"""
        ids = []
        ow = 3
        ids.append(self.c.create_oval(cx - 30, cy - 30, cx + 30, cy + 32,
                                      fill=BODY, outline=OUTLINE, width=ow))
        for dx in (-26, 26):
            ids.append(self.c.create_oval(cx + dx - 10, cy - 35,
                                          cx + dx + 10, cy - 13,
                                          fill=_mix(BODY, "#5a3a2a", 0.22),
                                          outline=OUTLINE, width=ow))
        ids.append(self.c.create_oval(cx - 18, cy - 8, cx + 18, cy + 28,
                                      fill=_mix(BODY, "#ffe9d6", 0.34),
                                      outline=""))
        for dx in (-11, 11):
            ids.append(self.c.create_oval(cx + dx - 4, cy - 11, cx + dx + 4,
                                          cy - 1, fill="#2f2620", outline=""))
            ids.append(self.c.create_oval(cx + dx - 2, cy - 9, cx + dx + 2,
                                          cy - 5, fill="#ffffff", outline=""))
        ids.append(self.c.create_oval(cx - 6, cy + 3, cx + 6, cy + 13,
                                      fill="#e8607a", outline=OUTLINE, width=2))
        # 遮罩只盖住洞口里面那圈，外面的土沿还留着
        mask = self.c.create_oval(cx - 45, cy - 13, cx + 45, cy + 20,
                                  fill="#3a2a22", outline="")
        return ids, (mask,)

    def _remove(self, mole):
        for i in list(mole.get("ids", [])) + list(mole.get("mask", [])):
            try:
                self.c.delete(i)
            except tk.TclError:
                pass
        if mole in self.moles:
            self.moles.remove(mole)

    # ------------------------------------------------------------ 点击
    def _on_click(self, e):
        if self.done:
            return
        for mole in list(self.moles):
            if mole["hit"] or mole["rise"] < 0.5:
                continue
            cx, cy = mole["cx"], mole["cy"] - mole["rise"] * self.RISE
            if abs(e.x - cx) < 42 and (cy - 40) < e.y < (cy + 20):
                self._hit(mole)
                return
        self.click_ring(e.x, e.y, PEACH_DK)

    def _hit(self, mole):
        mole["hit"] = True
        self.score += 1
        self.c.itemconfigure(self.score_txt, text="得分 %d" % self.score)
        cx, cy = mole["cx"], mole["cy"] - mole["rise"] * self.RISE
        self.float_text(cx, cy - 46, "+1", ACCENT, 14)
        self.burst(cx, cy - 14, GOLD, 8, 30)
        mole["life"] = 0.0
        # 被打中的一秒内缩回洞里
        mole["hit_down"] = True

    # ------------------------------------------------------------ 出洞
    def _spawn(self, hole):
        cx, cy = self.holes[hole]
        ids, mask = self._draw_mole(cx, cy)
        self.moles.append({"hole": hole, "rise": 0.0, "hit": False,
                           "ids": ids, "mask": mask, "cx": cx, "cy": cy,
                           "life": 0.0, "dy": 0.0})

    def _free_holes(self):
        used = {m["hole"] for m in self.moles}
        return [i for i in range(9) if i not in used]

    # ------------------------------------------------------------ 每帧
    def tick(self, dt, now):
        if self.done:
            return
        self.time_left -= dt
        if self.time_left <= 0:
            self.time_left = 0.0
            self._finish()
            return
        frac = max(0.0, self.time_left / self.SECONDS)
        self.c.coords(self.tbar, 26, 114, 26 + (self.W - 52) * frac, 114)
        self.c.itemconfigure(
            self.time_txt, text="%d 秒" % int(math.ceil(self.time_left)))

        self._spawn_acc += dt
        gap = 0.62 if self.time_left > 8 else 0.46
        if self._spawn_acc >= gap:
            free = self._free_holes()
            if free and len(self.moles) < 3:
                self._spawn_acc = 0.0
                self._spawn(random.choice(free))

        for mole in list(self.moles):
            mole["life"] += dt
            if mole["hit"]:
                target = 0.0
                speed = 6.0
            elif mole["life"] < 1.05:
                target = 1.0
                speed = 7.0
            else:
                target = 0.0
                speed = 5.0
            if mole["rise"] < target:
                mole["rise"] = min(target, mole["rise"] + dt * speed)
            elif mole["rise"] > target:
                mole["rise"] = max(target, mole["rise"] - dt * speed)
            want = mole["rise"] * self.RISE
            delta = mole["dy"] - want
            if abs(delta) > 0.02:
                for i in mole["ids"]:
                    try:
                        self.c.move(i, 0, delta)
                    except tk.TclError:
                        pass
                mole["dy"] = want
            if mole["hit"] and mole["rise"] <= 0.01:
                self._remove(mole)

    def _finish(self):
        self.done = True
        for mole in list(self.moles):
            self._remove(mole)
        self.again.set_enabled(True)
        st = self._stat
        prev = int(st.get("mole_best") or 0)
        new_best = self.score > prev
        if new_best:
            st["mole_best"] = self.score
        st["mole_plays"] = int(st.get("mole_plays") or 0) + 1
        save_stats(self.pet)
        won = self.score >= 15
        if won:
            self.c.itemconfigure(
                self.score_txt, fill=ACCENT,
                text="得分 %d · %s" % (self.score,
                                      "新纪录" if new_best else "达标"))
            self.award(2)
            self.burst(self.W / 2, 150, GOLD, 16, 70)
        else:
            self.c.itemconfigure(self.score_txt, fill=INK_SOFT,
                                 text="得分 %d" % self.score)
            self.award(1)
        self.say(None, "great" if won else "done")

    def reset(self):
        for mole in list(self.moles):
            self._remove(mole)
        self.score = 0
        self.done = False
        self._awarded = 0
        self.time_left = self.SECONDS
        self._spawn_acc = 0.0
        self.c.itemconfigure(self.score_txt, text="得分 0", fill=INK)
        self.c.itemconfigure(self.time_txt, text="30 秒")
        self.c.coords(self.tbar, 26, 114, self.W - 26, 114)
        self.again.set_enabled(False)


GAMES = {
    "rps": ("猜拳", RPSGame),
    "guess": ("猜数字", GuessGame),
    "memory": ("翻牌记忆", MemoryGame),
    "mole": ("打地鼠", MoleGame),
}

_OPEN = {}


def open_game(pet, key):
    entry = GAMES.get(key)
    if entry is None:
        return None
    cls = entry[1]
    win = _OPEN.get(id(pet))
    if win is not None:
        try:
            if win.win is not None and win.win.winfo_exists():
                if win.key == key:
                    win.win.lift()
                    return win
                win.close()
        except Exception:                        # noqa: BLE001
            pass
    game = cls(pet, key)
    try:
        game.show()
    except Exception:                            # noqa: BLE001
        _OPEN.pop(id(pet), None)
        raise
    _OPEN[id(pet)] = game
    return game
