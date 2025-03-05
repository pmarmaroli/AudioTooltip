"""
Audio Playback Module
--------------------
Handles audio playback and preview generation with efficient resource management.
"""

import os
import time
import logging
import tempfile
import subprocess
import traceback
from pathlib import Path
from typing import Optional, List, Union

import numpy as np

# Optional dependencies with fallbacks
try:
    import soundfile as sf
    SF_AVAILABLE = True
except ImportError:
    SF_AVAILABLE = False

try:
    import librosa
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False


class AudioPlayback:
    """
    Handles audio playback and preview clip generation with resource management.
    """

    def __init__(self):
        """Initialize the audio playback manager"""
        self.logger = logging.getLogger("AudioPlayback")
        self.temp_files: List[str] = []
        self.playing_process = None
        self.logger.info("AudioPlayback initialized")

    def play_audio(self, file_path: str) -> bool:
        """
        Play audio file using system default player.

        Args:
            file_path: Path to audio file

        Returns:
            bool: True if playback started successfully
        """
        if not os.path.exists(file_path):
            self.logger.error(f"File not found: {file_path}")
            return False

        try:
            # Stop any currently playing audio
            self.stop_playback()

            # Use appropriate method based on OS
            if os.name == 'nt':  # Windows
                self.logger.debug(
                    f"Starting playback with Windows default player: {file_path}")
                self.playing_process = subprocess.Popen(
                    ['start', '', file_path], shell=True)
                return True
            elif os.name == 'posix':  # macOS, Linux
                if os.uname().sysname == 'Darwin':  # macOS
                    self.logger.debug(
                        f"Starting playback with macOS open: {file_path}")
                    self.playing_process = subprocess.Popen(
                        ['open', file_path])
                    return True
                else:  # Linux
                    self.logger.debug(
                        f"Starting playback with xdg-open: {file_path}")
                    self.playing_process = subprocess.Popen(
                        ['xdg-open', file_path])
                    return True
            else:
                self.logger.error(f"Unsupported OS: {os.name}")
                return False

        except Exception as e:
            self.logger.error(f"Error playing audio: {e}")
            self.logger.error(traceback.format_exc())
            return False

    def stop_playback(self) -> None:
        """Stop any currently playing audio"""
        if self.playing_process:
            try:
                self.playing_process.terminate()
                self.playing_process = None
                self.logger.debug("Stopped playback")
            except Exception as e:
                self.logger.warning(f"Error stopping playback: {e}")

    def create_temp_clip(self, file_path: str, duration: float = 10.0) -> Optional[str]:
        """
        Create a temporary preview clip of the audio file.

        Args:
            file_path: Path to original audio file
            duration: Duration of preview in seconds

        Returns:
            str: Path to temporary preview file or None on error
        """
        if not os.path.exists(file_path):
            self.logger.error(f"File not found: {file_path}")
            return None

        # Check if required libraries are available
        if not SF_AVAILABLE and not LIBROSA_AVAILABLE:
            self.logger.error(
                "Neither soundfile nor librosa available for preview generation")
            return file_path  # Fall back to original file

        try:
            # Create unique temp filename
            file_ext = os.path.splitext(file_path)[1].lower()
            if not file_ext:
                file_ext = '.wav'  # Default format

            temp_dir = tempfile.gettempdir()
            temp_filename = f"preview_{int(time.time())}_{os.path.basename(file_path)}"
            temp_path = os.path.join(temp_dir, temp_filename)

            self.logger.info(
                f"Creating {duration}s preview clip from {file_path}")

            # Load audio data
            y = None
            sr = None

            if SF_AVAILABLE:
                try:
                    with sf.SoundFile(file_path) as f:
                        # Calculate frames to read for duration
                        frames_to_read = min(
                            int(f.samplerate * duration), f.frames)
                        y = f.read(frames_to_read)
                        sr = f.samplerate
                except Exception as sf_e:
                    self.logger.warning(f"Soundfile loading failed: {sf_e}")

            if y is None and LIBROSA_AVAILABLE:
                try:
                    y, sr = librosa.load(file_path, duration=duration)
                except Exception as lib_e:
                    self.logger.error(f"Librosa loading failed: {lib_e}")
                    return None

            if y is None or sr is None:
                self.logger.error("Failed to load audio data for preview")
                return None

            # Write preview file
            if SF_AVAILABLE:
                sf.write(temp_path, y, sr)
            else:
                import scipy.io.wavfile
                scipy.io.wavfile.write(temp_path, sr, y.astype(np.float32))

            # Track temp file for cleanup
            self.temp_files.append(temp_path)
            self.logger.info(f"Created preview clip: {temp_path}")

            return temp_path

        except Exception as e:
            self.logger.error(f"Error creating preview clip: {e}")
            self.logger.error(traceback.format_exc())
            return None

    def cleanup(self) -> None:
        """Clean up temporary files"""
        self.stop_playback()

        # Remove temp files
        for temp_file in self.temp_files:
            try:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
                    self.logger.debug(f"Removed temp file: {temp_file}")
            except Exception as e:
                self.logger.warning(
                    f"Failed to remove temp file {temp_file}: {e}")

        self.temp_files = []
        self.logger.info("Completed temp file cleanup")
