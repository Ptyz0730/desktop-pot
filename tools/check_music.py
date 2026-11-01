# -*- coding: utf-8 -*-
"""音乐功能自检：MCI 播放链路 + 菜单/气泡/存档 + 放完自动下一首。

用法：<DSH python> tools\\check_music.py
"""
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import desktop_pet as dp  # noqa: E402
import pet_music  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print("  %-44s %s %s" % (name, "ok" if cond else "FAIL", detail))


def bubble_text(pet):
    try:
        return "".join((pet.bubble._plan or {}).get("lines") or [])
    except Exception:                       # noqa: BLE001
        return ""


CFG = dp.CONFIG_PATH
BAK = CFG + ".music_bak"
if os.path.exists(CFG):
    shutil.copy2(CFG, BAK)
try:
    print("=== 扫描 music/ ===")
    songs = pet_music.scan_music(dp.MUSIC_DIR)
    for title, path in songs:
        print("  %s  (%d KB)" % (title, os.path.getsize(path) // 1024))
    check("扫到两首以上", len(songs) >= 2, "%d 首" % len(songs))

    print("=== MusicPlayer 原始链路 ===")
    player = pet_music.MusicPlayer()
    player.play(songs[0][1])
    player.set_volume(40)
    time.sleep(0.8)
    check("在放", "playing" in player.mode(), player.mode())
    check("有时长", player.length() > 1000, "%d ms" % player.length())
    pos1 = player.position()
    time.sleep(0.5)
    check("进度在走", player.position() >= pos1, "%d -> %d" % (pos1, player.position()))
    player.pause()
    time.sleep(0.2)
    check("能暂停", player.mode() == "paused", player.mode())
    player.resume()
    time.sleep(0.2)
    check("能继续", "playing" in player.mode(), player.mode())
    player.stop()
    player.close()
    check("关掉之后不再打开", not player.is_open)

    print("=== 桌宠里的音乐菜单 ===")
    if os.path.exists(CFG):
        os.remove(CFG)
    pet = dp.DesktopPet(use_ai=False, topmost=False, bubble=True)
    time.sleep(0.3)
    pet.root.update()
    check("启动就扫到歌", len(pet.music_files) >= 2, "%d 首" % len(pet.music_files))
    labels = []
    for i in range(pet.music_menu.index("end") + 1):
        try:
            labels.append(str(pet.music_menu.entrycget(i, "label")))
        except Exception:                   # noqa: BLE001 - 分隔符没有 label
            labels.append("-")
    print("  菜单项:", labels[:6], "...")
    check("菜单里有歌名", any(songs[0][0] in x for x in labels), str(labels[:3]))
    check("菜单里有音量", any("音量" in x for x in labels))

    print("=== 点歌播放 ===")
    first = songs[0][1]
    check("play_music 成功", pet.play_music(first))
    pet.root.update()
    check("歌名记下了", pet.music_name == os.path.basename(first), pet.music_name)
    check("菜单选中这首", pet.music_var.get() == os.path.basename(first),
          pet.music_var.get())
    said = bubble_text(pet)
    print("  气泡:", said)
    check("气泡报了歌名", "正在播放" in said and songs[0][0] in said, said[:50])
    check("真的在放", "playing" in pet.music.mode(), pet.music.mode())
    cfg = json.load(open(CFG, encoding="utf-8-sig"))
    check("存档记了这首", (cfg.get("music") or {}).get("file")
          == os.path.basename(first), str(cfg.get("music")))

    print("=== 暂停 / 继续 / 音量 / 停止 ===")
    pet.toggle_music()
    pet.root.update()
    check("暂停了", pet.music.mode() == "paused", pet.music.mode())
    check("气泡说暂停", "先停一下" in bubble_text(pet), bubble_text(pet)[:40])
    pet.toggle_music()
    pet.root.update()
    check("继续放", "playing" in pet.music.mode(), pet.music.mode())
    check("继续后挂回控制条", pet.bubble.persistent() and pet.bubble.visible(),
          "persistent=%s visible=%s" % (pet.bubble.persistent(), pet.bubble.visible()))
    check("控制条五个按钮", len(pet.bubble._buttons) == 5,
          "%d 个" % len(pet.bubble._buttons))
    labels = [b.cget("text") for b in pet.bubble._buttons]
    check("有上一首/下一首", labels[0] == "«" and labels[-1] == "»", str(labels))
    check("按钮都在卡片里", all(
        b.winfo_x() + b.winfo_width() <= pet.bubble._plan["w"]
        for b in pet.bubble._buttons),
          "w=%s" % pet.bubble._plan["w"])
    pet._music_volume(10)
    pet.root.update()
    check("音量变了", pet.music_volume == 70, str(pet.music_volume))

    print("=== 常驻气泡：一直在 / 快进后退 / 空格停止 ===")
    pet.play_music(first)
    for _ in range(20):                    # 比 SHOW_MS(4s) 还久，应该还在
        pet.root.update()
        time.sleep(0.3)
    check("4 秒后还在（常驻）", pet.bubble.visible(), "visible=%s" % pet.bubble.visible())
    check("标题是歌名", songs[0][0] in bubble_text(pet), bubble_text(pet)[:40])

    pet.music.seek(0)
    time.sleep(0.6)
    before = pet.music.position()
    check("快进 15 秒", pet.seek_music(15))
    time.sleep(0.4)
    after = pet.music.position()
    check("进度往前走了约 15 秒", after - before >= 13000,
          "%d -> %d" % (before, after))
    check("后退 15 秒", pet.seek_music(-15))
    time.sleep(0.4)
    check("进度退回约 15 秒", pet.music.position() < after - 8000,
          "%d -> %d" % (after, pet.music.position()))
    check("快进后退之后还在放", "playing" in pet.music.mode(), pet.music.mode())

    pet.bubble.hide()                      # 模拟被别的窗口盖住/被别的话顶掉
    pet._music_bubble_at = 0
    # 这个用例要在"露在桌面上"的前提下测：机器上前台是最大化浏览器时宠物
    # 会被判成 covered，_tick_body 在可见性检查那步就 return 了，走不到
    # 挂回气泡的逻辑（那是环境导致的，不是 bug）。
    pet.visible = True
    pet._next_visible_check = time.time() + 60
    pet._tick()
    check("气泡没了会自动挂回来", pet.bubble.visible() and pet.bubble.persistent(),
          "visible=%s" % pet.bubble.visible())

    check("空格键能停止", pet._key_stop_music() == "break")
    pet.root.update()
    check("空格之后真停了", not pet.music.is_open)
    check("停止后控制条收起", not pet.bubble.persistent(), "persistent=%s"
          % pet.bubble.persistent())
    check("气泡说不放了", "不放了" in bubble_text(pet), bubble_text(pet)[:40])

    print("=== 切歌（首尾相接）+ 快捷键 ===")
    allsongs = pet.music_files
    n = len(allsongs)
    first_name = os.path.basename(allsongs[0][1])
    pet.play_music(allsongs[0][1])
    pet.root.update()
    check("第一首往前 -> 最后一首", pet._switch_music(-1)
          and pet.music_name == os.path.basename(allsongs[-1][1]), pet.music_name)
    check("最后一首往后 -> 第一首", pet._switch_music(1)
          and pet.music_name == first_name, pet.music_name)
    check("切歌之后还在放", "playing" in pet.music.mode(), pet.music.mode())
    check("切歌键 [ 有效", pet._key_switch_music(-1)() == "break")
    pet.root.update()
    check("切歌键之后换了一首", pet.music_name != first_name, pet.music_name)
    pet.toggle_music()
    pet.root.update()
    check("暂停了", pet.music_paused and pet.music.mode() == "paused")
    pet._switch_music(1)
    pet.root.update()
    check("暂停中切歌仍然暂停", pet.music_paused and pet.music.mode() == "paused",
          "paused=%s mode=%s" % (pet.music_paused, pet.music.mode()))
    check("暂停时控制条不挂", not pet.bubble.persistent())
    pet.toggle_music()
    pet.root.update()
    check("继续放回来", "playing" in pet.music.mode(), pet.music.mode())

    print("=== 打开网页 ===")
    labels = []
    for _i in range(pet.web_menu.index("end") + 1):
        try:
            labels.append(str(pet.web_menu.entrycget(_i, "label")))
        except Exception:                   # 分隔线没有 label
            labels.append("---")
    print("  网页菜单:", labels)
    check("菜单里有 B站/GitHub/DeepSeek/豆包",
          all(any(k in x for x in labels)
              for k in ("Bilibili", "GitHub", "DeepSeek", "豆包")), str(labels))
    import webbrowser
    opened = []
    real_open = webbrowser.open
    webbrowser.open = lambda url, new=0, autoraise=True: opened.append(url) or True
    try:
        check("点一下会调默认浏览器",
              pet.open_web(dp.WEB_LINKS[0][1], dp.WEB_LINKS[0][0])
              and opened == [dp.WEB_LINKS[0][1]], str(opened))
    finally:
        webbrowser.open = real_open
    pet.music.close()

    print("=== 一首放完自动下一首 ===")
    pet.play_music(songs[0][1])
    pet.root.update()
    original_mode = pet.music.mode
    pet.music.mode = lambda: "stopped"
    pet._music_tick(time.monotonic())
    pet.music.mode = original_mode
    pet.root.update()
    check("切到下一首", pet.music_name == os.path.basename(songs[1][1]),
          pet.music_name)
    said = bubble_text(pet)
    check("气泡报了第二首", songs[1][0] in said, said[:50])
    pet.music.close()
    pet.quit()
finally:
    try:
        if os.path.exists(CFG):
            os.remove(CFG)
        if os.path.exists(BAK):
            shutil.move(BAK, CFG)
    except Exception:                       # noqa: BLE001
        pass

print("RESULT:", "OK" if ok else "FAILED")

