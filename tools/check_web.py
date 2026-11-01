# -*- coding: utf-8 -*-
"""自检：自定义快捷网页（打开网页菜单里的「＋ 添加网页…」）。

用法：<DSH python> tools\\check_web.py
（不联网：webbrowser 被替换成本地桩；测试前备份配置、测完还原。）
"""
import os
import shutil
import sys
import time
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import desktop_pet as dp  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print("  %-40s %s %s" % (name, "ok" if cond else "FAIL", detail))


def pump(pet, sec):
    end = time.monotonic() + sec
    while time.monotonic() < end:
        pet.root.update()
        time.sleep(0.02)


def labels(pet):
    m = pet.web_menu
    out = []
    for i in range(m.index("end") + 1):
        try:
            out.append(str(m.entrycget(i, "label")))
        except Exception:                   # 分隔线没有 label
            out.append("---")
    return out


CFG = dp.CONFIG_PATH
BAK = CFG + ".web_bak"
pet = None
opened = []
urls = []
_real_open = webbrowser.open


def fake_open(url, new=0, autoraise=True):
    urls.append(url)
    return True


try:
    if os.path.exists(CFG):
        shutil.copy2(CFG, BAK)
        os.remove(CFG)
    webbrowser.open = fake_open
    pet = dp.DesktopPet(use_ai=False, topmost=False, bubble=True)
    pump(pet, 0.8)

    print("=== 默认站点 ===")
    got = labels(pet)
    print("  菜单:", got)
    check("内置 8 个站点都在",
          all(any(k in x for x in got) for k in ("Bilibili", "GitHub", "DeepSeek",
                                                 "豆包", "知乎", "微博", "YouTube", "百度")))
    check("有「添加网页」项", any("添加网页" in x for x in got), "")
    check("一开始没有「删除」子菜单", not any("删除" in x for x in got), "")

    print("=== 加一个 ===")
    check("添加成功", pet.add_web_link("LeetCode", "leetcode.cn") is True)
    got = labels(pet)
    check("菜单里出现了", "LeetCode" in got, str(got))

    import json as _json
    try:
        with open(CFG, encoding="utf-8-sig") as fh:
            cfg = _json.load(fh)
    except Exception:
        cfg = {}
    saved = [x for x in cfg.get("web_links") or [] if x.get("name") == "LeetCode"]
    check("存进配置了", bool(saved) and saved[0]["url"] == "https://leetcode.cn",
          str(saved))
    check("名字重复不会多出一条", pet.add_web_link("LeetCode", "https://leetcode.com")
          is True and len([x for x in labels(pet) if x == "LeetCode"]) == 1,
          str(labels(pet)))

    print("=== 打开它 ===")
    urls[:] = []
    pet.open_web("leetcode.cn", "LeetCode")
    check("调了浏览器", urls == ["https://leetcode.cn"], str(urls))

    print("=== 乱填要被拦住 ===")
    n_before = len(labels(pet))
    check("没网址被拒绝", pet.add_web_link("瞎写", "not a url") is False)
    check("菜单没变", len(labels(pet)) == n_before, "")

    print("=== 弹窗（不点鼠标，直接走保存逻辑） ===")
    dlg = dp.WebLinkDialog(pet)
    dlg._build()
    dlg.name_var.set("知乎热榜")
    dlg.url_var.set("www.zhihu.com/hot")
    dlg._save()
    check("弹窗保存生效", "知乎热榜" in labels(pet) and dlg.win is None,
          str(labels(pet)))

    print("=== 删除自己加的 ===")
    check("删除成功", pet.remove_web_link("LeetCode") is True)
    check("菜单里没了", "LeetCode" not in labels(pet), str(labels(pet)))
    check("别的还在", "知乎热榜" in labels(pet), "")
    check("内置的删不掉", pet.remove_web_link("Bilibili") is False, "")

    print("=== 重开之后还在 ===")
    pet._save_config()
    pump(pet, 0.2)
    pet.quit()
    pet = None
    pet = dp.DesktopPet(use_ai=False, topmost=False, bubble=True)
    pump(pet, 0.8)
    check("知乎热榜还留着", "知乎热榜" in labels(pet), str(labels(pet)))
finally:
    webbrowser.open = _real_open
    try:
        if pet is not None:
            pet.quit()
    except Exception:                       # noqa: BLE001
        pass
    try:
        if os.path.exists(CFG):
            os.remove(CFG)
        if os.path.exists(BAK):
            shutil.move(BAK, CFG)
    except Exception:                       # noqa: BLE001
        pass

    print("RESULT:", "OK" if ok else "FAILED")


