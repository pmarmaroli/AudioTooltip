@echo off
echo Building AudioTooltip executable...
echo.

REM Clean previous build
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"

REM Build the executable using PyInstaller
pyinstaller AudioTooltip.spec --clean

REM Check if build was successful
if not exist "dist\AudioTooltip.exe" (
    echo ERROR: Build failed! AudioTooltip.exe not found in dist folder.
    pause
    exit /b 1
)

echo.
echo Build successful! Copying additional files...

REM Copy additional files to dist folder
copy "cleanup.ps1" "dist\" >nul
copy "installation-guide.md" "dist\" >nul

echo.
echo ✓ AudioTooltip.exe created
echo ✓ cleanup.ps1 copied to dist folder
echo ✓ installation-guide.md copied to dist folder
echo.
echo Release files are ready in the 'dist' folder!
echo.

REM List the contents of dist folder
echo Contents of dist folder:
dir "dist" /b

echo.
echo Build complete!
pause