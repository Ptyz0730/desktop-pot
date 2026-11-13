# -*- coding: utf-8 -*-
"""人设编辑器：在软件里直接改 / 加人设，还能让 AI 把一段粗糙的设定扩写完整。

设计要点：
- 内置人设（话痨朋友 / 闷骚少年 / 骚话少年）只读，想改就「复制成自定义」；
- 自定义人设存在 pet_config.json 的 custom_personas 里，启动时注册回 ai_client；
- 「AI 扩写」只发一次请求（后台线程跑，不卡主线程），失败就退回来让用户手写。

用法（在 desktop_pet 里）：
    PetPersonaDialog(pet).show()
"""
import json
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk

import ai_client

# 红白色系，和对话窗口 / 校徽一套
BG = "#fffdfd"
CARD = "#ffffff"
INK = "#332a2c"
INK_SOFT = "#6b5f61"
MUTED = "#9b8d8f"
ACCENT = "#b3242a"          # 一中红
ACCENT_DK = "#8a1a1f"
LINE = "#f0d5d6"
SOFT = "#fdf3f3"            # 浅红底（列表/脚注）
FONT = "Microsoft YaHei UI"
LOGO_SIZE = 46
TITLE = "编辑人设"

TIERS = (("0-20", 0), ("21-40", 21), ("41-60", 41), ("61-80", 61), ("81-100", 81))

EXPAND_SYSTEM = """你是角色设定编辑。用户给你一段很粗糙的角色设定，你要把它扩写成
可以直接给聊天模型用的人设，风格是「桌宠：二次元口吻、短句、只写台词和看的见的动作」。

只输出一个 JSON 对象，不要解释、不要 markdown 围栏，字段如下：
{
  "name": "角色名（2-4 个汉字，用户给了就用用户的）",
  "hint": "一句话简介，20 字以内",
  "prompt": "完整人设，350-600 字。要写：身份年龄、说话风格与口头禅、对玩家的态度、"
            "被夸/被靠近时的嘴硬反应、吃醋时的表现、冷战时的表现、"
            "旁白只写看得见的动作、绝不写心理活动、不替玩家做决定",
  "tones": ["陌生期(0-20)：称呼和语气", "熟悉期(21-40)：…", "朋友期(41-60)：…",
            "暧昧期(61-80)：…", "恋人期(81-100)：…"],
  "romance_line": "好感度满时的一句告白台词"
}
tones 必须是 5 条，从低到高，每条都以「XX期(区间)：」开头。"""


def _clean(text, limit=0):
    text = str(text or "").replace("\r\n", "\n").strip()
    if limit and len(text) > limit:
        text = text[:limit]
    return text


def normalize_tones(raw):
    """把模型给的 tones 规整成 ai_client 要的 ((81, 文本), (61, …) …) 五档。"""
    out = []
    if isinstance(raw, dict):
        raw = [raw.get(k) for k in ("0", "21", "41", "61", "81")]
    for idx, item in enumerate(list(raw or [])[:5]):
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            try:
                thr = int(item[0])
            except (TypeError, ValueError):
                thr = TIERS[idx][1]
            text = _clean(item[1])
        else:
            thr = TIERS[idx][1]
            text = _clean(item)
        if text:
            out.append((thr, text))
    if len(out) < 5:
        defaults = (
            "陌生期(0-20)：客气、有点距离。",
            "熟悉期(21-40)：会互怼，嘴上不饶人。",
            "朋友期(41-60)：主动搭话，嘴硬但关心。",
            "暧昧期(61-80)：容易脸红、吃醋，死不承认。",
            "恋人期(81-100)：撒娇直球，嘴上还要硬一句。",
        )
        have = dict(out)
        out = [(thr, have.get(thr) or defaults[i]) for i, (_, thr) in enumerate(TIERS)]
    return tuple(sorted(out, key=lambda t: -t[0]))


