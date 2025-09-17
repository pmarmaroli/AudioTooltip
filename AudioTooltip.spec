# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# Try to import Azure Speech SDK (optional)
azure_datas = []
azure_binaries = []
azure_hiddenimports = []
azure_speech_dir = None

try:
    import azure.cognitiveservices.speech as speechsdk
    # Get Azure Speech SDK path to find native DLLs
    azure_speech_dir = os.path.dirname(speechsdk.__file__)
    # Collect all Azure Speech SDK files
    azure_datas, azure_binaries, azure_hiddenimports = collect_all(
        'azure.cognitiveservices.speech')
    print("Azure Speech SDK found - including in build")
except ImportError:
    print("Azure Speech SDK not found - building without speech transcription support")
    azure_datas = []
    azure_binaries = []
    azure_hiddenimports = []

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[
        # Explicitly include the Azure native DLL if available
        (os.path.join(azure_speech_dir, 'Microsoft.CognitiveServices.Speech.core.dll'),
         os.path.join('azure', 'cognitiveservices', 'speech'))
    ] + azure_binaries if azure_speech_dir else azure_binaries,
    datas=[
        ('resources', 'resources'),  # Include resources directory
    ] + azure_datas,
    hiddenimports=[
        'librosa', 'soundfile', 'numpy', 'matplotlib', 'pynput', 'keyboard',
        'scipy.io.wavfile', 'scipy.signal', 'matplotlib.backends.backend_agg',
        'mutagen', 'win32api', 'win32con', 'win32gui', 'win32com.client',
        'pythoncom', 'winreg', 'signal', 'subprocess', 'threading', 'traceback',
        'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets'
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='AudioTooltip',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Hide console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='resources/icons/app_icon.png',
)
