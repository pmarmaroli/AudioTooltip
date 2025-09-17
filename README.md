# Audio Tooltip

Audio Tooltip is a desktop application that gives you quick information on audio files without needing to open complex audio editing software.

## What It Does

The app runs quietly in your system tray (the small icons area near your clock) and gives you instant information about audio files with a simple keyboard shortcut (Alt+A). When you select an audio file and press this shortcut, a small window (tooltip) pops up showing:

1. Basic information about the audio file (length, format, etc.)
2. Visual representations of the sound (waveforms and spectrograms)
3. Written transcript of any speech in the audio (like subtitles)

## How To Use It

There are several ways to analyze audio files:

1. **Keyboard shortcut**: Select a file in Windows Explorer and press Alt+A
2. **Middle-click detection**: Hold middle-click on any audio file in Windows Explorer  
3. **System tray**: Right-click the app's icon for menu, middle-click for quick file dialog
4. **Drop target window**: Press Alt+D to open a drop target window and drag-and-drop audio files onto it

## Watch our Youtube Demo

[![IMAGE ALT TEXT](http://img.youtube.com/vi/xclEy1SetjA/0.jpg)](http://www.youtube.com/watch?v=xclEy1SetjA "Video Title")

## Main Features

- **Overview**: Basic information and waveform display.
- **Visualizations**: Various audio visualizations (spectrogram, mel-spectrogram, chromagram, double waveform)
- **Full Audio Transcription**: Speech-to-text via Azure Speech Services with continuous recognition for files of any length
- **Simple interface**: Everything is organized in tabs for easy navigation

Additional controls:

- Play a short preview of the audio
- Open the full file in Audacity or your default audio player
- Pin the tooltip to keep it visible
- Switch between channels for multi-channel audio
- Save analysis results to files

## Keyboard Shortcuts

- **Alt+A**: Analyze the currently selected audio file in Windows Explorer
- **Alt+D**: Open the drop target window for drag-and-drop file analysis

## Why It's Useful

We hope this tool can be helpful for:

- Audio engineers wanting quick insights into sound files
- Podcast editors checking audio quality before detailed editing
- Musicians analyzing sound characteristics
- Anyone who works with audio and needs quick information without opening large programs

## Application Interface

![Audio Tooltip interface showing waveform analysis](screenshots/interface.png)
![Audio Tooltip interface showing waveform analysis](screenshots/visualization.png)

## Project Structure

```
audio-analyzer/
│
├── core/                      # Core analysis functionality
│   ├── audio_analyzer.py      # Audio loading, analysis, and feature extraction
│   └── audio_playback.py      # Audio playback functionality
│
├── ui/                        # User interface components
│   ├── tooltip.py             # Main tooltip display
│   ├── settings_dialog.py     # Settings configuration
│   └── progress_dialog.py     # Progress indicators
│
├── utils/                     # Utility functions
│   ├── file_utils.py          # File handling utilities
│   └── logging_utils.py       # Logging configuration
│
├── resources/                 # Application resources
│   └── icons/                 # Application icons
│
├── main.py                    # Application entry point
├── README.md                  # Project documentation
└── requirements.txt           # Dependencies
```

## System Requirements

### Operating System
- **Windows 7 or later** (Windows 10/11 recommended)
- **macOS and Linux are NOT supported**

AudioTooltip is designed specifically for Windows and uses Windows-specific features that are not available on other operating systems:
- Windows Registry integration for auto-startup
- Windows API integration for File Explorer interaction
- Windows COM objects for shell integration
- Windows system tray functionality
- Windows-specific hotkey handling

### Hardware Requirements
- **RAM:** 4GB minimum (8GB recommended for large audio files)
- **Storage:** 100MB for application + additional space for temporary files during analysis
- **Audio:** Sound card or audio device (for audio playback features)
- **Display:** Any resolution (application adapts to screen size)

### Software Dependencies (Pre-built Version)
The pre-built executable includes all necessary dependencies. No additional software installation required.

### Optional Features
- **Azure Speech Services account** (for speech transcription features)
- **Audacity** (for "Open in Audacity" feature - automatically detected if installed)

## Installation

### Option 1: Download the Pre-built Release

1. Go to the [Releases page](https://github.com/pmarmaroli/AudioTooltip/releases)
2. Download the latest version
3. Extract the ZIP file
4. Run AudioTooltip.exe

### Option 2: Build from Source

#### Requirements

- Python 3.11+
- PyQt5
- librosa
- numpy
- matplotlib
- soundfile
- mutagen
- Azure Speech SDK (for transcription)
- Windows-specific (optional):
  - pywin32
  - keyboard
  - pynput

#### Setup

1. Clone the repository:

```bash
git clone https://github.com/pmarmaroli/AudioTooltip.git
cd AudioTooltip
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Launch the application:

```bash
python main.py
```

4. Or build your own executable:

```bash
# Recommended: Use the build script (includes cleanup.ps1 and installation-guide.md)
.\build_release.bat

# Alternative: Manual build using PyInstaller
pyinstaller .\AudioTooltip.spec --clean
```

The build script will create `dist/AudioTooltip.exe` plus additional user files (`cleanup.ps1`, `installation-guide.md`).

## Development

### Extending the Application

The modular architecture makes it easy to extend:

- Add new visualization types in `core/audio_analyzer.py`
- Implement additional features in `core/audio_features.py`
- Enhance the UI by modifying components in the `ui/` directory

### Building a Standalone Application

You can package the application using the build script:

```bash
pip install pyinstaller
.\build_release.bat
```

## Troubleshooting

Logs are stored in:

- Windows: `%LOCALAPPDATA%\AudioTooltip_Logs\`
- Linux/Mac: `~/.local/share/AudioTooltip_Logs/`

Common issues:

- **Missing dependencies**: Ensure all packages in requirements.txt are installed
- **Hotkeys not working**: Make sure the virtual environment is activated when running from source
- **Audio file not recognized**: Check if the file format is supported
- **Network files not accessible**: UNC network paths may have issues; try copying files locally first
- **Transcription unavailable**: Verify Azure credentials in settings
- **Incomplete transcription**: Ensure "Full file" is selected in transcription duration settings
- **Windows security warning**: Follow the steps outlined in the security warning section

## Need Help?

If you encounter any issues or have questions, please contact support at [patrick.marmaroli@gmail.com] or visit our GitHub repository at [https://github.com/pmarmaroli/AudioTooltip](https://github.com/pmarmaroli/AudioTooltip).

## Developers

- [Patrick Marmaroli](https://www.linkedin.com/in/pmarmaroli/) - Developer
- [Ergo Esken](https://www.linkedin.com/in/ergo-esken/) - QA Auditor

## License

[MIT License](LICENSE)

## Acknowledgements

This application uses several open-source libraries:

- librosa for audio analysis
- PyQt5 for the user interface
- matplotlib for visualizations
- soundfile for audio file handling
- Azure Cognitive Services for speech recognition
