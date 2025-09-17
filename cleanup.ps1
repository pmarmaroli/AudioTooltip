# AudioTooltip Cleanup Script
#
# This script CLEANS UP AudioTooltip data and settings but does NOT uninstall the program.
# It removes:
#   - Running processes
#   - Windows startup entry
#   - Application logs (if logging was enabled) and settings
#   - Temporary files
#   - Data from common installation directories
#
# It does NOT remove:
#   - The main AudioTooltip.exe executable
#   - Desktop shortcuts
#   - Start Menu entries
#
# Use this for: Reset to defaults, troubleshooting, or preparing for clean reinstall
# For complete removal: Also manually delete AudioTooltip.exe and any shortcuts

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

Write-Host "AudioTooltip cleanup completed."
Write-Host "- Stopped running processes"
Write-Host "- Removed from Windows startup"
Write-Host "- Cleaned installation directories"
Write-Host "- Removed logs and settings"
Write-Host "- Cleaned temporary files"