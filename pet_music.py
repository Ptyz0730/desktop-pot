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

MUSIC_EXTS = (".mp3", ".wav", ".m4a", ".flac", ".ogg", ".wma")
ALIAS = "petmusic"


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
        """打开一个文件（先关掉上一首）。失败抛 MusicError，旧的不受影响。"""
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            raise MusicError("找不到文件：%s" % os.path.basename(path))
        self.close()
        self._cmd('open "%s" type mpegvideo alias %s' % (path, ALIAS))
        self.is_open = True
        self.path = path
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
