@echo off
setlocal
cd /d "%~dp0"

set VENV_DIR=.venv
set TITLE=AudioTooltip Dev

title %TITLE%
echo ============================================
echo  %TITLE%
echo ============================================
echo.

REM -- 1. Preflight: Python --
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    echo         Install Python 3.11+ and ensure "Add to PATH" is checked.
    pause
    exit /b 1
)
echo [OK] Python found: & python --version
echo.

REM -- 2. Bootstrap venv + deps --
if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo [INFO] Creating virtual environment...
    python -m venv %VENV_DIR%
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created.
    echo.
)

call "%VENV_DIR%\Scripts\activate.bat"
echo [OK] venv activated: %VIRTUAL_ENV%

REM Install/sync deps only when requirements.txt is newer than a stamp file
set STAMP=%VENV_DIR%\.deps-installed
if not exist "%STAMP%" goto :install_deps
for /f %%A in ('powershell -NoProfile -Command "(Get-Item requirements.txt).LastWriteTime -gt (Get-Item '%STAMP%').LastWriteTime"') do (
    if /i "%%A"=="True" goto :install_deps
)
echo [OK] Dependencies up to date.
goto :deps_done

:install_deps
echo [INFO] Installing dependencies...
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)
echo. > "%STAMP%"
echo [OK] Dependencies installed.

:deps_done
echo.

REM -- 3. Launch --
echo [INFO] Starting AudioTooltip...
echo         Press Ctrl+C to stop.
echo.
python main.py %*
set EXIT_CODE=%ERRORLEVEL%

REM -- 4. Handoff --
echo.
if %EXIT_CODE% neq 0 (
    echo [WARN] AudioTooltip exited with code %EXIT_CODE%.
) else (
    echo [OK] AudioTooltip stopped.
)
pause
