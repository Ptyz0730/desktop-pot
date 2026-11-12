# -*- coding: utf-8 -*-
"""音乐播放：用 Windows 自带的 MCI（winmm）放 mp3/wav，不引第三方库。

MCI 的几个坑（都在这层里处理掉）：
  * 命令里带空格/中文的路径必须用双引号包起来；
  * 播放是异步的，`play` 立刻返回，要用 `status <alias> mode` 查是不是还在放；
  * 同一个 alias 不能重复 open，换歌要先 close；
  * 出错时 rc != 0，错误文本要用 mciGetErrorStringW 取。
"""
import ctypes
import os
import queue
import threading
import time

MUSIC_EXTS = (".mp3", ".wav", ".m4a", ".flac", ".ogg", ".wma")
ALIAS = "petmusic"
RADIO_ALIAS = "petradio"


class MusicError(Exception):
    """MCI 报错（文件坏了/格式不支持/设备被占用）。"""


def scan_music(folder):
    """扫 music/ 里的歌：返回 [(显示名, 完整路径), ...]，按文件名排序。"""
    found = []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return found
    for name in names:
        ext = os.path.splitext(name)[1].lower()
        path = os.path.join(folder, name)
        if ext in MUSIC_EXTS and os.path.isfile(path):
            found.append((os.path.splitext(name)[0], path))
    return found


def title_of(path):
    return os.path.splitext(os.path.basename(path))[0]


class MusicPlayer(object):
    """一首接一首地用 MCI 播放；同一时刻只有一个文件打开。"""

    def __init__(self):
        self._winmm = getattr(ctypes, "windll", None)
        self._winmm = self._winmm.winmm if self._winmm is not None else None
        self.path = ""
        self.is_open = False
        self.stream = False

    # ------------------------------------------------------------------ MCI
    def _cmd(self, command):
        if self._winmm is None:
            raise MusicError("只有 Windows 才能放歌")
        buf = ctypes.create_unicode_buffer(1024)
        rc = self._winmm.mciSendStringW(command, buf, 1024, None)
        if rc:
            err = ctypes.create_unicode_buffer(256)
            try:
                self._winmm.mciGetErrorStringW(rc, err, 256)
            except Exception:               # noqa: BLE001
                err.value = str(rc)
            raise MusicError("%s（rc=%d）" % (err.value or "MCI 出错", rc))
        return buf.value

    def load(self, path):
        """打开一个文件或网络地址（先关掉上一首）。失败抛 MusicError。

        网络地址（http/https 的 mp3 流）也能放：MCI 的 mpegvideo 设备支持
        边下边播，电台这种无限长的流正好合适。本地文件仍然要求真实存在。
        """
        path = str(path or "").strip()
        if not path:
            raise MusicError("没有给出要放的地址")
        is_url = path.lower().startswith(("http://", "https://"))
        if not is_url:
            path = os.path.abspath(path)
            if not os.path.isfile(path):
                raise MusicError("找不到文件：%s" % os.path.basename(path))
        self.close()
        self._cmd('open "%s" type mpegvideo alias %s' % (path, ALIAS))
        self.is_open = True
        self.path = path
        self.stream = is_url
        try:
            self._cmd("set %s time format milliseconds" % ALIAS)
        except MusicError:
            pass
        return path

    def play(self, path=None):
        if path is not None:
            self.load(path)
        if not self.is_open:
            raise MusicError("还没有打开文件")
        self._cmd("play %s" % ALIAS)

    def pause(self):
        if self.is_open:
            self._cmd("pause %s" % ALIAS)

    def resume(self):
        if self.is_open:
            self._cmd("resume %s" % ALIAS)

    def stop(self):
        if self.is_open:
            self._cmd("stop %s" % ALIAS)

    def close(self):
        if self.is_open:
            try:
                self._cmd("close %s" % ALIAS)
            except MusicError:
                pass
        self.is_open = False
        self.path = ""
        self.stream = False

    # -------------------------------------------------------------- 查询/音量
    def mode(self):
        """playing / paused / stopped / paused playing / ''（没打开或查不了）。"""
        if not self.is_open:
            return ""
        try:
            return self._cmd("status %s mode" % ALIAS).strip().lower()
        except MusicError:
            return ""

    def is_playing(self):
        return "playing" in self.mode().split() and "paused" not in self.mode()

    def length(self):
        """总长（毫秒），查不到返回 0。"""
        return self._num("length")

    def position(self):
        return self._num("position")

    def _num(self, what):
        if not self.is_open:
            return 0
        try:
            return int(self._cmd("status %s %s" % (ALIAS, what)).strip() or 0)
        except (MusicError, ValueError):
            return 0

    def seek(self, seconds):
        """往前跳 seconds 秒（负数是后退），返回跳完之后的秒数（查不到返回 -1）。

        MCI 的做法是 pause -> seek to <毫秒> -> play：直接在播放中 seek
        有些格式会失败，先停一下最稳。正在放的话跳完继续放。
        """
        if not self.is_open:
            return -1
        try:
            seconds = float(seconds)
        except (TypeError, ValueError):
            return -1
        if self.stream:
            return -1
        total = self.length()
        pos = self.position()
        limit = total if total > 0 else pos
        target = int(max(0, min(limit, pos + int(seconds * 1000))))
        was_playing = self.mode() == "playing"
        if was_playing:
            try:
                self._cmd("pause %s" % ALIAS)
            except MusicError:
                pass
        try:
            self._cmd("seek %s to %d" % (ALIAS, target))
        finally:
            if was_playing:
                try:
                    self._cmd("play %s" % ALIAS)
                except MusicError:
                    pass
        return round(target / 1000.0, 1)

    def set_volume(self, percent):
        """0-100 的音量（MCI 内部 0-1000）。"""
        if not self.is_open:
            return
        try:
            percent = max(0, min(100, int(percent)))
        except (TypeError, ValueError):
            return
        try:
            self._cmd("setaudio %s volume to %d" % (ALIAS, percent * 10))
        except MusicError:
            pass


