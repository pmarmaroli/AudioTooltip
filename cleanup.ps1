# AudioTooltip Cleanup Script

# Stop all running instances
Get-Process -Name "AudioTooltip" -ErrorAction SilentlyContinue | Stop-Process -Force

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
Remove-Item "$env:APPDATA\AudioTooltip" -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "AudioTooltip cleanup completed."