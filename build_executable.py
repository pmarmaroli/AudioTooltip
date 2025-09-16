#!/usr/bin/env python3
"""
Build script for AudioTooltip executable using PyInstaller
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

def clean_build_dirs():
    """Clean previous build directories"""
    dirs_to_clean = ['build', 'dist', '__pycache__']
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            print(f"Cleaning {dir_name}...")
            shutil.rmtree(dir_name)
    
    # Clean .pyc files
    for root, dirs, files in os.walk('.'):
        for file in files:
            if file.endswith('.pyc'):
                os.remove(os.path.join(root, file))

def build_executable():
    """Build the executable using PyInstaller"""
    
    # PyInstaller command with options
    cmd = [
        'pyinstaller',
        '--onefile',                    # Create a single executable file
        '--windowed',                   # Don't show console window
        '--name=AudioTooltip',          # Name of the executable
        '--icon=resources/icons/app_icon.png',  # Icon (if available)
        '--add-data=resources;resources',       # Include resources folder
        '--hidden-import=win32api',     # Explicitly include win32api
        '--hidden-import=win32gui',     # Explicitly include win32gui
        '--hidden-import=win32con',     # Explicitly include win32con
        '--hidden-import=keyboard',     # Explicitly include keyboard
        '--hidden-import=librosa',      # Explicitly include librosa
        '--hidden-import=soundfile',    # Explicitly include soundfile
        '--hidden-import=matplotlib',   # Explicitly include matplotlib
        '--collect-all=librosa',        # Collect all librosa files
        '--collect-all=soundfile',      # Collect all soundfile files
        'main.py'                       # Entry point
    ]
    
    print("Building executable...")
    print(f"Command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("Build successful!")
        print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Build failed with error code {e.returncode}")
        print("STDOUT:", e.stdout)
        print("STDERR:", e.stderr)
        return False

def main():
    """Main build process"""
    print("=== AudioTooltip Executable Builder ===")
    
    # Check if we're in the right directory
    if not os.path.exists('main.py'):
        print("Error: main.py not found. Please run this script from the AudioTooltip directory.")
        sys.exit(1)
    
    # Clean previous builds
    clean_build_dirs()
    
    # Build executable
    success = build_executable()
    
    if success:
        print("\n=== Build Complete! ===")
        print("Executable location: dist/AudioTooltip.exe")
        
        # Check if executable was created
        exe_path = Path("dist/AudioTooltip.exe")
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            print(f"Executable size: {size_mb:.2f} MB")
        else:
            print("Warning: Executable not found in expected location")
    else:
        print("\n=== Build Failed! ===")
        sys.exit(1)

if __name__ == "__main__":
    main()