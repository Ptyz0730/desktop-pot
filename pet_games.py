# -*- coding: utf-8 -*-
"""桌宠小游戏（右键 → 小游戏）。

四个都是点着玩、几秒钟一局的小东西，适合挂在桌宠旁边：

* 猜拳     —— 三局两胜，它自己出手势
* 猜数字   —— 1~100，看几次能猜到
* 翻牌记忆 —— 4x3 十二张牌，六对图案
* 打地鼠   —— 30 秒，九宫格里冒头就点

每个窗口都贴着宠物放（上面放不下就挪到下面），Esc 关掉；玩完它会在气泡
里点评一句，好感度给一点点（每局只给一次）。
"""
import random
import time
import tkinter as tk

FONT_FAMILY = "Microsoft YaHei UI"

BG = "#fffdfd"
CARD = "#ffffff"
RED = "#b3242a"
RED_DARK = "#8a1a1f"
RED_LIGHT = "#f6dfe0"
INK = "#332a2c"
MUTED = "#9b8d8f"
GOLD = "#b8842c"
BORDER = "#d9b3b5"


def _work_area(root):
    """复用 desktop_pet 的 work_area；万一没导入成功就退回整个屏幕。"""
    try:
        import desktop_pet
        return desktop_pet.work_area(root)
    except Exception:                            # noqa: BLE001
        return (0, 0, root.winfo_screenwidth(), root.winfo_screenheight())


def stats_of(pet):
    """每个小游戏的成绩存在 pet_config.json 的 games 里。"""
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


# 玩完之后它说的话。没有这个形象就退回「话痨朋友」那套。
LINES = {
    "闷骚少年": {
        "win": "基操勿六。",
        "lose": "……再来。",
        "tie": "平了，接着来。",
        "done": "还行吧。",
        "great": "手气不错嘛。",
    },
    "骚话少年": {
        "win": "バカ，我赢了。",
        "lose": "もう一回，再来一次。",
        "tie": "同点。気持ちいい。",
        "done": "気持ちいい…我是说这局。",
        "great": "君だけだよ，你最厉害。",
    },
    "话痨朋友": {
        "win": "我厉害吧！",
        "lose": "哎呀，再来再来！",
        "tie": "平手，接着来！",
        "done": "玩得不错！",
        "great": "你也太强了吧！",
    },
}


