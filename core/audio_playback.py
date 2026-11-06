"""
Audio Playback Module
--------------------
Preview clips played inside the app (stoppable), plus opening files in the
system default player.
"""

import os
import time
import logging
import tempfile
import traceback
from typing import Optional, List, Tuple, Callable

import soundfile as sf

try:
    import winsound
    WINSOUND_AVAILABLE = True
except ImportError:  # not on Windows
    WINSOUND_AVAILABLE = False


class AudioPlayback:
    """Creates WAV preview clips, plays them in-process and cleans them up."""

    def __init__(self, loader: Optional[Callable] = None):
        """
        Args:
            loader: function(path, duration=..., channel=...) returning
                    (samples, sample_rate, total_duration, num_channels), e.g.
                    AudioAnalyzer.load_audio. It decodes every supported format.
        """
        self.logger = logging.getLogger("AudioPlayback")
        self.loader = loader
        self.temp_files: List[str] = []
        self.current_clip: Optional[str] = None

    def play_audio(self, file_path: str) -> bool:
        """Open a file in the system default player."""
        if not os.path.exists(file_path):
            self.logger.error(f"File not found: {file_path}")
            return False
        try:
            os.startfile(file_path)
            return True
        except Exception as e:
            self.logger.error(f"Error playing audio: {e}")
            return False

    def play_clip(self, clip_path: str) -> bool:
        """Play a WAV clip asynchronously inside the app."""
        if not WINSOUND_AVAILABLE:
            return self.play_audio(clip_path)
        try:
            self.stop_playback()
            winsound.PlaySound(
                clip_path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            self.current_clip = clip_path
            return True
        except Exception as e:
            self.logger.error(f"Error playing clip: {e}")
            return False

    def stop_playback(self) -> None:
        """Stop the clip currently playing, if any."""
        if WINSOUND_AVAILABLE:
            try:
                winsound.PlaySound(None, 0)
            except Exception as e:
                self.logger.warning(f"Error stopping playback: {e}")
        self.current_clip = None

    def create_temp_clip(self, file_path: str, duration: float = 10.0,
                         channel: int = 0) -> Tuple[Optional[str], float]:
        """
        Write the first `duration` seconds of one channel to a temporary
        16-bit WAV (playable whatever the source format).

        Returns:
            (clip_path, clip_seconds), or (None, 0) on error.
        """
        if self.loader is None:
            self.logger.error("No audio loader configured")
            return None, 0.0
        try:
            y, sr, _, _ = self.loader(file_path, duration=duration, channel=channel)
            if y is None or sr is None or len(y) == 0:
                self.logger.error("Failed to load audio data for preview")
                return None, 0.0

            fd, temp_path = tempfile.mkstemp(prefix="audiotooltip_preview_", suffix=".wav")
            os.close(fd)
            sf.write(temp_path, y, sr, subtype='PCM_16')
            self.temp_files.append(temp_path)
            return temp_path, len(y) / sr

        except Exception as e:
            self.logger.error(f"Error creating preview clip: {e}")
            self.logger.error(traceback.format_exc())
            return None, 0.0

    def cleanup(self, min_age_seconds: Optional[float] = None) -> None:
        """
        Delete preview clips. With min_age_seconds, only clips older than that
        and not currently playing are deleted; files that cannot be deleted
        are kept in the list and retried later.
        """
        now = time.time()
        remaining = []
        for temp_file in self.temp_files:
            try:
                if not os.path.exists(temp_file):
                    continue
                if min_age_seconds is not None and (
                        temp_file == self.current_clip or
                        now - os.path.getmtime(temp_file) < min_age_seconds):
                    remaining.append(temp_file)
                    continue
                os.unlink(temp_file)
            except OSError as e:
                self.logger.debug(f"Could not remove temp file {temp_file}: {e}")
                remaining.append(temp_file)
        self.temp_files = remaining
