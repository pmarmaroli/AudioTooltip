# -*- mode: python ; coding: utf-8 -*-

import azure.cognitiveservices.speech as speechsdk
import os
import sys
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# Get Azure Speech SDK path to find native DLLs
azure_speech_dir = os.path.dirname(speechsdk.__file__)

# Collect all Azure Speech SDK files
azure_datas, azure_binaries, azure_hiddenimports = collect_all(
    'azure.cognitiveservices.speech')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[
        # Explicitly include the native DLL
        (os.path.join(azure_speech_dir, 'Microsoft.CognitiveServices.Speech.core.dll'),
         os.path.join('azure', 'cognitiveservices', 'speech'))
    ] + azure_binaries,
    datas=[
        ('resources', 'resources'),  # Include resources directory
    ] + azure_datas,
    hiddenimports=[
        'librosa', 'soundfile', 'numpy', 'matplotlib', 'pynput', 'keyboard',
        'scipy.io.wavfile', 'scipy.signal', 'matplotlib.backends.backend_agg',
        'mutagen', 'win32api', 'win32con', 'win32gui', 'win32com.client',
        'pythoncom'
    ] + azure_hiddenimports,
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
    name='AudioTooltip',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Changed to False to hide console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='resources/icons/app_icon.png',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AudioTooltip',
)
