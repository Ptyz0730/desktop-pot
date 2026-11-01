# -*- coding: utf-8 -*-
"""给 check_menu.py 追加：菜单外观（字体/配色/图标）与托盘条目检查。"""
import io

P = 'tools/check_menu.py'
s = io.open(P, encoding='utf-8').read()

old = '''        tray = pet.tray
        print("tray menu ids:", [t[0] for t in getattr(tray, "items", [])]
              if tray is not None else "no tray")
        print("menu ok")
        return 0'''

new = '''        # 外观：不再是系统默认的灰白 Tk 菜单
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
        ids = [t[0] for t in getattr(tray, "items", [])] if tray is not None else []
        print("tray menu ids:", ids)
        for want in (1, 2, 3, 4, 5, 6):
            assert want in ids, "tray item %d missing" % want

        print("menu ok")
        return 0'''

assert old in s
s = s.replace(old, new, 1)
io.open(P, 'w', encoding='utf-8', newline='').write(s)
print('menu check extended')
