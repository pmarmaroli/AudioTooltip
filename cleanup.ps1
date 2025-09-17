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
# This ensures a thorough removal of AudioTooltip, making it easy to uninstall
# or prepare for a fresh installation.

# Stop all running instances
Get-Process -Name "AudioTooltip" -ErrorAction SilentlyContinue | Stop-Process -Force
# Also stop Python processes that might be running AudioTooltip
Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*main.py*" } | Stop-Process -Force

# Remove from startup registry
Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "AudioTooltip" -ErrorAction SilentlyContinue

# Potential installation directories
$installDirs = @(
    "$env:LOCALAPPDATA\AudioTooltip",
    "$env:PROGRAMFILES\AudioTooltip",
    "$env:PROGRAMFILES(X86)\AudioTooltip",
    "$env:USERPROFILE\Documents\AudioTooltip"
)

# Remove directories
foreach ($dir in $installDirs) {
    if (Test-Path $dir) {
        Remove-Item $dir -Recurse -Force
    }
}

# Remove logs and config
Remove-Item "$env:LOCALAPPDATA\AudioTooltip_Logs" -Recurse -Force -ErrorAction SilentlyContinue

# Remove QSettings registry entries
Remove-Item "HKCU:\Software\AudioTooltip" -Recurse -Force -ErrorAction SilentlyContinue

# Remove any temporary files
Remove-Item "$env:TEMP\AudioTooltip*" -Recurse -Force -ErrorAction SilentlyContinue

# Remove Desktop shortcuts
Remove-Item "$env:USERPROFILE\Desktop\AudioTooltip.lnk" -Force -ErrorAction SilentlyContinue

# Remove Start Menu shortcuts
$startMenuPaths = @(
    "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\AudioTooltip.lnk",
    "$env:ALLUSERSPROFILE\Microsoft\Windows\Start Menu\Programs\AudioTooltip.lnk"
)

foreach ($shortcut in $startMenuPaths) {
    Remove-Item $shortcut -Force -ErrorAction SilentlyContinue
}

# Try to remove the executable if it exists in current directory
$currentDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$exePath = Join-Path $currentDir "AudioTooltip.exe"
if (Test-Path $exePath) {
    try {
        Remove-Item $exePath -Force
        Write-Host "- Removed AudioTooltip.exe"
    } catch {
        Write-Host "- Note: AudioTooltip.exe could not be removed (may be in use). Please delete manually."
    }
}

Write-Host "AudioTooltip complete uninstallation completed."
Write-Host "- Stopped running processes"
Write-Host "- Removed from Windows startup"
Write-Host "- Cleaned installation directories"
Write-Host "- Removed logs and settings"
Write-Host "- Cleaned temporary files"
Write-Host "- Removed shortcuts"
Write-Host "- Attempted to remove executable"
Write-Host ""
Write-Host "AudioTooltip has been completely removed from your system."