def expand(brain, basic, name=""):
    """调一次 API，把粗糙设定扩写成结构化人设。失败抛异常。"""
    basic = _clean(basic)
    if not basic:
        raise ValueError("先写两句基本设定")
    messages = [
        {"role": "system", "content": EXPAND_SYSTEM},
        {"role": "user", "content": "角色名：%s\n基本设定：\n%s" % (name or "（没定）", basic)},
    ]
    text = brain._complete(messages, max_tokens=1600, temperature=0.8,
                           json_mode=True)
    data = ai_client._json_object(text)
    if not isinstance(data, dict):
        raise ValueError("AI 返回的格式不对，再试一次")
    prompt = _clean(data.get("prompt"))
    if not prompt:
        raise ValueError("AI 没写出人设正文，再试一次")
    return {
        "name": _clean(data.get("name")) or _clean(name) or "新角色",
        "hint": _clean(data.get("hint"), 40),
        "prompt": prompt,
        "tones": normalize_tones(data.get("tones")),
        "romance_line": _clean(data.get("romance_line"), 30),
    }


class PetPersonaDialog:
    """人设编辑器窗口（单开）。"""

    W = 780
    H = 690

    def __init__(self, pet):
        self.pet = pet
        self.win = None
        self.jobs = []
        self.busy = False
        self._queue = queue.Queue()
        self.keys = []

    # ------------------------------------------------------------ 窗口
    def show(self):
        if self.win is not None:
            try:
                self.win.deiconify()
                self.win.lift()
                self.win.focus_force()
            except tk.TclError:
                self.win = None
            if self.win is not None:
                return self
        win = tk.Toplevel(self.pet.root)
        self.win = win
        win.title("编辑人设")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self.pet.root)
        win.protocol("WM_DELETE_WINDOW", self.close)
        win.bind("<Escape>", lambda e: self.close())
        try:
            self.pet._modal_depth += 1
        except Exception:                    # noqa: BLE001
            pass
        self._build(win)
        self._center(win)
        self._reload_list()
        self._poll()
        return self

    def _center(self, win):
        win.update_idletasks()
        root = self.pet.root
        x = root.winfo_rootx() + (root.winfo_width() - self.W) // 2
        y = root.winfo_rooty() - self.H - 12
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        x = max(8, min(x, sw - self.W - 8))
        y = max(8, min(y, sh - self.H - 48))
        win.geometry("%dx%d+%d+%d" % (self.W, self.H, x, y))

    def _asset(self, name):
        """assets/ 下的素材：打包后在 _MEIPASS，开发时在项目目录。"""
        bases = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")]
        mei = getattr(sys, "_MEIPASS", None)
        if mei:
            bases.insert(0, os.path.join(mei, "assets"))
        for base in bases:
            path = os.path.join(base, name)
            if os.path.isfile(path):
                return path
        return None

    def _logo_photo(self, win):
        path = self._asset("school_logo.png")
        if not path:
            return None
        try:
            from PIL import Image, ImageTk
            img = Image.open(path).convert("RGBA")
            img = img.resize((LOGO_SIZE, LOGO_SIZE), Image.LANCZOS)
            self._logo = ImageTk.PhotoImage(img, master=win)
            return self._logo
        except Exception:                 # noqa: BLE001
            return None

    def _build(self, win):
        # ---------------------------------------------------------- 标题带
        band_h = 72
        band = tk.Frame(win, bg=CARD)
        band.place(x=0, y=0, width=self.W, height=band_h)
        logo = self._logo_photo(win)
        if logo is not None:
            tk.Label(band, image=logo, bg=CARD, bd=0).place(
                x=16, y=(band_h - LOGO_SIZE) // 2)
        text_x = 16 + (LOGO_SIZE + 14 if logo is not None else 0)
        tk.Label(band, text=TITLE, bg=CARD, fg=ACCENT_DK,
                 font=(FONT, 16, "bold")).place(x=text_x, y=13)
        tk.Label(band, text="莆田一中 · 自定义角色", bg=CARD, fg=MUTED,
                 font=(FONT, 9)).place(x=text_x + 2, y=42)
        tk.Button(band, text="✕", command=self.close, bg=CARD, fg=MUTED,
                  activebackground=SOFT, activeforeground=ACCENT_DK,
                  relief="flat", bd=0, font=(FONT, 12),
                  cursor="hand2").place(x=self.W - 44, y=14, width=30, height=28)
        tk.Frame(win, bg=ACCENT, height=2).place(x=0, y=band_h - 2, width=self.W)
        tk.Frame(win, bg=LINE, height=1).place(x=0, y=band_h + 6, width=self.W)

        body = tk.Frame(win, bg=BG)
        body.place(x=16, y=band_h + 18, width=self.W - 32, height=self.H - band_h - 74)

        # ------------------------------------------------- 左：人设列表
        left = tk.Frame(body, bg=BG, width=196)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Label(left, text="人设列表", bg=BG, fg=ACCENT, font=(FONT, 9, "bold")
                 ).pack(anchor="w")
        card = tk.Frame(left, bg=CARD, highlightbackground=LINE,
                        highlightthickness=1)
        card.pack(fill="both", expand=True, pady=(6, 8))
        self.listbox = tk.Listbox(card, width=20, bg=CARD, fg=INK, bd=0,
                                  highlightthickness=0, font=(FONT, 10),
                                  activestyle="none", exportselection=False,
                                  selectbackground=ACCENT,
                                  selectforeground="#ffffff")
        self.listbox.pack(side="left", fill="both", expand=True, padx=2, pady=2)
        self.listbox.bind("<<ListboxSelect>>", lambda e: self._on_pick())
        self._btn(left, "＋ 新建人设", self._new, width=10).pack(fill="x")

        # ------------------------------------------------- 右：表单
        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(16, 0))

        self.v_name = tk.StringVar()
        self.v_hint = tk.StringVar()
        self.v_love = tk.StringVar()
        self.v_tier = [tk.StringVar() for _ in TIERS]
        self.tier_entries = []

        self._row(right, "名字", self.v_name, 0, width=26)
        self._row(right, "一句话简介", self.v_hint, 1, width=40)

        tk.Label(right, text="人设正文（AI 会按这段说话）", bg=BG, fg=INK_SOFT,
                 font=(FONT, 9)).grid(row=2, column=0, sticky="w", pady=(8, 2))
        self.txt = tk.Text(right, width=58, height=13, bg=CARD, fg=INK,
                           relief="flat", wrap="word", font=(FONT, 10),
                           insertbackground=ACCENT, highlightthickness=1,
                           highlightbackground=LINE, highlightcolor=ACCENT,
                           padx=8, pady=6)
        self.txt.grid(row=3, column=0, columnspan=3, sticky="we")

        tiers = tk.Frame(right, bg=BG)
        tiers.grid(row=4, column=0, columnspan=3, sticky="we", pady=(10, 0))
        tk.Label(tiers, text="好感度语气（0-100 五档）", bg=BG, fg=INK_SOFT,
                 font=(FONT, 9)).grid(row=0, column=0, columnspan=2, sticky="w")
        for i, (label, _thr) in enumerate(TIERS):
            tk.Label(tiers, text=label, bg=BG, fg=MUTED, width=7, anchor="e",
                     font=(FONT, 9)).grid(row=i + 1, column=0, sticky="e", pady=1)
            entry = self._entry(tiers, self.v_tier[i], 58, 9)
            entry.grid(row=i + 1, column=1, sticky="we", pady=1)
            self.tier_entries.append(entry)

        self._row(right, "告白台词", self.v_love, 5, width=40)
        for col in range(7):
            right.grid_rowconfigure(col, weight=0)
        right.grid_columnconfigure(1, weight=1)

        # ---------------------------------------------------------- 脚注
        tk.Frame(win, bg=LINE, height=1).place(x=0, y=self.H - 52, width=self.W)
        foot = tk.Frame(win, bg=SOFT)
        foot.place(x=0, y=self.H - 51, width=self.W, height=51)
        self.status = tk.Label(foot, text="", bg=SOFT, fg=INK_SOFT, font=(FONT, 9))
        self.status.pack(side="left", padx=16)

        self.b_save = self._btn(foot, "保存", self._save, width=8, primary=True)
        self.b_save.pack(side="right", padx=(8, 14), pady=9)
        self.b_copy = self._btn(foot, "复制成自定义", self._copy, width=12)
        self.b_copy.pack(side="right", padx=8, pady=9)
        self.b_del = self._btn(foot, "删除", self._delete, width=6)
        self.b_del.pack(side="right", padx=8, pady=9)
        self.b_ai = self._btn(foot, "AI 扩写", self._expand, width=9)
        self.b_ai.pack(side="right", pady=9)

    def _btn(self, parent, text, command, width=8, primary=False):
        """红白按钮：主按钮实心红，其余白底红字 + 细红框。"""
        if primary:
            return tk.Button(parent, text=text, command=command, bg=ACCENT,
                             fg="#ffffff", activebackground=ACCENT_DK,
                             activeforeground="#ffffff",
                             disabledforeground="#e9b6b8",
                             relief="flat", bd=0, width=width,
                             font=(FONT, 10, "bold"), cursor="hand2",
                             highlightthickness=0)
        return tk.Button(parent, text=text, command=command, bg=CARD, fg=ACCENT,
                         activebackground=SOFT, activeforeground=ACCENT_DK,
                         disabledforeground="#cbb9ba",
                         relief="flat", bd=0, width=width,
                         font=(FONT, 10), cursor="hand2",
                         highlightthickness=1,
                         highlightbackground="#e7bfc0",
                         highlightcolor="#e7bfc0")

    def _entry(self, parent, var, width=30, size=10):
        return tk.Entry(parent, textvariable=var, width=width, bg=CARD, fg=INK,
                        relief="flat", font=(FONT, size), insertbackground=ACCENT,
                        highlightthickness=1, highlightbackground=LINE,
                        highlightcolor=ACCENT)

    def _row(self, parent, label, var, row, width=30):
        tk.Label(parent, text=label, bg=BG, fg=INK_SOFT, font=(FONT, 9)).grid(
            row=row, column=0, sticky="w", pady=3)
        entry = self._entry(parent, var, width, 10)
        entry.grid(row=row, column=1, columnspan=2, sticky="we", pady=3)
        return entry

    # ------------------------------------------------------------ 数据
    def _reload_list(self, select=None):
        self.listbox.delete(0, "end")
        self.keys = []
        for key in ai_client.PERSONA_PROMPTS:
            mark = "（内置）" if key not in self.pet.custom_personas else ""
            self.listbox.insert("end", "%s%s" % (key, mark))
            self.keys.append(key)
        if select and select in self.keys:
            idx = self.keys.index(select)
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(idx)
            self.listbox.see(idx)
        self._on_pick()

    def _current(self):
        sel = self.listbox.curselection()
        if not sel:
            return None
        idx = int(sel[0])
        return self.keys[idx] if 0 <= idx < len(self.keys) else None

    def _is_custom(self, key):
        return key in self.pet.custom_personas

    def _on_pick(self):
        key = self._current()
        custom = bool(key) and self._is_custom(key)
        self.b_save.configure(state="normal" if custom else "disabled")
        self.b_del.configure(state="normal" if custom else "disabled")
        self.b_copy.configure(state="normal" if key and not custom else "disabled")
        if not key:
            return
        data = self.pet.custom_personas.get(key)
        if not data:
            data = {
                "name": ai_client.persona_display_name(key),
                "hint": ai_client.persona_hint(key) or "",
                "prompt": ai_client.PERSONA_PROMPTS.get(key, ""),
                "tones": ai_client.PERSONA_TONES.get(key, ()),
                "romance_line": ai_client.romance_line(key),
            }
        self._fill(data)

    def _fill(self, data):
        self.v_name.set(str(data.get("name") or ""))
        self.v_hint.set(str(data.get("hint") or ""))
        self.v_love.set(str(data.get("romance_line") or ""))
        tones = normalize_tones(data.get("tones")) if len(data.get("tones") or ()) else ()
        table = {thr: text for thr, text in tones}
        for i, (_label, thr) in enumerate(TIERS):
            self.v_tier[i].set(table.get(thr, ""))
        for entry in self.tier_entries:      # 条目是右对齐滚动的，重置到开头
            try:
                entry.xview_moveto(0)
            except tk.TclError:
                pass
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", str(data.get("prompt") or ""))

    def _collect(self):
        return {
            "name": _clean(self.v_name.get()),
            "hint": _clean(self.v_hint.get(), 40),
            "prompt": _clean(self.txt.get("1.0", "end")),
            "tones": normalize_tones([self.v_tier[i].get() for i in range(5)]),
            "romance_line": _clean(self.v_love.get(), 30),
        }

    # ------------------------------------------------------------ 动作
    def _new(self):
        self.listbox.selection_clear(0, "end")
        self._fill({"name": "", "hint": "", "prompt": "",
                    "tones": (), "romance_line": ""})
        self.b_save.configure(state="normal")
        self.b_del.configure(state="disabled")
        self.b_copy.configure(state="disabled")
        self._status("写两句基本设定，再点「AI 扩写」")
        self.txt.focus_set()

    def _copy(self):
        key = self._current()
        if not key:
            return
        data = self._collect()
        data["name"] = data["name"] or key
        new_key = data["name"]
        if new_key in ai_client.PERSONA_PROMPTS:
            new_key = new_key + "·改"
        data["name"] = new_key
        self.pet.save_custom_persona(new_key, data)
        self._reload_list(select=new_key)
        self._status("已复制成自定义人设「%s」" % new_key)

    def _save(self):
        key = self._current()
        data = self._collect()
        if not data["prompt"]:
            self._status("人设正文不能空着")
            return
        name = data["name"] or key
        if not name:
            self._status("给它起个名字")
            return
        if key and self._is_custom(key) and name == key:
            self.pet.save_custom_persona(key, data)
        else:
            if name in ai_client.PERSONA_PROMPTS and not self._is_custom(name):
                self._status("「%s」是内置人设，换个名字" % name)
                return
            self.pet.save_custom_persona(name, data)
        self._reload_list(select=data["name"])
        self._status("已保存「%s」" % data["name"])

    def _delete(self):
        key = self._current()
        if not key or not self._is_custom(key):
            return
        self.pet.delete_custom_persona(key)
        self._reload_list()
        self._status("已删除「%s」" % key)

    def _expand(self):
        if self.busy:
            return
        basic = _clean(self.txt.get("1.0", "end"))
        if len(basic) < 4:
            self._status("先写两句基本设定，再点 AI 扩写")
            return
        brain = getattr(self.pet, "brain", None)
        if brain is None or not brain.enabled:
            self._status("先设置 API Key，才能用 AI 扩写")
            return
        name = _clean(self.v_name.get())
        self.busy = True
        self._status("AI 正在写…（一般十几秒）")
        self.b_ai.configure(state="disabled")

        def work():
            try:
                self._queue.put(("ok", expand(brain, basic, name)))
            except Exception as exc:        # noqa: BLE001
                self._queue.put(("err", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            kind, payload = self._queue.get_nowait()
        except queue.Empty:
            kind = None
        if kind == "ok":
            self.busy = False
            self.b_ai.configure(state="normal")
            self.v_name.set(payload["name"])
            self.v_hint.set(payload.get("hint") or "")
            table = {thr: text for thr, text in payload["tones"]}
            for i, (_label, thr) in enumerate(TIERS):
                self.v_tier[i].set(table.get(thr, ""))
            if payload.get("romance_line"):
                self.v_love.set(payload["romance_line"])
            self.txt.delete("1.0", "end")
            self.txt.insert("1.0", payload["prompt"])
            self._status("写好了，可以再改，然后点保存")
        elif kind == "err":
            self.busy = False
            self.b_ai.configure(state="normal")
            self._status("AI 没成功：%s" % payload)
        if self.win is not None:
            try:
                self.jobs.append(self.win.after(120, self._poll))
            except tk.TclError:
                pass

    def _status(self, text):
        try:
            self.status.configure(text=text)
        except tk.TclError:
            pass

    # ------------------------------------------------------------ 关闭
    def close(self):
        win, self.win = self.win, None
        try:
            self.pet._modal_depth = max(0, self.pet._modal_depth - 1)
        except Exception:                    # noqa: BLE001
            pass
        if win is not None:
            for job in self.jobs:
                try:
                    win.after_cancel(job)
                except tk.TclError:
                    pass
            self.jobs = []
            try:
                win.destroy()
            except tk.TclError:
                pass
        try:
            self.pet.persona_editor = None
        except Exception:                    # noqa: BLE001
            pass
