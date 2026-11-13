# -*- coding: utf-8 -*-
"""在线电台：不用往 music 文件夹里塞歌，直接放网上的 mp3 流。

数据来自 radio-browser.info（公开接口，不要 key），拿到的是一条条电台：
名字、流派标签、码率、可直接播的 url。MCI 的 mpegvideo 设备能边下边播，
所以点一下就能出声 —— 桌宠的「音乐」菜单里多一个「在线电台…」。

网络不通的时候退回到下面 PRESETS 里那几个手写地址（都是实测能放的），
所以没网也能听，只是选不了台。
"""
import json
import queue
import threading
import time
import tkinter as tk
import urllib.parse
import urllib.request

API = "https://de1.api.radio-browser.info/json/stations/search"
UA = "desktop-pet/1.0 (radio)"

# 手写的兜底电台（实测可播的中文台 + 一个氛围台）
PRESETS = [
    {"name": "中国之声", "url": "https://lhttp.qtfm.cn/live/15318317/64k.mp3",
     "tags": "新闻 综合", "bitrate": 64},
    {"name": "怀集音乐之声", "url": "https://lhttp.qingting.fm/live/4804/64k.mp3",
     "tags": "音乐", "bitrate": 64},
    {"name": "清晨音乐台", "url": "http://lhttp.qingting.fm/live/4915/64k.mp3",
     "tags": "轻音乐", "bitrate": 64},
    {"name": "两广之声音乐台", "url": "https://lhttp.qtfm.cn/live/20500149/64k.mp3",
     "tags": "音乐", "bitrate": 64},
    {"name": "SomaFM Groove Salad",
     "url": "http://ice1.somafm.com/groovesalad-128-mp3",
     "tags": "chillout ambient", "bitrate": 128},
]

# 分类：显示名 -> 搜索参数
CATEGORIES = [
    ("中文", {"country": "China", "codec": "mp3", "order": "clickcount"}),
    ("轻音乐", {"tag": "chillout", "codec": "mp3", "order": "clickcount"}),
    ("日语", {"tag": "jpop", "codec": "mp3", "order": "clickcount"}),
    ("白噪音", {"tag": "ambient", "codec": "mp3", "order": "clickcount"}),
    ("古典", {"tag": "classical", "codec": "mp3", "order": "clickcount"}),
]

BG = "#fff7ea"
CARD = "#ffffff"
INK = "#3b2b3a"
INK_SOFT = "#6d5b6b"
MUTED = "#a08e9c"
ACCENT = "#ff6f61"
PEACH = "#ffe1cf"
BORDER = "#e2c9b4"
OUTLINE = "#3b2b3a"

_FONT = "Microsoft YaHei UI"
_cache = {}          # (query, limit) -> (ts, stations)
_cache_lock = threading.Lock()
CACHE_TTL = 600.0


def _font_family(root):
    global _FONT
    try:
        import tkinter.font as tkfont
        fams = set(tkfont.families(root))
        for name in ("幼圆", "YouYuan", "Microsoft YaHei UI"):
            if name in fams:
                _FONT = name
                break
    except Exception:                            # noqa: BLE001
        pass
    return _FONT


