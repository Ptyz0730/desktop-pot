# -*- coding: utf-8 -*-
"""在线电台自检：数据解析、兜底、异步流播放（本地 HTTP 服务器）、切台、停止、存档、窗口。

为了不依赖外网，集成测试自己起一个 127.0.0.1 的 http.server 供两个 mp3，
流一开就是秒开；真电台那 25 秒的 open 留给人工试。

跑法：python tools\\check_radio.py
会真的出声几秒（本地文件），不想听就先把系统音量关小。
"""
import functools
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import desktop_pet as dp
import pet_music
import pet_radio

OK = []
MUSIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "music")


def check(name, cond, detail=""):
    OK.append(bool(cond))
    print(("ok   - " if cond else "FAIL - ") + name +
          ("" if cond else "   | " + str(detail)))


def settle(pet, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pet.root.update()
        time.sleep(0.01)


def wait_stream(pet, want="playing", limit=8.0):
    """等 StreamPlayer 进到某个状态（主线程每轮只能花很短的时间）。"""
    end = time.monotonic() + limit
    while time.monotonic() < end:
        start = time.monotonic()
        pet.root.update()
        spent = time.monotonic() - start
        if spent > 0.5:                  # 主线程被 MCI 卡住了
            return False, "主线程卡了 %.2fs" % spent
        if pet.stream.status() == want:
            return True, pet.stream.status()
        time.sleep(0.05)
    return False, pet.stream.status()


def unit_tests():
    print("\n[数据层]")
    for st in pet_radio.PRESETS:
        check("内置台 %s 地址合法" % st["name"],
              st["url"].lower().startswith("http"), st["url"])
    st = pet_radio._clean_station({"name": "测试台", "url_resolved": "https://a/b.mp3",
                                   "tags": "流行,音乐", "bitrate": "128"})
    check("解析台信息", st and st["name"] == "测试台" and st["bitrate"] == 128, st)
    check("非 http 地址被丢掉",
          pet_radio._clean_station({"name": "x", "url": "ftp://x"}) is None)

    # 断网兜底：_fetch 抛异常时，中文分类回落到 PRESETS
    real_fetch = pet_radio._fetch

    def boom(*a, **k):
        raise OSError("no network")
    pet_radio._fetch = boom
    try:
        found = pet_radio.stations_for({"country": "China", "codec": "mp3"},
                                      use_cache=False)
    finally:
        pet_radio._fetch = real_fetch
    check("断网时回落到内置台", len(found) >= len(pet_radio.PRESETS), len(found))
    check("兜底台带 url", all(f.get("url") for f in found))


def local_radio_server():
    """起一个只给两个 mp3 的本地服务器，返回 (base_url, cleanup)。"""
    tmp = tempfile.mkdtemp(prefix="pet_radio_")
    picks = [n for n in sorted(os.listdir(MUSIC_DIR)) if n.lower().endswith(".mp3")][:2]
    for i, name in enumerate(picks):
        shutil.copy2(os.path.join(MUSIC_DIR, name), os.path.join(tmp, "s%d.mp3" % i))
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=tmp)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.log_message = lambda *a, **k: None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]

    def cleanup():
        try:
            srv.shutdown()
        except Exception:                # noqa: BLE001
            pass
        shutil.rmtree(tmp, ignore_errors=True)
    return base, cleanup


