# -*- coding: utf-8 -*-
"""校徽图标接入 + 彻底去掉任务栏按钮。"""
import io

P = 'desktop_pet.spec'
s = io.open(P, encoding='utf-8').read()

anchor = "           ('assets/pet.ico', 'assets')],"
assert anchor in s, 'spec anchor not found'
s = s.replace(anchor,
              "           # 设置窗口里的校徽（tools/build_badge.py 生成）\n"
              "           ('assets/school_badge.png', 'assets'),\n"
              "           ('assets/school_badge_faded.png', 'assets'),\n"
              "           # 托盘 / exe / 窗口图标：校徽（tools/make_badge_ico.py 生成）\n"
              "           ('assets/school_badge.ico', 'assets'),\n"
              "           ('assets/pet.ico', 'assets')],", 1)

assert "    icon='assets/pet.ico'," in s
s = s.replace("    icon='assets/pet.ico',",
              "    icon='assets/school_badge.ico',", 1)
io.open(P, 'w', encoding='utf-8', newline='').write(s)
print('spec patched')

P = 'desktop_pet.py'
s = io.open(P, encoding='utf-8').read()


def rep(old, new, why=''):
    global s
    assert old in s, '%s: %r' % (why, old[:70])
    s = s.replace(old, new, 1)


rep('''            self.tray = TrayIcon(
                "桌面宠物（右键：设置 / 退出）", _asset_path("pet.ico"),''',
    '''            tray_icon = _asset_path("school_badge.ico")
            if not os.path.exists(tray_icon):
                tray_icon = _asset_path("pet.ico")
            self.tray = TrayIcon(
                "桌面宠物（右键：设置 / 退出）", tray_icon,''',
    'tray icon')

rep('''        # 托盘优先；拿不到才退回"屏幕外的小窗口当任务栏按钮"
        if not self._install_tray():
            self._install_taskbar()''',
    '''        # 只挂托盘图标（右下角「^」里）；拿不到也不在任务栏留按钮
        self._install_tray()''',
    'init tray only')

rep('''    def _tray_late_ok(self):
        """托盘线程调：注册终于成功了，回主线程把占位任务栏窗口撤掉。"""
        self._main_thread(self._drop_taskbar_hint)''',
    '''    def _tray_late_ok(self):
        """托盘线程调：后台重试终于注册成功了。

        以前这里要撤掉「任务栏占位窗口」；现在不再建那个窗口（用户只要右下角
        小箭头里的图标），所以只需要让设置窗口/菜单里的状态保持最新。
        """
        self._main_thread(self.sync_settings)''',
    'late ok')

start = s.find('    def _drop_taskbar_hint(self):')
assert start > 0
end = s.find('    def _tray_event(self, what):', start)
assert end > start
s = s[:start] + s[end:]

start = s.find('    def _install_taskbar(self):')
assert start > 0
end = s.find('    def _chat_closed(self, win):', start)
assert end > start
s = s[:start] + s[end:]

rep('''            hint = getattr(pet, "taskbar_win", None) is not None''',
    '''            hint = False        # 不再建任务栏占位窗口''',
    'tray hint')

rep('''    except Exception:                       # noqa: BLE001 - 缺图也要能开设置
        img = Image.new("RGBA", (int(size), int(size)), (244, 120, 159, 255))''',
    '''    except Exception:                       # noqa: BLE001 - 缺图也要能开设置
        _log_exception()
        img = Image.new("RGBA", (int(size), int(size)), (244, 120, 159, 255))''',
    'badge fallback log')

io.open(P, 'w', encoding='utf-8', newline='').write(s)
print('code patched')
