@echo off
setlocal enabledelayedexpansion

REM Always run from the directory containing this script
cd /d "%~dp0"

echo ============================================
echo  AudioTooltip Build Script
echo ============================================
echo.

REM ── 0. Ask for version number ────────────────────────────────────────────────
REM Read current version from main.py for display
for /f "tokens=*" %%a in ('python -c "import re; content=open('main.py').read(); m=re.search(r'v(\d+\.\d+\.\d+)', content); print(m.group(1) if m else 'unknown')" 2^>nul') do set CURRENT_VERSION=%%a

echo Current version in code: v%CURRENT_VERSION%
echo.
set /p VERSION="Enter new version number (e.g. 3.1.0), or press Enter to keep v%CURRENT_VERSION%: "

REM If user pressed Enter without typing, keep current version
if "!VERSION!"=="" (
    set VERSION=%CURRENT_VERSION%
    echo [OK] Keeping current version: v!VERSION!
) else (
    REM Validate format: must match digits.digits.digits
    echo !VERSION! | findstr /r "^[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*$" >nul
    if errorlevel 1 (
        echo [ERROR] Invalid version format "!VERSION!". Expected format: MAJOR.MINOR.PATCH (e.g. 3.1.0)
        pause
        exit /b 1
    )
    echo [OK] New version: v!VERSION!
)
echo.

REM ── 1. Check Python ──────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [INFO] Python not found. Attempting to install via winget...
    winget install Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo.
        echo [ERROR] Could not install Python automatically.
        echo         Please install Python 3.11 from https://www.python.org/downloads/
        echo         Make sure to check "Add Python to PATH" during installation.
        pause
        exit /b 1
    )
    REM Reload PATH so python is found in this session
    for /f "tokens=*" %%i in ('where python 2^>nul') do set PYTHON_EXE=%%i
    if "!PYTHON_EXE!"=="" (
        echo [ERROR] Python installed but still not found in PATH.
        echo         Please close this window, reopen a new command prompt, and run again.
        pause
        exit /b 1
    )
)
echo [OK] Python found:
python --version
echo.

REM ── 2. Patch version string in main.py ───────────────────────────────────────
echo [INFO] Updating version string in main.py to v!VERSION!...
python -c "
import re, sys
path = 'main.py'
content = open(path, encoding='utf-8').read()
new_content = re.sub(r'v\d+\.\d+\.\d+(\s*-\s*Audio Analysis Tool)', r'v%VERSION%\1', content)
if new_content == content:
    print('WARNING: version pattern not found in main.py — no change made')
    sys.exit(0)
open(path, 'w', encoding='utf-8').write(new_content)
print('OK')
"
if errorlevel 1 (
    echo [ERROR] Failed to patch version in main.py.
    pause
    exit /b 1
)
echo [OK] main.py updated.
echo.

REM ── 3. Create virtual environment if needed ──────────────────────────────────
set VENV_DIR=.venv

if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo [INFO] Creating virtual environment in %VENV_DIR%...
    python -m venv %VENV_DIR%
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created.
) else (
    echo [OK] Virtual environment already exists.
)
echo.

REM ── 4. Activate virtual environment ──────────────────────────────────────────
call "%VENV_DIR%\Scripts\activate.bat"
echo [OK] Virtual environment activated: %VIRTUAL_ENV%
echo.

REM ── 5. Upgrade pip quietly ───────────────────────────────────────────────────
echo [INFO] Upgrading pip...
python -m pip install --upgrade pip --quiet
echo [OK] pip up to date.
echo.

REM ── 6. Install project requirements ─────────────────────────────────────────
echo [INFO] Installing requirements from requirements.txt...
python -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install requirements.
    pause
    exit /b 1
)
echo [OK] Requirements installed.
echo.

REM ── 7. Install PyInstaller if not already present ────────────────────────────
python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [INFO] PyInstaller not found — installing...
    python -m pip install pyinstaller --quiet
    if errorlevel 1 (
        echo [ERROR] Failed to install PyInstaller.
        pause
        exit /b 1
    )
    echo [OK] PyInstaller installed.
) else (
    echo [OK] PyInstaller already present.
)
echo.

REM ── 8. Clean previous build artifacts ────────────────────────────────────────
echo [INFO] Cleaning previous build...
if exist "dist"  rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"
echo [OK] Clean done.
echo.

REM ── 9. Run PyInstaller ───────────────────────────────────────────────────────
echo [INFO] Building executable...
echo.
python -m PyInstaller AudioTooltip.spec --clean
if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller build failed. Check output above for details.
    pause
    exit /b 1
)

REM ── 10. Verify output ────────────────────────────────────────────────────────
if not exist "dist\AudioTooltip.exe" (
    echo [ERROR] Build failed — AudioTooltip.exe not found in dist folder.
    pause
    exit /b 1
)

REM ── 11. Copy additional release files ────────────────────────────────────────
echo.
echo [INFO] Copying release files...
copy "cleanup.ps1"           "dist\" >nul
copy "installation-guide.md" "dist\" >nul
echo [OK] Additional files copied.

REM ── Done ─────────────────────────────────────────────────────────────────────
echo.
echo ============================================
echo  Build successful!  v!VERSION!
echo ============================================
echo.
echo   dist\AudioTooltip.exe  ^<-- ready
echo   dist\cleanup.ps1
echo   dist\installation-guide.md
echo.
echo Contents of dist folder:
dir "dist" /b
echo.
echo Next steps:
echo   git add main.py
echo   git commit -m "chore: bump version to v!VERSION!"
echo   git tag v!VERSION!
echo   git push ^&^& git push --tags
echo.
pause