def integration_tests():
    print("\n[桌宠集成]")
    base, cleanup = local_radio_server()
    stations = [
        {"name": "测试一台", "url": base + "/s0.mp3", "tags": "测试", "bitrate": 128},
        {"name": "测试二台", "url": base + "/s1.mp3", "tags": "测试", "bitrate": 128},
    ]
    cfg_path = dp.CONFIG_PATH
    bak = cfg_path + ".radio_bak"
    had = os.path.isfile(cfg_path)
    if had:
        shutil.copy2(cfg_path, bak)
    try:
        if had:
            os.remove(cfg_path)
        pet = dp.DesktopPet(use_ai=False, topmost=True, bubble=True, style="colorkey")
        settle(pet, 0.4)

        ok = pet.play_radio(stations[0], stations=stations)
        check("play_radio 立即返回成功", ok)
        check("切换成在线模式", pet.music_online)
        check("记下当前电台", (pet.radio_station or {}).get("name") == "测试一台",
              pet.radio_station)
        check("返回时还没阻塞（状态是 opening 或已 playing）",
              pet.stream.status() in ("opening", "playing"), pet.stream.status())

        playing, detail = wait_stream(pet, "playing", 8.0)
        check("流真的放起来了（主线程没被卡住）", playing, detail)
        check("stream.is_open", pet.stream.is_open, pet.stream.status())
        check("音量已设置", pet.music_volume == 60, pet.music_volume)
        check("头顶控制条挂出来了", pet.bubble.visible(), pet._music_bubble_wanted)

        # 切台：下一台、上一台
        first = pet.radio_station["url"]
        pet.next_station()
        settle(pet, 0.2)
        check("下一台换了地址", pet.radio_station["url"] == stations[1]["url"],
              pet.radio_station)
        ok2, detail2 = wait_stream(pet, "playing", 8.0)
        check("切台后也能放", ok2, detail2)
        pet.prev_station()
        settle(pet, 0.2)
        check("上一台绕回来了", pet.radio_station["url"] == first, pet.radio_station)

        # 暂停/继续
        pet.toggle_music()
        settle(pet, 0.4)
        check("暂停电台", pet.stream.status() == "paused", pet.stream.status())
        pet.toggle_music()
        settle(pet, 0.4)
        check("继续电台", pet.stream.status() == "playing", pet.stream.status())

        # 菜单里有「在线电台…」
        labels = []
        for i in range(pet.music_menu.index("end") + 1):
            try:
                labels.append(str(pet.music_menu.entrycget(i, "label")))
            except Exception:                    # noqa: BLE001
                labels.append("")
        check("音乐菜单有在线电台入口",
              any("在线电台" in x for x in labels), labels[:4])

        # 存档：online 字段写进去了
        pet._save_config()
        with open(cfg_path, encoding="utf-8") as fh:
            saved = json.load(fh)
        music = saved.get("music") or {}
        check("配置记住当前电台", (music.get("online") or {}).get("url") == first, music)
        check("在线时不把 url 写进 file", music.get("file") == "", music)

        # 停止
        pet.stop_music()
        settle(pet, 0.4)
        check("停止后不再是在线", not pet.music_online)
        check("停止后播放器关掉了", not pet.stream.is_open, pet.stream.status())
        check("停止后本地播放器也没开", not pet.music.is_open, pet.music.mode())

        # 窗口：用假数据，别依赖网络
        real = pet_radio.stations_for
        pet_radio.stations_for = lambda *a, **k: list(stations)
        try:
            pet.open_radio()
            settle(pet, 0.4)
            dlg = pet._radio_dialog
            check("电台窗口开了", dlg is not None and dlg.win is not None)
            check("列表里有台", dlg.listbox.size() == len(stations),
                  dlg.listbox.size())
            dlg.listbox.selection_clear(0, "end")
            dlg.listbox.selection_set(1)
            dlg.play_selected()
            settle(pet, 0.4)
            check("窗口里点台能播", pet.music_online and
                  pet.radio_station["url"] == stations[1]["url"], pet.radio_station)
            check("状态栏显示正在播放",
                  "正在播放" in dlg.status.cget("text"), dlg.status.cget("text"))
            dlg.stop()
            settle(pet, 0.2)
            check("窗口里停止能用", not pet.music_online)
            dlg.close()
            settle(pet, 0.2)
            check("窗口关得掉", pet._radio_dialog.win is None)
        finally:
            pet_radio.stations_for = real

        pet.quit()
    finally:
        if had:
            shutil.move(bak, cfg_path)
        elif os.path.isfile(cfg_path):
            os.remove(cfg_path)
        cleanup()


def main():
    unit_tests()
    integration_tests()
    print("\nRESULT:", "OK" if all(OK) else "FAILED (%d/%d)" % (OK.count(False), len(OK)))
    return 0 if all(OK) else 1


if __name__ == "__main__":
    sys.exit(main())