class StreamPlayer(object):
    """网络流播放器：把 MCI 全放到一条后台线程里，主线程永不阻塞。

    为什么要单开一条线程：MCI 打开 https 的 mp3 流会同步阻塞 25 秒以上（实测
    中文台 25~30s），放在主线程会整个界面卡死；而 MCI 的设备和线程绑定
    （在 A 线程 open 出来的 alias，B 线程调用会 rc=263），所以 open/play/
    pause/stop/close/查询必须都在同一条线程里做。

    主线程只做两件事：put 一条命令、读缓存状态（status()/mode()/position()）。
    """

    OPEN_TIMEOUT = 32.0        # 开流超过这么久还没 playing，就当这个台不行

    def __init__(self, alias=RADIO_ALIAS):
        self.alias = alias
        self.path = ""
        self.stream = True
        winmm = getattr(ctypes, "windll", None)
        self._winmm = winmm.winmm if winmm is not None else None
        self._q = queue.Queue()
        self._thread = None
        self._gen = 0
        self._state = ""
        self._mode = ""
        self._pos = 0
        self._error = ""
        self._volume = 70
        self._since = time.monotonic()

    # ---------------------------------------------------------------- 主线程
    @property
    def is_open(self):
        return self._state in ("opening", "playing", "paused", "stopped")

    def status(self):
        return self._state

    def mode(self):
        return self._mode

    def position(self):
        return self._pos

    def last_error(self):
        return self._error

    def waited(self):
        return time.monotonic() - self._since

    def play(self, url):
        url = str(url or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            raise MusicError("不是网络地址：%s" % url)
        self._gen += 1
        self.path = url
        self._error = ""
        self._mode = ""
        self._pos = 0
        self._mark("opening")
        self._post("play", url, self._gen)
        return url

    def stop(self):
        self._post("stop")

    def pause(self):
        self._post("pause")

    def resume(self):
        self._post("resume")

    def close(self):
        self._gen += 1
        self._post("close")
        self._mode = ""
        self._pos = 0
        self.path = ""
        self._mark("")

    def quit(self):
        self._gen += 1
        self._post("quit")

    def give_up(self, why="连不上"):
        """主线程判超时：放弃当前这个台（后台线程会在 open 返回后自己关掉）。"""
        self._gen += 1
        self._error = why
        self._mark("error")

    def set_volume(self, percent):
        try:
            percent = max(0, min(100, int(percent)))
        except (TypeError, ValueError):
            return
        self._volume = percent
        self._post("volume", percent)

    # ---------------------------------------------------------------- 线程侧
    def _mark(self, state, error=None):
        self._state = state
        if error is not None:
            self._error = error
        self._since = time.monotonic()

    def _post(self, name, *args):
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self._run, name="pet-radio", daemon=True)
            self._thread.start()
        self._q.put((name,) + args)

    def _run(self):
        while True:
            try:
                job = self._q.get(timeout=0.25)
            except queue.Empty:
                self._poll()
                continue
            name = job[0]
            if name == "quit":
                self._close_alias()
                return
            try:
                if name == "play":
                    self._do_play(job[1], job[2])
                elif name == "stop":
                    self._do_stop()
                elif name == "pause":
                    self._do_pause()
                elif name == "resume":
                    self._do_resume()
                elif name == "close":
                    self._close_alias()
                elif name == "volume":
                    self._volume = job[1]
                    self._apply_volume()
            except MusicError:
                pass

    def _cmd(self, command):
        if self._winmm is None:
            raise MusicError("只有 Windows 才能放歌")
        buf = ctypes.create_unicode_buffer(1024)
        rc = self._winmm.mciSendStringW(command, buf, 1024, None)
        if rc:
            err = ctypes.create_unicode_buffer(256)
            try:
                self._winmm.mciGetErrorStringW(rc, err, 256)
            except Exception:               # noqa: BLE001
                err.value = str(rc)
            raise MusicError("%s（rc=%d）" % (err.value or "MCI 出错", rc))
        return buf.value

    def _do_play(self, url, gen):
        self._close_alias()
        try:
            # 这一步可能阻塞 25 秒以上（DNS + TLS + 缓冲），所以在后台线程里做
            self._cmd('open "%s" type mpegvideo alias %s' % (url, self.alias))
        except MusicError as exc:
            if gen == self._gen:
                self._mark("error", str(exc))
            return
        if gen != self._gen:                # 期间被放弃 / 换台了
            self._close_alias()
            return
        try:
            self._cmd("set %s time format milliseconds" % self.alias)
        except MusicError:
            pass
        try:
            self._cmd("play %s" % self.alias)
        except MusicError as exc:
            if gen == self._gen:
                self._mark("error", str(exc))
            self._close_alias()
            return
        self._apply_volume()
        self._mode = "playing"
        self._mark("playing")

    def _do_stop(self):
        if self._state in ("playing", "paused"):
            try:
                self._cmd("stop %s" % self.alias)
            except MusicError:
                pass
            self._mode = "stopped"
            self._mark("stopped")

    def _do_pause(self):
        if self._state == "playing":
            try:
                self._cmd("pause %s" % self.alias)
            except MusicError:
                return
            self._mode = "paused"
            self._mark("paused")

    def _do_resume(self):
        if self._state == "paused":
            try:
                self._cmd("resume %s" % self.alias)
            except MusicError:
                return
            self._mode = "playing"
            self._mark("playing")

    def _apply_volume(self):
        if self._state not in ("playing", "paused"):
            return
        try:
            self._cmd("setaudio %s volume to %d" % (self.alias, self._volume * 10))
        except MusicError:
            pass

    def _close_alias(self):
        try:
            self._cmd("close %s" % self.alias)
        except MusicError:
            pass
        self._mode = ""

    def _poll(self):
        if self._state not in ("playing", "paused"):
            return
        try:
            mode = self._cmd("status %s mode" % self.alias).strip().lower()
        except MusicError:
            mode = ""
        if not mode:
            return
        self._mode = mode
        if mode.startswith("paused"):
            if self._state != "paused":
                self._mark("paused")
        elif "playing" in mode:
            if self._state != "playing":
                self._mark("playing")
        elif mode == "stopped" or "stopped" in mode:
            self._mark("stopped")
        try:
            self._pos = int(self._cmd("status %s position" % self.alias).strip() or 0)
        except (MusicError, ValueError):
            pass
