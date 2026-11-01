"""自检：右键菜单里只剩"功能"，设置类开关都搬进设置窗口了。

跑法：
    python tools/check_menu.py
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import desktop_pet as dp                                    # noqa: E402

SETTINGS_LABELS = ("置顶", "显示气泡", "手势互动", "说话带颜文字", "点击穿透",
                   "浮在所有窗口上面", "启用 AI", "鼠标穿透", "全屏时停用",
                   "卡死自动刷新")
FUNCTION_LABELS = ("形象", "大小", "不透明度", "音乐", "打开网页", "说点什么",
                   "逗它玩", "对话…", "设置…", "刷新一下（卡死急救）",
                   "来一个颜文字", "回到右下角", "打开图片文件夹", "退出")


def settle(pet, seconds):
    end = time.time() + seconds
    while time.time() < end:
        try:
            pet.root.update()
        except Exception:                                   # noqa: BLE001
            return
        time.sleep(0.015)


def submenu(menu, wanted):
    """按名字找一个 cascade 子菜单。"""
    last = menu.index("end")
    for i in range((last or 0) + 1):
        try:
            if menu.type(i) == "cascade" and menu.entrycget(i, "label") == wanted:
                return menu.nametowidget(menu.entrycget(i, "menu"))
        except Exception:                                   # noqa: BLE001
            continue
    raise AssertionError("submenu %r not found" % (wanted,))


def labels(menu):
    out = []
    last = menu.index("end")
    if last is None:
        return out
    for i in range(last + 1):
        if menu.type(i) == "separator":
            continue
        try:
            out.append(menu.entrycget(i, "label"))
        except Exception:                                   # noqa: BLE001
            out.append("?")
    return out


def main():
    backup = os.path.join(ROOT, "pet_config.check_backup.json")
    cfg = dp.CONFIG_PATH
    if os.path.exists(cfg):
        os.replace(cfg, backup)
    pet = None
    try:
        pet = dp.DesktopPet(use_ai=False, bubble=True)
        settle(pet, 0.6)
        top = labels(pet.menu)
        print("menu:", " | ".join(top))
        hits = [lab for lab in top if lab in SETTINGS_LABELS]
        assert not hits, "settings toggles still in the menu: %r" % (hits,)
        missing = [lab for lab in FUNCTION_LABELS if lab not in top]
        assert not missing, "functional items missing from menu: %r" % (missing,)

        ai = labels(submenu(pet.menu, "AI 设置"))
        print("ai menu:", " | ".join(ai))
        assert "启用 AI" not in ai, "启用 AI 属于设置，应该在设置窗口里"

        play = labels(submenu(pet.menu, "逗它玩"))
        print("play menu:", " | ".join(play))
        for lab in ("摸头", "跳一下", "压扁", "转圈圈（晕）", "躲一下"):
            assert lab in play, "%s missing from 逗它玩" % lab

        # 外观：不再是系统默认的灰白 Tk 菜单
        font = str(pet.menu.cget("font"))
        bg = str(pet.menu.cget("background"))
        fg = str(pet.menu.cget("foreground"))
        print("menu style:", font, "| bg", bg, "| fg", fg,
              "| icons", len(pet._menu_photos))
        assert "YaHei" in font, "menu font should be the app font, got %r" % font
        assert bg.lower() == dp.MENU_BG.lower(), "menu bg should be MENU_BG"
        assert fg.lower() == dp.MENU_FG.lower(), "menu fg should be MENU_FG"
        assert len(pet._menu_photos) >= 10, "menu icons missing"
        sub_font = str(submenu(pet.menu, "逗它玩").cget("font"))
        assert "YaHei" in sub_font, "submenu font should be styled too"

        tray = pet.tray
        ids = [t[0] for t in getattr(tray, "commands", [])] \
            if tray is not None else []
        print("tray menu ids:", ids)
        for want in (1, 2, 3, 4, 5, 6):
            assert want in ids, "tray item %d missing" % want
        assert tray is not None and tray.ok, "tray icon should be registered"

        print("menu ok")
        return 0
    finally:
        if pet is not None:
            try:
                pet.quit()
            except Exception:                               # noqa: BLE001
                pass
        if os.path.exists(backup):
            os.replace(backup, cfg)


if __name__ == "__main__":
    sys.exit(main())
