# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['gui/app.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('export/epub_style.css', 'export'),
        ('cli/run_crawl.py', 'cli'),
    ],
    hiddenimports=[
        'twisted.internet',
        'twisted.internet.asyncioreactor',
        'twisted.internet.selectreactor',
        'twisted.internet.epollreactor',
        'scrapy.extensions.logstats',
        'scrapy.extensions.corestats',
        'scrapy.extensions.telnet',
        'scrapy.spidermiddlewares',
        'scrapy.downloadermiddlewares',
    ],
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
