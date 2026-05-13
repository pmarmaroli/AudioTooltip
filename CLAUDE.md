# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AudioTooltip is a Windows-only desktop application (PyQt5) that analyzes audio files via system tray hotkeys (Alt+A, Alt+D) or drag-and-drop. It displays waveforms, spectrograms, metadata, and optional Azure speech transcription in a tooltip UI. Built with PyInstaller into a single .exe.

## Build & Run Commands

```bash
# Run from source (requires Python 3.11+)
start.bat              # Creates .venv, installs deps, launches main.py

# Or manually:
pip install -r requirements.txt
python main.py

# Build release (Windows only, prompts for version)
scripts\build_release.bat

# Version management
python scripts/build_version.py --read          # Read current version
python scripts/build_version.py --patch X.Y.Z  # Patch version in main.py
```

## Architecture

```
main.py                        # Entry point, AudioTooltipApp, worker threads, drop target
core/audio_analyzer.py         # AudioAnalyzer: librosa loading, waveform/spectrogram generation
core/audio_playback.py         # Audio playback functionality
ui/tooltip.py                  # EnhancedTooltip: multi-tab display (overview, visualizations, transcript)
ui/settings_dialog.py          # Settings UI (analysis, transcription, startup preferences)
ui/progress_dialog.py          # Progress indicator widget
utils/file_utils.py            # File validation, recent files, supported format list
utils/logging_utils.py         # Logging configuration
utils/startup_utils.py         # Windows registry auto-startup management
scripts/build_release.bat      # Release build script (PyInstaller)
scripts/upload_release.bat     # Release upload script (GitHub CLI)
scripts/build_version.py       # Version read/patch utility
scripts/cleanup.ps1            # Uninstall/cleanup script
start.bat                      # Dev launcher: venv bootstrap, dep sync, run
```

**Key patterns:**
- PyQt5 signal/slot for component communication
- Worker threads (TranscriptionWorker, AudioTooltipWorker) to keep UI responsive
- QSettings for persistent user preferences
- Windows-specific: pywin32 for window management, pynput/keyboard for global hotkeys

## Version Location

The version string lives in `main.py` in the `__main__` block near the end of the file:
```python
painter.drawText(20, 80, "vX.Y.Z - Audio Analysis Tool")
```
Use `scripts/build_version.py` to read/patch it — don't edit manually.

## Supported Audio Formats

MP3, WAV, FLAC, OGG, M4A, WMA, AAC, AIFF, MP4, APE, Opus, WV

## No Test Suite

There are no automated tests. Manual testing uses the included `resources/test_audio.wav`.

## Platform Constraint

This application is Windows-only. All file paths, hotkey handling, and system tray integration depend on Windows APIs.