def _clean_station(raw):
    url = str(raw.get("url_resolved") or raw.get("url") or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return None
    name = str(raw.get("name") or "").strip() or "未命名电台"
    tags = str(raw.get("tags") or "").replace(",", " ").strip()
    try:
        bitrate = int(raw.get("bitrate") or 0)
    except (TypeError, ValueError):
        bitrate = 0
    return {"name": name[:28], "url": url, "tags": tags[:24],
            "bitrate": bitrate}


def _fetch(params, limit, timeout):
    query = urllib.parse.urlencode(dict(params, limit=limit))
    req = urllib.request.Request(API + "?" + query, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    out = []
    for raw in data if isinstance(data, list) else []:
        st = _clean_station(raw)
        if st:
            out.append(st)
    return out


def stations_for(params, limit=20, timeout=6.0, use_cache=True):
    """按分类/关键词拿一批电台；网络不行就返回 PRESETS（只对「中文」）。"""
    key = (json.dumps(params, sort_keys=True), limit)
    now = time.time()
    if use_cache:
        with _cache_lock:
            hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL:
            return list(hit[1])
    try:
        found = _fetch(params, limit, timeout)
    except Exception:                            # noqa: BLE001
        found = []
    if not found and params.get("country") == "China":
        found = [dict(s) for s in PRESETS]
    if found:
        with _cache_lock:
            _cache[key] = (now, list(found))
    return found


def search(query, limit=20, timeout=6.0):
    """按名字搜台。"""
    q = str(query or "").strip()
    if not q:
        return stations_for({"country": "China", "codec": "mp3",
                             "order": "clickcount"}, limit, timeout)
    return stations_for({"name": q, "codec": "mp3", "order": "clickcount",
                         "reverse": "true"}, limit, timeout)


class RadioDialog(object):
    """「在线电台」小窗口：搜台、分类、点一下就能放。"""

    W, H = 420, 400

    def __init__(self, pet):
        self.pet = pet
        self.win = None
        self.listbox = None
        self.status = None
        self.entry = None
        self._stations = []
        self._seq = 0
        self._busy = False
        self._results = queue.Queue()

    # ------------------------------------------------------------ 窗口
    def show(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.lift()
            self.win.focus_force()
            return self
        root = self.pet.root
        font = _font_family(root)
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.title("在线电台")
        self.win.configure(bg=BG)
        self.win.resizable(False, False)
        try:
            self.win.attributes("-topmost", True)
        except tk.TclError:
            pass

        head = tk.Frame(self.win, bg=BG)
        head.pack(fill="x", padx=14, pady=(12, 4))
        tk.Label(head, text="在线电台", bg=BG, fg=INK,
                 font=(font, 14, "bold")).pack(side="left")
        tk.Button(head, text="✕", command=self.close, bg=BG, fg=INK_SOFT,
                  relief="flat", font=(font, 11, "bold"), bd=0,
                  activebackground=PEACH).pack(side="right")
        tk.Label(self.win, text="直接听网上的电台，不用往 music 文件夹里放歌　·　点台后要等 20~30 秒才出声（Windows 的限制）",
                 bg=BG, fg=MUTED, font=(font, 8)).pack(anchor="w", padx=16)

        row = tk.Frame(self.win, bg=BG)
        row.pack(fill="x", padx=14, pady=(8, 4))
        self.entry = tk.Entry(row, font=(font, 10), bg=CARD, fg=INK,
                              relief="solid", bd=1, insertbackground=INK)
        self.entry.pack(side="left", fill="x", expand=True, ipady=4)
        self.entry.bind("<Return>", lambda e: self.do_search())
        tk.Button(row, text="搜", command=self.do_search, bg=ACCENT, fg="#fff",
                  relief="flat", font=(font, 10, "bold"), bd=0, padx=12,
                  activebackground="#d94f43").pack(side="left", padx=(6, 0))

        cats = tk.Frame(self.win, bg=BG)
        cats.pack(fill="x", padx=14, pady=(2, 6))
        for name, params in CATEGORIES:
            tk.Button(cats, text=name, command=lambda p=params: self.load_category(p),
                      bg=PEACH, fg=INK, relief="flat", font=(font, 9), bd=0,
                      padx=8, pady=2,
                      activebackground="#ffc3a8").pack(side="left", padx=(0, 6))

        body = tk.Frame(self.win, bg=CARD, highlightbackground=BORDER,
                        highlightthickness=1)
        body.pack(fill="both", expand=True, padx=14)
        self.listbox = tk.Listbox(body, bg=CARD, fg=INK, bd=0,
                                   font=(font, 9), activestyle="none",
                                   selectbackground=PEACH, selectforeground=INK,
                                   highlightthickness=0)
        self.listbox.pack(side="left", fill="both", expand=True, padx=2, pady=2)
        bar = tk.Scrollbar(body, command=self.listbox.yview)
        bar.pack(side="right", fill="y")
        self.listbox.configure(yscrollcommand=bar.set)
        self.listbox.bind("<Double-Button-1>", lambda e: self.play_selected())
        self.listbox.bind("<Return>", lambda e: self.play_selected())

        foot = tk.Frame(self.win, bg=BG)
        foot.pack(fill="x", padx=14, pady=(6, 10))
        self.status = tk.Label(foot, text="正在找台…", bg=BG, fg=MUTED,
                               font=(font, 8), anchor="w", justify="left")
        self.status.pack(side="left", fill="x", expand=True)
        tk.Button(foot, text="停止", command=self.stop, bg=PEACH, fg=INK,
                  relief="flat", font=(font, 9), bd=0, padx=10,
                  activebackground="#ffc3a8").pack(side="right")
        tk.Button(foot, text="播放", command=self.play_selected, bg=ACCENT,
                  fg="#fff", relief="flat", font=(font, 9, "bold"), bd=0,
                  padx=10, activebackground="#d94f43").pack(side="right", padx=6)

        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.bind("<Escape>", lambda e: self.close())
        self._center()
        self.win.deiconify()
        self.win.focus_force()
        self.entry.focus_set()
        self.load_category(CATEGORIES[0][1])
        self._pump()
        return self

    def _center(self):
        try:
            root = self.pet.root
            self.win.update_idletasks()
            x = root.winfo_rootx() + (root.winfo_width() - self.W) // 2
            y = root.winfo_rooty() + (root.winfo_height() - self.H) // 2
            x = max(20, min(x, root.winfo_screenwidth() - self.W - 20))
            y = max(20, min(y, root.winfo_screenheight() - self.H - 60))
            self.win.geometry("%dx%d+%d+%d" % (self.W, self.H, x, y))
        except tk.TclError:
            pass

    def close(self):
        try:
            if self.win is not None:
                self.win.destroy()
        except tk.TclError:
            pass
        self.win = None

    # ------------------------------------------------------------ 数据
    def load_category(self, params):
        self._start(lambda: stations_for(params))

    def do_search(self):
        text = self.entry.get() if self.entry is not None else ""
        text = text.strip()
        if not text:
            self.load_category(CATEGORIES[0][1])
            return
        self._start(lambda: search(text))

    def _start(self, work):
        if self._busy:
            return
        self._busy = True
        self._seq += 1
        seq = self._seq
        self._set_status("正在找台…")

        def run():
            try:
                result = work()
            except Exception:                    # noqa: BLE001
                result = []
            # 不能从子线程碰 Tk（after 也不行）：结果丢进队列，主线程来取
            self._results.put((seq, result))

        threading.Thread(target=run, name="pet-radio", daemon=True).start()

    def _pump(self):
        """主线程每 120ms 取一次网络线程的结果。"""
        if self.win is None:
            return
        while True:
            try:
                seq, stations = self._results.get_nowait()
            except queue.Empty:
                break
            self._done(seq, stations)
        try:
            self.win.after(120, self._pump)
        except tk.TclError:
            pass

    def _done(self, seq, stations):
        self._busy = False
        if seq != self._seq or self.win is None:
            return
        self._stations = list(stations or [])
        self.listbox.delete(0, "end")
        for st in self._stations:
            bits = []
            if st.get("tags"):
                bits.append(st["tags"])
            if st.get("bitrate"):
                bits.append("%dk" % st["bitrate"])
            tail = ("  ·  " + " · ".join(bits)) if bits else ""
            self.listbox.insert("end", st["name"] + tail)
        if not self._stations:
            self._set_status("没找到台（可能是网络不通），换个词试试")
        else:
            self.listbox.selection_set(0)
            self._set_status("找到 %d 个台，双击 / 回车播放" % len(self._stations))

    def _set_status(self, text):
        try:
            self.status.configure(text=text)
        except (tk.TclError, AttributeError):
            pass

    # ------------------------------------------------------------ 播放
    def _selected_station(self):
        if not self._stations:
            return None
        try:
            idx = self.listbox.curselection()
        except (tk.TclError, AttributeError):
            idx = ()
        i = idx[0] if idx else 0
        if not (0 <= i < len(self._stations)):
            return None
        return self._stations[i]

    def play_selected(self):
        st = self._selected_station()
        if st is None:
            self._set_status("先选一个台")
            return
        ok = self.pet.play_radio(st, stations=self._stations)
        if ok:
            self._set_status("正在播放：%s" % st["name"])
        else:
            self._set_status("这个台放不出来，换一个试试")

    def stop(self):
        self.pet.stop_music()
        self._set_status("停了")