class GameWindow:
    """小游戏窗口的壳：标题条、成绩行、关闭按钮、贴边摆放。"""

    W, H = 380, 340
    TITLE = "小游戏"
    SUB = ""
    HINT = "Esc 关掉"

    def __init__(self, pet, key):
        self.pet = pet
        self.key = key
        self.win = None
        self.body = None
        self._jobs = []
        self._awarded = 0
        self._stat = stats_of(pet)

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
        try:
            import ai_client
            who = ai_client.persona_display_name(
                getattr(self.pet, "_persona", ""))
        except Exception:                        # noqa: BLE001
            who = "桌宠"
        self.win.title("%s · %s" % (self.TITLE, who))
        self.win.configure(bg=BG)
        self.win.resizable(False, False)
        self.win.attributes("-topmost", True)
        self.win.geometry("%dx%d" % (self.W, self.H))
        try:
            self.win.tk.call("wm", "minsize", str(self.win), self.W, self.H)
            self.win.tk.call("wm", "maxsize", str(self.win), self.W, self.H)
        except tk.TclError:
            pass
        self._build_head()
        self.body = tk.Frame(self.win, bg=BG)
        self.body.place(x=0, y=58, width=self.W, height=self.H - 58 - 26)
        self.build()
        tk.Label(self.win, text=self.HINT, bg=BG, fg=MUTED,
                 font=(FONT_FAMILY, 8), anchor="w").place(
            x=14, y=self.H - 24, width=self.W - 120, height=18)
        self.win.bind("<Escape>", lambda e: self.close())
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self._place()
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()
        return self

    def _build_head(self):
        head = tk.Frame(self.win, bg=BG)
        head.place(x=0, y=0, width=self.W, height=58)
        tk.Label(head, text=self.TITLE, bg=BG, fg=RED_DARK,
                 font=(FONT_FAMILY, 13, "bold"), anchor="w").place(
            x=14, y=9, width=self.W - 90, height=26)
        self.sub_var = tk.StringVar(value=self.SUB or self.HINT)
        tk.Label(head, textvariable=self.sub_var, bg=BG, fg=MUTED,
                 font=(FONT_FAMILY, 9), anchor="w").place(
            x=14, y=35, width=self.W - 90, height=17)
        close = tk.Label(head, text="✕", bg=BG, fg=MUTED,
                         font=(FONT_FAMILY, 12), cursor="hand2")
        close.place(x=self.W - 40, y=12, width=26, height=26)
        close.bind("<Button-1>", lambda e: self.close())
        close.bind("<Enter>", lambda e: close.configure(fg=RED))
        close.bind("<Leave>", lambda e: close.configure(fg=MUTED))
        tk.Frame(self.win, bg=RED, height=2).place(
            x=0, y=56, width=self.W, height=2)

    def _place(self):
        root = self.pet.root
        left, top, right, bottom = _work_area(root)
        ax = self.pet.win_x + self.pet.win_w // 2
        x = int(min(max(left + 8, ax - self.W // 2), right - self.W - 8))
        y = int(self.pet.win_y - self.H - 30)
        if y < top + 8:
            y = int(self.pet.win_y + self.pet.win_h + 8)
            if y + self.H > bottom - 8:
                y = max(top + 8, bottom - self.H - 8)
        self.win.geometry("%dx%d+%d+%d" % (self.W, self.H, x, y))

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
        if self.win is not None and self.win.winfo_exists():
            try:
                self.win.destroy()
            except tk.TclError:
                pass
        self.win = None

    # ---------------------------------------------------------------- 小工具
    def after(self, ms, fn):
        job = self.win.after(ms, fn)
        self._jobs.append(job)
        return job

    def line(self, kind):
        name = getattr(self.pet, "_persona", "") or ""
        table = LINES.get(name) or LINES["话痨朋友"]
        return table.get(kind) or LINES["话痨朋友"].get(kind, "")

    def say(self, text, kind=None):
        """气泡里说一句；kind 是 LINES 的键。"""
        if kind:
            text = self.line(kind)
        if not text:
            return
        try:
            self.pet.speak(text)
        except Exception:                        # noqa: BLE001
            pass

    def award(self, delta):
        """好感度加一点，一局只加一次。"""
        if self._awarded or not delta:
            return
        self._awarded = delta
        try:
            self.pet._apply_affection(delta)
        except Exception:                        # noqa: BLE001
            pass

    def btn(self, parent, text, command, width=92, height=38,
            fg=None, bg=None, font_size=11):
        b = tk.Button(parent, text=text, command=command,
                      bg=bg or CARD, fg=fg or RED_DARK,
                      activebackground=RED_LIGHT, activeforeground=RED_DARK,
                      relief="solid", bd=1, highlightthickness=0,
                      font=(FONT_FAMILY, font_size), cursor="hand2")
        b.place(width=width, height=height)
        return b

    def card(self, parent, x, y, w, h, text="", fg=None, bg=None,
             font_size=18, bold=False):
        lab = tk.Label(parent, text=text, bg=bg or CARD, fg=fg or INK,
                       font=(FONT_FAMILY, font_size, "bold" if bold else "normal"),
                       bd=1, relief="solid", highlightthickness=0)
        lab.place(x=x, y=y, width=w, height=h)
        return lab

    # 子类实现
    def build(self):
        raise NotImplementedError

    def on_close(self):
        pass


# ------------------------------------------------------------------ 猜拳
class RPSGame(GameWindow):
    W, H = 400, 330
    TITLE = "猜拳"
    SUB = "三局两胜，谁先赢两把"
    HINT = "Esc 关掉 · 每局只加一次好感"
    HANDS = ("石头", "剪刀", "布")
    # 谁赢谁：(我出手, 它出手)
    BEATS = {("石头", "剪刀"), ("剪刀", "布"), ("布", "石头")}

    def build(self):
        self.you = 0
        self.it = 0
        self.rounds = 0
        self.done = False
        self._awarded = 0

        self.score_var = tk.StringVar()
        tk.Label(self.body, textvariable=self.score_var, bg=BG, fg=RED_DARK,
                 font=(FONT_FAMILY, 13, "bold")).place(
            x=0, y=6, width=self.W, height=28)

        self.show_var = tk.StringVar(value="出个手势吧")
        tk.Label(self.body, textvariable=self.show_var, bg=BG, fg=INK,
                 font=(FONT_FAMILY, 12)).place(
            x=20, y=44, width=self.W - 40, height=54)

        hand_w = 96
        gap = 16
        x0 = (self.W - (hand_w * 3 + gap * 2)) // 2
        for i, hand in enumerate(self.HANDS):
            b = self.btn(self.body, hand, lambda h=hand: self.play(h),
                         width=hand_w, height=42, font_size=12)
            b.place(x=x0 + i * (hand_w + gap), y=112)

        self.again = self.btn(self.body, "再来一局", self.reset,
                              width=130, height=36)
        self.again.place(x=(self.W - 130) // 2, y=176)
        self.again.configure(state="disabled")
        self._refresh()

    def _refresh(self):
        self.score_var.set("你 %d : %d 它" % (self.you, self.it))

    def play(self, mine):
        if self.done:
            return
        theirs = random.choice(self.HANDS)
        self.rounds += 1
        if mine == theirs:
            text = "都是 %s，平了。" % mine
        elif (mine, theirs) in self.BEATS:
            self.you += 1
            text = "你 %s，它 %s —— 你赢了这局。" % (mine, theirs)
        else:
            self.it += 1
            text = "你 %s，它 %s —— 它赢了这局。" % (mine, theirs)
        self.show_var.set(text)
        self._refresh()
        if self.you >= 2 or self.it >= 2:
            self._finish()
        elif self.rounds >= 3 and self.you == self.it:
            self._finish()

    def _finish(self):
        self.done = True
        self.again.configure(state="normal")
        st = self._stat
        if self.you > self.it:
            self.show_var.set("你赢了！%d : %d" % (self.you, self.it))
            st["rps_wins"] = int(st.get("rps_wins") or 0) + 1
            self.award(1)
            self.say(None, "great" if self.you >= 2 else "win")
        elif self.you < self.it:
            self.show_var.set("它赢了。%d : %d" % (self.you, self.it))
            self.say(None, "lose")
        else:
            self.show_var.set("平手收场。")
            self.say(None, "tie")
        save_stats(self.pet)

    def reset(self):
        self.you = self.it = self.rounds = 0
        self.done = False
        self._awarded = 0
        self.again.configure(state="disabled")
        self.show_var.set("出个手势吧")
        self._refresh()


# ------------------------------------------------------------------ 猜数字
class GuessGame(GameWindow):
    W, H = 400, 300
    TITLE = "猜数字"
    SUB = "1 ~ 100 之间，看几次能猜到"
    HINT = "Esc 关掉 · Enter 也能猜"

    def build(self):
        self.target = random.randint(1, 100)
        self.lo, self.hi = 1, 100
        self.tries = 0
        self.done = False
        self._awarded = 0

        self.tip_var = tk.StringVar(value="在 1 ~ 100 之间")
        tk.Label(self.body, textvariable=self.tip_var, bg=BG, fg=INK,
                 font=(FONT_FAMILY, 12)).place(
            x=16, y=14, width=self.W - 32, height=40)

        self.entry = tk.Entry(self.body, bg=CARD, fg=INK, relief="flat",
                              highlightthickness=1, highlightbackground=BORDER,
                              highlightcolor=RED, font=(FONT_FAMILY, 14),
                              justify="center")
        self.entry.place(x=(self.W - 150) // 2, y=76, width=150, height=40)
        self.entry.bind("<Return>", lambda e: self.guess())
        self.entry.bind("<KP_Enter>", lambda e: self.guess())

        self.guess_btn = self.btn(self.body, "猜", self.guess,
                                  width=92, height=40, font_size=12)
        self.guess_btn.place(x=self.W // 2 + 30, y=76)

        self.state_var = tk.StringVar(value="")
        tk.Label(self.body, textvariable=self.state_var, bg=BG, fg=RED_DARK,
                 font=(FONT_FAMILY, 10)).place(
            x=16, y=128, width=self.W - 32, height=22)

        self.again = self.btn(self.body, "换一个数", self.reset,
                              width=130, height=36)
        self.again.place(x=(self.W - 130) // 2, y=162)
        self.again.configure(state="disabled")
        self.after(60, lambda: self.entry.focus_force())

    def guess(self):
        if self.done:
            return
        raw = self.entry.get().strip()
        self.entry.delete(0, "end")
        try:
            n = int(raw)
        except ValueError:
            self.state_var.set("填个 1~100 的整数。")
            return
        if n < 1 or n > 100:
            self.state_var.set("超出范围了，1~100。")
            return
        self.tries += 1
        if n == self.target:
            self.done = True
            self.again.configure(state="normal")
            prev = int(self._stat.get("guess_best") or 0)
            new_best = (not prev) or self.tries < prev
            if new_best:
                self._stat["guess_best"] = self.tries
            st = self._stat
            st["guess_plays"] = int(st.get("guess_plays") or 0) + 1
            save_stats(self.pet)
            self.tip_var.set("猜对了！就是 %d。" % self.target)
            self.state_var.set("用了 %d 次%s" % (
                self.tries, "（新纪录）" if new_best else ""))
            self.award(2 if self.tries <= 5 else 1)
            self.say(None, "great" if self.tries <= 5 else "done")
            return
        if n < self.target:
            self.lo = max(self.lo, n + 1)
            self.state_var.set("%d 小了。" % n)
        else:
            self.hi = min(self.hi, n - 1)
            self.state_var.set("%d 大了。" % n)
        self.tip_var.set("现在大概在 %d ~ %d 之间" % (self.lo, self.hi))

    def reset(self):
        self.target = random.randint(1, 100)
        self.lo, self.hi = 1, 100
        self.tries = 0
        self.done = False
        self._awarded = 0
        self.tip_var.set("在 1 ~ 100 之间")
        self.state_var.set("")
        self.again.configure(state="disabled")
        self.entry.delete(0, "end")
        self.entry.focus_force()


# ------------------------------------------------------------------ 翻牌记忆
class MemoryGame(GameWindow):
    W, H = 400, 420
    TITLE = "翻牌记忆"
    SUB = "六对图案，翻到一样的就配对"
    HINT = "Esc 关掉 · 步数越少越好"
    SYMBOLS = ("♠", "♥", "♦", "♣", "★", "●")
    COLS, ROWS = 4, 3
    CW, CH = 76, 76

    def build(self):
        self.moves = 0
        self.done = False
        self._awarded = 0
        self.first = None
        self.locked = False

        self.tip_var = tk.StringVar(value="点一张牌开始")
        tk.Label(self.body, textvariable=self.tip_var, bg=BG, fg=INK,
                 font=(FONT_FAMILY, 11)).place(
            x=16, y=4, width=self.W - 32, height=24)

        symbols = list(self.SYMBOLS) * 2
        random.shuffle(symbols)
        self.symbols = symbols
        self.cards = []
        self.revealed = set()
        self.matched = set()
        grid_w = self.COLS * self.CW + (self.COLS - 1) * 10
        x0 = (self.W - grid_w) // 2
        for i, sym in enumerate(symbols):
            r, c = divmod(i, self.COLS)
            x = x0 + c * (self.CW + 10)
            y = 36 + r * (self.CH + 10)
            lab = self.card(self.body, x, y, self.CW, self.CH, "", font_size=24)
            lab.configure(cursor="hand2")
            lab.bind("<Button-1>", lambda e, idx=i: self.flip(idx))
            self.cards.append(lab)

        self.again = self.btn(self.body, "重新洗牌", self.reset,
                              width=130, height=34, font_size=10)
        self.again.place(x=(self.W - 130) // 2, y=36 + 3 * (self.CH + 10) + 4)
        self.again.configure(state="disabled")

    def flip(self, idx):
        if self.done or self.locked or idx in self.revealed or idx in self.matched:
            return
        self.revealed.add(idx)
        self.cards[idx].configure(text=self.symbols[idx], fg=RED_DARK,
                                  bg=RED_LIGHT)
        if self.first is None:
            self.first = idx
            self.tip_var.set("再翻一张")
            return
        a, b = self.first, idx
        self.first = None
        self.moves += 1
        if self.symbols[a] == self.symbols[b]:
            self.matched.update((a, b))
            self.revealed.discard(a)
            self.revealed.discard(b)
            self.cards[a].configure(bg=CARD, fg=GOLD)
            self.cards[b].configure(bg=CARD, fg=GOLD)
            self.tip_var.set("配上了（%d 步）" % self.moves)
            if len(self.matched) == len(self.symbols):
                self._finish()
            return
        self.locked = True
        self.tip_var.set("不一样，翻回去…")
        self.after(620, lambda: self._hide(a, b))

    def _hide(self, a, b):
        for idx in (a, b):
            if idx in self.matched:
                continue
            self.revealed.discard(idx)
            if self.cards[idx].winfo_exists():
                self.cards[idx].configure(text="", bg=CARD)
        self.locked = False
        self.tip_var.set("再试试（已翻 %d 步）" % self.moves)

    def _finish(self):
        self.done = True
        self.again.configure(state="normal")
        st = self._stat
        prev = int(st.get("memory_best") or 0)
        new_best = (not prev) or self.moves < prev
        if new_best:
            st["memory_best"] = self.moves
        st["memory_plays"] = int(st.get("memory_plays") or 0) + 1
        save_stats(self.pet)
        self.tip_var.set("全配上了！用了 %d 步%s" % (
            self.moves, "（新纪录）" if new_best else ""))
        self.award(2 if self.moves <= 10 else 1)
        self.say(None, "great" if self.moves <= 10 else "done")

    def reset(self):
        self.moves = 0
        self.done = False
        self._awarded = 0
        self.first = None
        self.locked = False
        symbols = list(self.SYMBOLS) * 2
        random.shuffle(symbols)
        self.symbols = symbols
        self.revealed.clear()
        self.matched.clear()
        for lab in self.cards:
            try:
                lab.configure(text="", bg=CARD, fg=INK)
            except tk.TclError:
                pass
        self.again.configure(state="disabled")
        self.tip_var.set("点一张牌开始")


# ------------------------------------------------------------------ 打地鼠
class MoleGame(GameWindow):
    W, H = 420, 420
    TITLE = "打地鼠"
    SUB = "30 秒，冒头就点"
    HINT = "Esc 关掉 · 点中 +1"
    HOLES = 9
    SECONDS = 30.0

    def build(self):
        self.score = 0
        self.hits = 0
        self.done = False
        self._awarded = 0
        self.mole = None
        self.left = self.SECONDS

        self.head_var = tk.StringVar()
        tk.Label(self.body, textvariable=self.head_var, bg=BG, fg=RED_DARK,
                 font=(FONT_FAMILY, 12, "bold")).place(
            x=16, y=2, width=self.W - 32, height=26)

        size = 360
        self.canvas = tk.Canvas(self.body, width=size, height=270, bg=BG,
                                highlightthickness=0, bd=0)
        self.canvas.place(x=(self.W - size) // 2, y=30)
        self.canvas.bind("<Button-1>", self.on_click)
        self.cell = size // 3
        self.holes = []
        for i in range(self.HOLES):
            r, c = divmod(i, 3)
            cx = c * self.cell + self.cell // 2
            cy = r * 84 + 58
            self.canvas.create_oval(cx - 44, cy - 20, cx + 44, cy + 22,
                                    fill="#2b2b33", outline="")
            self.canvas.create_oval(cx - 38, cy - 16, cx + 38, cy + 16,
                                    fill="#3a3a46", outline="")
            self.holes.append((cx, cy))

        self.again = self.btn(self.body, "再来一局", self.reset,
                              width=130, height=32, font_size=10)
        self.again.place(x=(self.W - 130) // 2, y=300)
        self.again.configure(state="disabled")
        self._refresh()
        self._tick()

    def _refresh(self):
        self.head_var.set("得分 %d · 还剩 %d 秒" % (self.score, max(0, int(self.left))))

    def _tick(self):
        if self.done:
            return
        self.left -= 0.25
        if self.left <= 0:
            self._finish()
            return
        if self.mole is None and random.random() < 0.55:
            self._pop()
        if self.mole is not None:
            self._hide_in = getattr(self, "_hide_in", 0) - 0.25
            if self._hide_in <= 0:
                self._drop_mole()
        self._refresh()
        self.after(250, self._tick)

    def _pop(self):
        idx = random.randrange(self.HOLES)
        cx, cy = self.holes[idx]
        body = self.canvas.create_oval(cx - 26, cy - 26, cx + 26, cy + 22,
                                       fill="#8a5a3b", outline="#5c3a24")
        eye1 = self.canvas.create_oval(cx - 13, cy - 10, cx - 5, cy - 2,
                                       fill="#20160f", outline="")
        eye2 = self.canvas.create_oval(cx + 5, cy - 10, cx + 13, cy - 2,
                                       fill="#20160f", outline="")
        nose = self.canvas.create_oval(cx - 4, cy + 2, cx + 4, cy + 9,
                                       fill="#e8b4a0", outline="")
        self.mole = (idx, body, eye1, eye2, nose)
        self._hide_in = random.uniform(0.55, 0.95)

    def _drop_mole(self):
        if self.mole is None:
            return
        for item in self.mole[1:]:
            try:
                self.canvas.delete(item)
            except tk.TclError:
                pass
        self.mole = None

    def on_click(self, event):
        if self.done or self.mole is None:
            return
        idx = self.mole[0]
        cx, cy = self.holes[idx]
        if (event.x - cx) ** 2 + (event.y - cy) ** 2 > 40 ** 2:
            return
        self._drop_mole()
        self.score += 1
        self.hits += 1
        self._refresh()

    def _finish(self):
        self.done = True
        self._drop_mole()
        if self.score >= 15:
            self.head_var.set("时间到！%d 分 —— 手速可以。" % self.score)
            self.award(2)
            self.say(None, "great")
        else:
            self.head_var.set("时间到，%d 分。再来一局？" % self.score)
            self.award(1)
            self.say(None, "done")
        st = self._stat
        best = int(st.get("mole_best") or 0)
        if self.score > best:
            st["mole_best"] = self.score
            self.head_var.set(self.head_var.get() + "（新纪录）")
        save_stats(self.pet)
        self.again.configure(state="normal")

    def reset(self):
        for job in self._jobs:
            try:
                self.win.after_cancel(job)
            except Exception:                    # noqa: BLE001
                pass
        self._jobs = []
        self._drop_mole()
        self.score = 0
        self.hits = 0
        self.done = False
        self._awarded = 0
        self.left = self.SECONDS
        self.again.configure(state="disabled")
        self._refresh()
        self._tick()


GAMES = {
    "rps": ("猜拳", RPSGame),
    "guess": ("猜数字", GuessGame),
    "memory": ("翻牌记忆", MemoryGame),
    "mole": ("打地鼠", MoleGame),
}


def open_game(pet, key):
    """按小游戏名字开一个窗口；同名窗口已经开着就提到前面。"""
    game_cls = GAMES[key][1]
    win = getattr(pet, "_game_win", None)
    if win is not None and win.win is not None and win.win.winfo_exists():
        if win.__class__ is game_cls:
            try:
                win.win.deiconify()
                win.win.lift()
                win.win.focus_force()
            except tk.TclError:
                pass
            return win
        win.close()
    pet._game_win = game_cls(pet, key).show()
    return pet._game_win
