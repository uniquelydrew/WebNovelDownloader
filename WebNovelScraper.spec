# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None
project_root = Path(SPECPATH)

playwright_datas, playwright_binaries, playwright_hiddenimports = collect_all('playwright')

browser_root = os.environ.get('PLAYWRIGHT_BROWSERS_PATH')
browser_datas = []
if browser_root and Path(browser_root).exists():
    for path in Path(browser_root).rglob('*'):
        if path.is_file():
            relative_parent = path.relative_to(browser_root).parent
            target_dir = Path('playwright-browsers') / relative_parent
            browser_datas.append((str(path), str(target_dir)))

hiddenimports = [
    'twisted.internet',
    'twisted.internet.asyncioreactor',
    'twisted.internet.selectreactor',
    'twisted.internet.epollreactor',
    'scrapy.extensions.logstats',
    'scrapy.extensions.corestats',
    'scrapy.extensions.telnet',
    'scrapy.spidermiddlewares',
    'scrapy.downloadermiddlewares',
]
hiddenimports += playwright_hiddenimports
hiddenimports += collect_submodules('scrapy')
hiddenimports += collect_submodules('twisted.internet')


a = Analysis(
    ['gui/app.py'],
    pathex=[str(project_root)],
    binaries=playwright_binaries,
    datas=[
        ('export/epub_style.css', 'export'),
    ] + playwright_datas + browser_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='WebNovelScraper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='WebNovelScraper',
)
