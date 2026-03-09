@echo off
setlocal enabledelayedexpansion

echo ============================================
echo  AudioTooltip Build Script
echo ============================================
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

REM ── 2. Create virtual environment if needed ──────────────────────────────────
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

REM ── 3. Activate virtual environment ──────────────────────────────────────────
call "%VENV_DIR%\Scripts\activate.bat"
echo [OK] Virtual environment activated: %VIRTUAL_ENV%
echo.

REM ── 4. Upgrade pip quietly ───────────────────────────────────────────────────
echo [INFO] Upgrading pip...
python -m pip install --upgrade pip --quiet
echo [OK] pip up to date.
echo.

REM ── 5. Install project requirements ─────────────────────────────────────────
echo [INFO] Installing requirements from requirements.txt...
python -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install requirements.
    pause
    exit /b 1
)
echo [OK] Requirements installed.
echo.

REM ── 6. Install PyInstaller if not already present ────────────────────────────
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

REM ── 7. Clean previous build artifacts ────────────────────────────────────────
echo [INFO] Cleaning previous build...
if exist "dist"  rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"
echo [OK] Clean done.
echo.

REM ── 8. Run PyInstaller ───────────────────────────────────────────────────────
echo [INFO] Building executable...
echo.
python -m PyInstaller AudioTooltip.spec --clean
if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller build failed. Check output above for details.
    pause
    exit /b 1
)

REM ── 9. Verify output ─────────────────────────────────────────────────────────
if not exist "dist\AudioTooltip.exe" (
    echo [ERROR] Build failed — AudioTooltip.exe not found in dist folder.
    pause
    exit /b 1
)

REM ── 10. Copy additional release files ────────────────────────────────────────
echo.
echo [INFO] Copying release files...
copy "cleanup.ps1"           "dist\" >nul
copy "installation-guide.md" "dist\" >nul
echo [OK] Additional files copied.

REM ── Done ─────────────────────────────────────────────────────────────────────
echo.
echo ============================================
echo  Build successful!
echo ============================================
echo.
echo   AudioTooltip.exe  ^<-- ready in dist\
echo   cleanup.ps1
echo   installation-guide.md
echo.
echo Contents of dist folder:
dir "dist" /b
echo.
pause
