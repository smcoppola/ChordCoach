# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

import sys
import os
import glob
from PyInstaller.utils.hooks import collect_all

is_win = sys.platform.startswith('win')
is_mac = sys.platform == 'darwin'

def find_file(pattern, default):
    matches = glob.glob(pattern)
    return matches[0] if matches else default

if is_win:
    hw_ext_path = find_file('build/src/hardware/Release/chordcoach_hw*.pyd', 'build/src/hardware/Release/chordcoach_hw.pyd')
    rtmidi_lib_path = 'build/_deps/rtmidi-build/Release/rtmidi.dll'
    app_icon = 'resources/icon.ico'
elif is_mac:
    hw_ext_path = find_file('build/src/hardware/chordcoach_hw*.so', 'build/src/hardware/chordcoach_hw.so') 
    rtmidi_lib_path = 'build/_deps/rtmidi-build/librtmidi.dylib'
    app_icon = 'resources/icon.png'
else:
    hw_ext_path = find_file('build/src/hardware/chordcoach_hw*.so', 'build/src/hardware/chordcoach_hw.so')
    rtmidi_lib_path = 'build/_deps/rtmidi-build/librtmidi.so'
    app_icon = 'resources/icon.png'

# Essential UI and Resource files
datas_list = []
if os.path.isdir('src/ui'):
    datas_list.append(('src/ui', 'ui'))
if os.path.isdir('src/resources'):
    datas_list.append(('src/resources', 'src/resources'))

# Database folder (optional at build time)
if os.path.isdir('database'):
    datas_list.append(('database', 'database'))

# Configuration and Icon
if os.path.exists('.env'):
    datas_list.append(('.env', '.'))
if os.path.exists(app_icon):
    datas_list.append((app_icon, 'resources'))

binaries_list = []
if os.path.exists(hw_ext_path):
    binaries_list.append((hw_ext_path, '.'))
if os.path.exists(rtmidi_lib_path):
    binaries_list.append((rtmidi_lib_path, '.'))

# Collect music21 and pretty_midi assets
m21_datas, m21_binaries, m21_hiddenimports = collect_all('music21')
pm_datas, pm_binaries, pm_hiddenimports = collect_all('pretty_midi')

# Filter music21 data to exclude bulky assets (corpus, docs, tests)
m21_excluded_dirs = ['corpus', 'test', 'documentation', 'demos']
filtered_m21_datas = []
excluded_count = 0
for src, dst in m21_datas:
    # Normalize paths for comparison
    src_norm = src.replace('\\', '/').lower()
    if any(f"/music21/{d}/" in src_norm or f"\\music21\\{d}\\" in src.lower() for d in m21_excluded_dirs):
        excluded_count += 1
        continue
    filtered_m21_datas.append((src, dst))

print(f"PyInstaller Spec: Excluded {excluded_count} music21 assets (corpus, tests, docs).")
m21_datas = filtered_m21_datas

datas_list += m21_datas + pm_datas
binaries_list += m21_binaries + pm_binaries

a = Analysis(
    ['src/app.py'],
    pathex=[os.path.abspath(os.path.join(SPECPATH, 'src'))],
    binaries=binaries_list,
    datas=datas_list,
    hiddenimports=[
        'PySide6.QtQml', 
        'PySide6.QtQuick', 
        'PySide6.QtCore', 
        'PySide6.QtGui', 
        'PySide6.QtNetwork', 
        'PySide6.QtWebEngineCore', 
        'PySide6.QtWebEngineQuick',
        'PySide6.QtMultimedia',
        'bs4',
        'requests',
        'mido',
        'pretty_midi',
        'websockets',
        'certifi',
        'music21',
        'numpy',
        'logic.services.gemini_service', 
        'logic.services.midi_ingestor', 
        'logic.services.repertoire_crawler', 
        'logic.services.database_manager', 
        'logic.services.chord_trainer', 
        'logic.services.evaluation_service', 
        'logic.services.adaptive_engine', 
        'logic.services.settings_service',
        'logic.services.curriculum_service',
        'logic.services.metronome_service',
        'logic.services.circle_of_fifths_service',
        'logic.services.music21_service',
        'logic.utils.corpus_indexer',
        'logic.utils.fingering_optimizer',
        'logic.coordinators.app_coordinator',
        'hardware.midi_hardware_service',
        'core.bootstrap'
    ] + m21_hiddenimports + pm_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='ChordCoachCompanionPortable',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # Windowed on every platform. A console build put a black terminal next to
    # the UI on Windows for no user-facing benefit: nothing reads stdin, and
    # bootstrap.setup_logging tees all output to
    # <user data>/logs/chordcoach.log, which is where frozen-build
    # troubleshooting should look anyway. Do not set this back to True to debug
    # a build — read the log.
    console=False,
    icon=app_icon,
    # Keep False: it is what still raises a dialog for an unhandled exception in
    # a windowed build, instead of the process vanishing silently.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='arm64' if is_mac else None,
    codesign_identity=None,
    entitlements_file='entitlements.plist' if is_mac else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ChordCoachCompanionPortable',
)

if is_mac:
    app = BUNDLE(
        coll,
        name='ChordCoachCompanion.app',
        icon=app_icon,
        bundle_identifier='com.chordcoach.companion',
        info_plist={
            'CFBundleShortVersionString': '1.0.0',
            'CFBundleVersion': '1.0.0',
            'NSPrincipalClass': 'NSApplication',
            'LSApplicationCategoryType': 'public.app-category.music-education',
            'NSHumanReadableCopyright': 'Copyright \u00a9 2026 ChordCoach Team',
            'NSHighResolutionCapable': True,
        },
    )
