# Audio Tooltip

A desktop tooltip that provides instant audio insights like metadata, spectrograms, and transcription with a simple Alt+A keyboard shortcut.

## Application Interface

![Audio Tooltip interface showing waveform analysis](screenshots/interface.png)
![Audio Tooltip interface showing waveform analysis](screenshots/visualization.png)

## Installation

## Overview

Audio Tooltip provides detailed audio analysis through an unobtrusive tooltip interface. Analyze audio files directly from your file explorer with a simple keyboard shortcut (Alt+A), or open files manually through the application.

## Features

- **Comprehensive Audio Analysis**: Extract spectral, harmonic, and perceptual features
- **Rich Visualizations**: Waveforms, spectrograms, chromagrams analysis
- **Full Audio Transcription**: Speech-to-text via Azure Speech Services with continuous recognition for files of any length
- **System Tray Integration**: Minimal footprint with easy access
- **File Explorer Integration**: Analyze files with Alt+A keyboard shortcut
- **Multi-channel Support**: Analyze and visualize individual channels in multi-channel audio
- **Audio Previews**: Generate and play short previews
- **Double Waveform Visualization**: Special visualization for stereo audio files

## Project Structure

```
audio-analyzer/
│
├── core/                      # Core analysis functionality
│   ├── audio_analyzer.py      # Audio loading and analysis
│   ├── audio_features.py      # Feature extraction
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

## Installation

### Option 1: Download the Pre-built Release

1. Go to the [Releases page](https://github.com/pmarmaroli/AudioTooltip/releases)
2. Download the latest version
3. Extract the ZIP file
4. Run AudioTooltip.exe

### Option 2: Build from Source

#### Requirements

- Python 3.7+
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
# For basic build
pyinstaller main.py

# For optimized build using the provided spec file
pyinstaller .\AudioTooltip.spec --noconfirm
```

The optimized build will create a `dist/AudioTooltip` folder containing the executable and all necessary files.

## Usage

### System Tray

The application runs in the system tray. Right-click the icon to:

- Analyze a file
- Access recently analyzed files
- Adjust application settings
- Exit the application

### Explorer Integration

1. Left-click an audio file in Windows Explorer
2. Press Alt+A
3. The analysis tooltip will appear with detailed information

### Drop Target Window

Access the drop target window by:

- Right-clicking the system tray icon and selecting "Open Drop Target Window"
- Using the Alt+D keyboard shortcut

Simply drag and drop audio files onto this window for quick analysis.

### Manual Analysis

1. Right-click the system tray icon
2. Select "Analyze File..."
3. Choose an audio file from the file dialog

### Tooltip Features

The tooltip interface provides several tabs:

- **Overview**: Basic file information and waveform display
- **Visualizations**: Various audio visualizations (spectrogram, mel-spectrogram, chromagram, double waveform)
- **Transcript**: Speech-to-text transcription of full audio content

Additional controls:

- Play a short preview of the audio
- Open the full file in Audacity or your default audio player
- Pin the tooltip to keep it visible
- Switch between channels for multi-channel audio
- Save analysis results to files

## Configuration

Access settings by right-clicking the tray icon and selecting "Settings..." or from within the tooltip.

### Analysis Settings

- Preview duration
- Option to analyze entire file
- Configure advanced analysis features

### Transcription Settings

- Enable/disable speech transcription
- Configure Azure Speech Services credentials
- Select language options
- Transcription duration options:
  - Same as preview
  - 60 seconds
  - Full file (continuous recognition)

### Channel Analysis

For multi-channel audio:

- Analyze individual channels separately
- View channel-specific visualizations
- Calculate inter-channel time delays

### Double Waveform Visualization

A specialized visualization for stereo audio files:

- Left channel (red) shown as positive values
- Right channel (blue) shown as negative values
- Easily identify stereo imaging and channel differences

## Development

### Extending the Application

The modular architecture makes it easy to extend:

- Add new visualization types in `core/audio_analyzer.py`
- Implement additional features in `core/audio_features.py`
- Enhance the UI by modifying components in the `ui/` directory

### Building a Standalone Application

You can package the application using PyInstaller:

```bash
pip install pyinstaller
pyinstaller .\AudioTooltip.spec --noconfirm
```

## Troubleshooting

Logs are stored in:

- Windows: `%LOCALAPPDATA%\AudioTooltip_Logs\`
- Linux/Mac: `~/.local/share/AudioTooltip_Logs/`

Common issues:

- **Missing dependencies**: Ensure all packages in requirements.txt are installed
- **Audio file not recognized**: Check if the file format is supported
- **Transcription unavailable**: Verify Azure credentials in settings
- **Incomplete transcription**: Ensure "Full file" is selected in transcription duration settings
- **Windows security warning**: Follow the steps outlined in the security warning section

## Need Help?

If you encounter any issues or have questions, please contact support at [patrick.marmaroli@gmail.com] or visit our GitHub repository at [https://github.com/pmarmaroli/AudioTooltip](https://github.com/pmarmaroli/AudioTooltip).

## Developers

- [Patrick Marmaroli](https://www.linkedin.com/in/patrickmarmaroli/) - Developer
- [Ergo Esken](https://www.linkedin.com/in/ergo-esken/) - Reviewer

## License

[MIT License](LICENSE)

## Acknowledgements

This application uses several open-source libraries:

- librosa for audio analysis
- PyQt5 for the user interface
- matplotlib for visualizations
- soundfile for audio file handling
- Azure Cognitive Services for speech recognition
