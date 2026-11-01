# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec：打包成**目录版** exe（免安装绿色版）。

为什么是目录版：单文件版启动时要把自己解包到一个临时目录，而本机环境里
PyInstaller 的引导程序创建不了那个临时目录（一个 hello-world 的单文件 exe
也报 "Could not create temporary directory!"），所以这里用目录版——不需要
临时目录，启动也更快。整个 dist\\桌面宠物 目录一起拷走即可运行。

datas 只放 assets（内置立绘素材）。image/ 是"用户放自己图片"的目录，由程序在
exe 旁边自动建出来，这样用户能直接替换、也能看见，而不是藏在打包产物里面。
"""

block_cipher = None

a = Analysis(
    # 只把 desktop_pet.py 当入口。ai_client 是它 import 的模块，
    # 如果也写在这里，PyInstaller 会把 ai_client 的 __main__ 演示代码
    # 一起塞进包里当第二个入口（启动时会莫名多跑一段 API 自测）。
    ['desktop_pet.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/pet_gray_rgba.png', 'assets'),
           ('assets/pet_gray_flat.png', 'assets'),
           ('assets/pet_white_rgba.png', 'assets'),
           ('assets/pet_white_flat.png', 'assets'),
           ('assets/pet_black_rgba.png', 'assets'),
           ('assets/pet_black_flat.png', 'assets'),
           # 对话框左上角的校徽（tools/make_logo.py 生成）
           ('assets/school_logo.png', 'assets'),
           # 托盘图标：运行时用 LoadImageW 从文件加载，所以要带上这个文件
           # 设置窗口里的校徽（tools/build_badge.py 生成）
           ('assets/school_badge.png', 'assets'),
           ('assets/school_badge_faded.png', 'assets'),
           # 托盘 / exe / 窗口图标：校徽（tools/make_badge_ico.py 生成）
           ('assets/school_badge.ico', 'assets'),
           ('assets/pet.ico', 'assets')],
    hiddenimports=['PIL._tkinter_finder'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['numpy', 'pandas', 'matplotlib', 'scipy', 'pytest',
              'docx', 'pptx', 'openpyxl', 'xlsxwriter', 'lxml',
              'setuptools', 'pip', 'unittest', 'pydoc_data'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='桌面宠物',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/school_badge.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='桌面宠物',
)
