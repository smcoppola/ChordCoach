# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

import sys
import os
import glob

is_win = sys.platform.startswith('win')
is_mac = sys.platform == 'darwin'

def find_file(pattern, default):
    matches = glob.glob(pattern)
    return matches[0] if matches else default

if is_win:
    hw_ext_path = find_file('build/src/hardware/Release/chordcoach_hw*.pyd', 'build/src/hardware/Release/chordcoach_hw.pyd')
    rtmidi_lib_path = 'build/_deps/rtmidi-build/Release/rtmidi.dll'
    portaudio_lib_path = 'build/_deps/portaudio-build/Release/portaudio.dll'
    app_icon = 'resources/icon.ico'
elif is_mac:
    # Use wildcards or assume typical CMake output paths for macOS
    hw_ext_path = find_file('build/src/hardware/chordcoach_hw*.so', 'build/src/hardware/chordcoach_hw.so') 
    rtmidi_lib_path = 'build/_deps/rtmidi-build/librtmidi.dylib'
    portaudio_lib_path = 'build/_deps/portaudio-build/libportaudio.dylib'
    app_icon = 'resources/icon.png'
else:
    hw_ext_path = find_file('build/src/hardware/chordcoach_hw*.so', 'build/src/hardware/chordcoach_hw.so')
    rtmidi_lib_path = 'build/_deps/rtmidi-build/librtmidi.so'
    portaudio_lib_path = 'build/_deps/portaudio-build/libportaudio.so'
    app_icon = 'resources/icon.png'

# Paths to assets
hw_extension = (hw_ext_path, '.')
rtmidi_dll = (rtmidi_lib_path, '.')
portaudio_dll = (portaudio_lib_path, '.')
ui_files = (
    'src/ui',
    'ui'
)
database_folder = (
    'database',
    'database'
)
env_file = (
    '.env',
    '.'
)
icon_file = (
    app_icon,
    'resources'
)

datas_list = [ui_files, database_folder]
if os.path.exists('.env'):
    datas_list.append(env_file)
if os.path.exists(app_icon):
    datas_list.append(icon_file)

binaries_list = [hw_extension]
if os.path.exists(rtmidi_lib_path):
    binaries_list.append(rtmidi_dll)
if os.path.exists(portaudio_lib_path):
    binaries_list.append(portaudio_dll)

a = Analysis(
    ['src/app.py'],
    pathex=['src'],
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
        'logic.services.gemini_service', 
        'logic.services.midi_ingestor', 
        'logic.services.repertoire_crawler', 
        'logic.services.database_manager', 
        'logic.services.chord_trainer', 
        'logic.services.evaluation_service', 
        'logic.services.adaptive_engine', 
        'logic.services.settings_service'
    ],
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
    console=True,
    icon=app_icon,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
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
        coll, # In macOS BUNDLE on a dir, we pass coll or exe depending on PyInstaller version. Typically exe.
        name='ChordCoachCompanion.app',
        icon=app_icon,
        bundle_identifier='com.chordcoach.companion',
        info_plist={
            'NSMicrophoneUsageDescription': 'Required for AI voice interaction',
            'NSCameraUsageDescription': 'Optional for future features',
        },
    )
