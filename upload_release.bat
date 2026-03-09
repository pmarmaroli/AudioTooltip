@echo off
setlocal enabledelayedexpansion

REM Always run from the directory containing this script
cd /d "%~dp0"

echo ============================================
echo  AudioTooltip Release Upload Script
echo ============================================
echo.

REM ── 1. Check GitHub CLI ────────────────────────────────────────────────────
where gh >nul 2>&1
if errorlevel 1 (
    echo [INFO] GitHub CLI ^(gh^) not found. Attempting to install...

    REM Try winget first
    where winget >nul 2>&1
    if not errorlevel 1 (
        echo [INFO] Installing via winget...
        winget install GitHub.cli --silent --accept-package-agreements --accept-source-agreements
    )

    REM If still not found, download with PowerShell
    where gh >nul 2>&1
    if errorlevel 1 (
        echo [INFO] Downloading GitHub CLI installer...
        powershell -NoProfile -Command ^
            "$url = (Invoke-RestMethod 'https://api.github.com/repos/cli/cli/releases/latest').assets | Where-Object { $_.name -match 'windows_amd64.msi' } | Select-Object -First 1 -ExpandProperty browser_download_url; " ^
            "Write-Host \"Downloading $url\"; " ^
            "Invoke-WebRequest -Uri $url -OutFile \"$env:TEMP\gh_installer.msi\" -UseBasicParsing"
        if errorlevel 1 (
            echo [ERROR] Failed to download GitHub CLI.
            echo         Please install it manually from https://cli.github.com/
            pause
            exit /b 1
        )
        echo [INFO] Installing GitHub CLI...
        msiexec /i "%TEMP%\gh_installer.msi" /quiet /norestart
        if errorlevel 1 (
            echo [ERROR] MSI installation failed. Trying interactive install...
            msiexec /i "%TEMP%\gh_installer.msi"
        )
        del "%TEMP%\gh_installer.msi" >nul 2>&1
    )

    REM Refresh PATH for this session
    set "PATH=%PATH%;%ProgramFiles%\GitHub CLI;%LOCALAPPDATA%\Programs\GitHub CLI"
    where gh >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] GitHub CLI installed but not found in PATH.
        echo         Please close this window, reopen a new command prompt, and run again.
        pause
        exit /b 1
    )
)
echo [OK] GitHub CLI found:
gh --version
echo.

REM ── 2. Check gh authentication ─────────────────────────────────────────────
gh auth status >nul 2>&1
if errorlevel 1 (
    echo [INFO] Not logged in to GitHub. Starting login...
    gh auth login
    if errorlevel 1 (
        echo [ERROR] GitHub authentication failed.
        pause
        exit /b 1
    )
)
echo [OK] Authenticated with GitHub.
echo.

REM ── 3. Read version from main.py ───────────────────────────────────────────
for /f "tokens=*" %%a in ('python build_version.py --read 2^>nul') do set VERSION=%%a

if "!VERSION!"=="" (
    echo [ERROR] Could not read version from main.py.
    pause
    exit /b 1
)
echo [OK] Version: v!VERSION!
echo.

REM ── 4. Verify dist folder contents ─────────────────────────────────────────
if not exist "dist\AudioTooltip.exe" (
    echo [ERROR] dist\AudioTooltip.exe not found.
    echo         Run build_release.bat first.
    pause
    exit /b 1
)
echo [OK] dist\AudioTooltip.exe found.
echo.

REM ── 5. Create zip archive ──────────────────────────────────────────────────
set ZIP_NAME=AudioTooltip-v!VERSION!.zip
if exist "dist\!ZIP_NAME!" del "dist\!ZIP_NAME!"

echo [INFO] Creating !ZIP_NAME!...
powershell -NoProfile -Command "Compress-Archive -Path 'dist\AudioTooltip.exe','dist\cleanup.ps1','dist\installation-guide.md' -DestinationPath 'dist\!ZIP_NAME!' -Force"
if errorlevel 1 (
    echo [ERROR] Failed to create zip archive.
    pause
    exit /b 1
)
echo [OK] Archive created: dist\!ZIP_NAME!
echo.

REM ── 6. Commit version bump and tag ─────────────────────────────────────────
echo [INFO] Checking git status...
git diff --quiet main.py >nul 2>&1
if errorlevel 1 (
    echo [INFO] Committing version bump...
    git add main.py
    git commit -m "chore: bump version to v!VERSION!"
    if errorlevel 1 (
        echo [ERROR] Git commit failed.
        pause
        exit /b 1
    )
    echo [OK] Version bump committed.
) else (
    echo [OK] main.py already committed.
)
echo.

REM Check if tag already exists
git rev-parse "v!VERSION!" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Creating tag v!VERSION!...
    git tag "v!VERSION!"
    echo [OK] Tag created.
) else (
    echo [OK] Tag v!VERSION! already exists.
)
echo.

REM ── 7. Push to remote ──────────────────────────────────────────────────────
echo [INFO] Pushing to remote...
git push && git push --tags
if errorlevel 1 (
    echo [ERROR] Git push failed.
    pause
    exit /b 1
)
echo [OK] Pushed to remote.
echo.

REM ── 8. Create GitHub release ────────────────────────────────────────────────
echo [INFO] Creating GitHub release v!VERSION!...
gh release create "v!VERSION!" "dist\!ZIP_NAME!" --repo pmarmaroli/AudioTooltip --title "AudioTooltip v!VERSION!" --generate-notes
if errorlevel 1 (
    echo [ERROR] Failed to create GitHub release.
    echo         You may need to delete an existing v!VERSION! release first.
    pause
    exit /b 1
)

REM ── Done ────────────────────────────────────────────────────────────────────
echo.
echo ============================================
echo  Release v!VERSION! uploaded successfully!
echo ============================================
echo.
echo   https://github.com/pmarmaroli/AudioTooltip/releases/tag/v!VERSION!
echo.
pause
