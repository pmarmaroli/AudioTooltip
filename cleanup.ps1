# AudioTooltip Complete Uninstallation Script
#
# This script provides a complete uninstallation of AudioTooltip from your system.
# It removes:
#   - Running processes
#   - Windows startup entry (registry cleanup)
#   - All application settings and configuration files
#   - Application logs and cached files
#   - Temporary data
#   - Data from installation directories
#   - Desktop shortcuts (if any)
#   - Start Menu entries (if any)
#
# Usage: Right-click > Run with PowerShell, or:
#   powershell -ExecutionPolicy Bypass -File cleanup.ps1

# Self-elevate to admin if not already running as admin
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Requesting administrator privileges..."
    Start-Process PowerShell -ArgumentList "-ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    exit
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  AudioTooltip Uninstaller" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Stop all running instances
$stopped = Get-Process -Name "AudioTooltip" -ErrorAction SilentlyContinue
if ($stopped) {
    $stopped | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host "[OK] Stopped running AudioTooltip processes" -ForegroundColor Green
} else {
    Write-Host "[--] No running AudioTooltip processes found" -ForegroundColor Gray
}

# Also stop Python processes that might be running AudioTooltip
Get-Process -Name "python" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*main.py*" } |
    Stop-Process -Force -ErrorAction SilentlyContinue

# Remove from startup registry
$startupEntry = Get-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "AudioTooltip" -ErrorAction SilentlyContinue
if ($startupEntry) {
    Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "AudioTooltip" -ErrorAction SilentlyContinue
    Write-Host "[OK] Removed from Windows startup" -ForegroundColor Green
} else {
    Write-Host "[--] No startup entry found" -ForegroundColor Gray
}

# Potential installation directories
$installDirs = @(
    "$env:LOCALAPPDATA\AudioTooltip",
    "$env:PROGRAMFILES\AudioTooltip",
    "${env:PROGRAMFILES(X86)}\AudioTooltip",
    "$env:USERPROFILE\Documents\AudioTooltip"
)

foreach ($dir in $installDirs) {
    if (Test-Path $dir) {
        Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "[OK] Removed directory: $dir" -ForegroundColor Green
    }
}

# Remove logs and config
if (Test-Path "$env:LOCALAPPDATA\AudioTooltip_Logs") {
    Remove-Item "$env:LOCALAPPDATA\AudioTooltip_Logs" -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "[OK] Removed logs" -ForegroundColor Green
}

# Remove QSettings registry entries (organization name used by app)
$regPaths = @(
    "HKCU:\Software\AudioTooltip",
    "HKCU:\Software\MCDE - FHL 2025"
)
foreach ($regPath in $regPaths) {
    if (Test-Path $regPath) {
        Remove-Item $regPath -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "[OK] Removed registry: $regPath" -ForegroundColor Green
    }
}

# Remove any temporary files (PyInstaller extraction cache)
$tempItems = Get-ChildItem "$env:TEMP" -Filter "AudioTooltip*" -ErrorAction SilentlyContinue
$meiItems = Get-ChildItem "$env:TEMP" -Filter "_MEI*" -ErrorAction SilentlyContinue
if ($tempItems) {
    Remove-Item "$env:TEMP\AudioTooltip*" -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "[OK] Removed temporary files" -ForegroundColor Green
}
if ($meiItems) {
    $meiItems | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "[OK] Removed PyInstaller extraction cache" -ForegroundColor Green
}

# Remove Desktop shortcuts
if (Test-Path "$env:USERPROFILE\Desktop\AudioTooltip.lnk") {
    Remove-Item "$env:USERPROFILE\Desktop\AudioTooltip.lnk" -Force -ErrorAction SilentlyContinue
    Write-Host "[OK] Removed desktop shortcut" -ForegroundColor Green
}

# Remove Start Menu shortcuts
$startMenuPaths = @(
    "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\AudioTooltip.lnk",
    "$env:ALLUSERSPROFILE\Microsoft\Windows\Start Menu\Programs\AudioTooltip.lnk"
)
foreach ($shortcut in $startMenuPaths) {
    if (Test-Path $shortcut) {
        Remove-Item $shortcut -Force -ErrorAction SilentlyContinue
        Write-Host "[OK] Removed shortcut: $shortcut" -ForegroundColor Green
    }
}

# Try to remove the executable if it exists in current directory
$currentDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$exePath = Join-Path $currentDir "AudioTooltip.exe"
if (Test-Path $exePath) {
    try {
        Remove-Item $exePath -Force
        Write-Host "[OK] Removed AudioTooltip.exe" -ForegroundColor Green
    } catch {
        Write-Host "[!!] AudioTooltip.exe could not be removed (may be in use). Please delete manually." -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  AudioTooltip has been removed." -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press any key to close..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
