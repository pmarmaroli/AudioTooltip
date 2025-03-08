## Windows Security Warning Notice

When you download and run the Audio Tooltip application for the first time, you may see a Windows security warning message saying "Windows protected your PC" or "SmartScreen prevented an unrecognized app from starting." This is normal behavior for applications that are not yet digitally signed or don't have an established reputation with Microsoft's SmartScreen system.

### How to Run the Application If You See the Warning

1. Click on "More info" or "Show more details" in the warning message
2. Click on "Run anyway" button that appears
3. The application will start normally after this step

This warning appears because the application isn't digitally signed with a commercial code signing certificate and is new to Microsoft's reputation systems. The Audio Tooltip is safe to use, and this warning is simply a precautionary measure by Windows.

## Releases

To get the latest release, go to the [Releases page](https://github.com/pmarmaroli/AudioTooltip/releases)

## How to use Audio Tooltip

1. Left-click an audio file in Windows Explorer
2. Press Alt+A
3. The analysis tooltip will appear with detailed information

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
