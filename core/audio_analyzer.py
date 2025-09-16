"""
Enhanced Audio Analyzer Module
------------------------------
Core functionality for audio file analysis with improved performance and error handling.
"""

# fmt: off
import os
import io
import time
import logging
import traceback
import tempfile
from pathlib import Path
from typing import Tuple, Dict, Optional, Union, Any, BinaryIO

import numpy as np
import librosa
import librosa.display
import soundfile as sf
import scipy.signal as signal
import matplotlib
matplotlib.use('Agg')  # Set the non-GUI backend before importing pyplot
import matplotlib.pyplot as plt
from matplotlib import rcParams
import matplotlib.gridspec as gridspec
# fmt: on

# Optional imports with fallbacks
try:
    import mutagen
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

try:
    import azure.cognitiveservices.speech as speechsdk
    AZURE_SPEECH_AVAILABLE = True
except ImportError:
    AZURE_SPEECH_AVAILABLE = False


class AudioAnalyzer:
    """
    Enhanced audio analyzer with improved architecture, error handling, and performance.

    Features:
    - Optimized audio file loading with format detection
    - Multiple visualization types (waveform, spectrogram, mel-spectrogram, etc.)
    - Optional transcription via Azure Speech Services
    - Comprehensive caching system
    - Smart error handling and recovery
    """

    def __init__(self, settings=None):
        """
        Initialize the audio analyzer.

        Args:
            settings: Application settings object (optional)
        """
        self.logger = logging.getLogger("AudioAnalyzer")
        self.settings = settings
        self.speech_config = None
        self.initialized = False

        # Initialize caches with size limits
        self.sr_cache = {}  # Sample rate cache
        self.duration_cache = {}  # Duration cache
        self.analysis_cache = {}  # Analysis results cache
        self.max_cache_size = 20  # Maximum items in each cache

        # Default analysis parameters
        self.chunk_duration = 10.0  # Default preview duration in seconds
        self.spec_n_fft = 2048
        self.spec_hop_length = 512

        # Configure matplotlib for non-interactive use
        rcParams['figure.dpi'] = 100
        rcParams['savefig.dpi'] = 150
        rcParams['font.size'] = 10
        plt.ioff()  # Turn off interactive mode

        self.logger.info("AudioAnalyzer initialized")

    def is_cache_valid(self, file_path: str) -> bool:
        """
        Check if cached analysis for a file is still valid.

        Args:
            file_path: Path to the audio file

        Returns:
            bool: True if cache is valid, False if file has been modified
        """
        # If file doesn't exist, cache is invalid
        if not os.path.exists(file_path):
            return False

        # Check if file has been modified since it was cached
        current_mtime = os.path.getmtime(file_path)

        # If we don't have a stored modification time, cache is invalid
        if 'mtime' not in self.analysis_cache.get(file_path, {}):
            # Initialize if needed
            if file_path not in self.analysis_cache:
                self.analysis_cache[file_path] = {}
            self.analysis_cache[file_path]['mtime'] = current_mtime
            return False

        # If modification time has changed, cache is invalid
        cached_mtime = self.analysis_cache[file_path]['mtime']
        if current_mtime > cached_mtime:
            self.logger.info(
                f"File {file_path} has been modified since last analysis")
            # Update the stored modification time
            self.analysis_cache[file_path]['mtime'] = current_mtime
            return False

        # Cache is valid
        return True

    def calculate_time_delay(self, file_path: str) -> Optional[float]:
        """Calculate time delay between left and right channels using GCC-PHAT."""
        try:
            self.logger.debug(
                f"Starting time delay calculation for {file_path}")

            # Check if this is a stereo file by loading a small sample
            y_check, sr_check, _, num_channels = self.load_audio(
                file_path, duration=0.1, all_channels=True)

            self.logger.debug(f"File has {num_channels} channels")

            if num_channels < 2:
                self.logger.debug(
                    f"Time delay calculation requires stereo audio, found {num_channels} channels")
                return None

            # Load both channels
            self.logger.debug("Loading full audio for time delay calculation")
            y, sr, _, _ = self.load_audio(file_path, all_channels=True)

            if y is None or sr is None:
                self.logger.error(
                    "Failed to load audio for time delay calculation")
                return None

            self.logger.debug(
                f"Audio loaded successfully: shape={y.shape}, sr={sr}")

            # Extract the channels
            left_channel = y[:, 0]
            right_channel = y[:, 1]

            self.logger.debug("Computing cross-correlation")
            (G, axe_spl, axe_ms) = self.GCCPHAT(
                left_channel, right_channel, sr, 1)

            # Find the peak of the cross-correlation
            peak_index = np.argmax(G)
            delay_ms = axe_ms[peak_index]

            print(f"Successfully calculated time delay: {delay_ms:.2f} ms")

            self.logger.info(
                f"Successfully calculated time delay: {delay_ms:.2f} ms")
            return delay_ms

        except Exception as e:
            self.logger.error(f"Error calculating time delay: {e}")
            self.logger.error(traceback.format_exc())
            return None

    def MYFFT(self, a):
        if isinstance(a, list):
            myfft = np.fft.fft(a)
        else:
            myfft = np.fft.fftn(a)

        return myfft

    def MYIFFT(self, a):
        if isinstance(a, list):
            myifft = np.fft.ifft(a)
        else:
            myifft = np.fft.ifftn(a)

        return myifft

    def COLORE(self, sigin, fs, fmin, fmax, mode):
        # FFT-based filter
        # if mode = 1 -> bandpass between fmin and fmax, if mode = 0 -> bandcut between fmin and fmax

        siginFFT = self.MYFFT(sigin)
        nfft = len(siginFFT)

        vfc_pos = np.linspace(0, fs/2, (int)(nfft/2+1))
        vfc_neg = -np.flipud(vfc_pos[1:len(vfc_pos)-1])
        vfc = np.concatenate((vfc_pos, vfc_neg))

        indFreqInBand = np.where(
            (((vfc >= fmin) & (vfc <= fmax)) | ((vfc <= -fmin) & (vfc >= -fmax))))
        indFreqOutBand = np.where(
            (((vfc < fmin) & (vfc > -fmin)) | ((vfc < -fmax) | (vfc > fmax))))

        absS = np.abs(siginFFT)

        if (mode == 1):
            absS[indFreqOutBand] = 0
        else:
            absS[indFreqInBand] = 0

        sigout = np.real(self.MYIFFT(np.multiply(
            absS, np.exp(np.multiply(1j, np.angle(siginFFT))))))

        return sigout

    def GCCPHAT(self, s1, s2, fs, norm, fmin=0, fmax=8000):
        s1c = self.COLORE(s1, fs, fmin, fmax, 1)
        s2c = self.COLORE(s2, fs, fmin, fmax, 1)

        # Use FFTs of the filtered signals (do not overwrite them accidentally)
        f_s1 = self.MYFFT(s1c)
        f_s2 = self.MYFFT(s2c)

        Pxy = f_s1 * np.conj(f_s2)

        if (norm == 1):
            denom = np.abs(Pxy)
            denom[denom < 1e-6] = 1e-6
        else:
            denom = 1

        # This line is the only difference between GCC-PHAT and normal cross correlation
        G = np.fft.fftshift(np.real(self.MYIFFT(Pxy / denom)))
        G = G / np.max(np.abs(G))

        x = np.array([i for i in range(G.shape[0])])
        axe_spl = x - G.shape[0]/2
        axe_ms = axe_spl/fs*1000

        return G, axe_spl, axe_ms

    def initialize(self) -> bool:
        """
        Fully initialize the analyzer with settings.

        Returns:
            bool: True if initialization was successful
        """
        if self.initialized:
            return True

        try:
            self.logger.info("Initializing audio analyzer")

            # Load settings if available
            if self.settings:
                self.chunk_duration = float(
                    self.settings.value("preview_duration", "10.0"))
                self.logger.info(
                    f"Set preview duration to {self.chunk_duration}s")

                # Initialize speech services if enabled
                if self.settings.value("enable_transcription", "false") == "true":
                    self.initialize_speech_services()

            self.initialized = True
            return True

        except Exception as e:
            self.logger.error(f"Initialization failed: {e}")
            self.logger.error(traceback.format_exc())
            return False

    # Add this method to the AudioAnalyzer class in core/audio_analyzer.py

    def generate_double_waveform(self, file_path: str) -> Optional[io.BytesIO]:
        """
        Generate double waveform visualization for stereo audio files.
        Left channel (0) is shown in red for positive values.
        Right channel (1) is shown in blue for negative values.

        Args:
            file_path: Path to the stereo audio file

        Returns:
            BytesIO buffer containing the visualization image or None on error
        """
        try:
            # Check if this is a stereo file by loading a small sample
            y_check, sr_check, _, num_channels = self.load_audio(
                file_path, duration=0.1, all_channels=True)

            if num_channels < 2:
                self.logger.warning(
                    f"Double waveform requires stereo audio, but found {num_channels} channels")
                return None

            # Close any existing figures
            plt.close('all')

            # Load both channels
            y, sr, _, _ = self.load_audio(file_path, all_channels=True)

            if y is None or sr is None:
                self.logger.error("Failed to load audio for double waveform")
                return None

            # Extract the channels
            left_channel = y[:, 0]
            right_channel = y[:, 1]

            # Create figure
            fig = plt.figure(figsize=(10, 4), facecolor='white')
            ax = fig.add_subplot(111)

            # Optimize data for display
            max_points = 10000
            if len(left_channel) > max_points:
                decimation_factor = len(left_channel) // max_points
                left_decimated = left_channel[::decimation_factor]
                right_decimated = right_channel[::decimation_factor]
                time_decimated = np.linspace(
                    0, len(left_channel) / sr, len(left_decimated))
            else:
                left_decimated = left_channel
                right_decimated = right_channel
                time_decimated = np.linspace(
                    0, len(left_channel) / sr, len(left_channel))

            # Only plot positive values for left channel (in red)
            left_positive = left_decimated.copy()
            left_positive[left_positive < 0] = 0

            # Only plot negative values for right channel (in blue)
            right_negative = right_decimated.copy()
            right_negative[right_negative > 0] = 0

            # Plot with custom styling
            ax.fill_between(time_decimated, left_positive, 0,
                            color='#e74c3c', alpha=0.7, label='Left Channel (positive)')
            ax.fill_between(time_decimated, right_negative, 0,
                            color='#3498db', alpha=0.7, label='Right Channel (negative)')

            ax.set_title('Double Waveform - Stereo Channels', fontsize=12)
            ax.set_xlabel('Time (s)', fontsize=10)
            ax.set_ylabel('Amplitude', fontsize=10)
            ax.set_ylim(-1.1, 1.1)
            ax.grid(True, linestyle='--', alpha=0.7, color='#cccccc')
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.legend(loc='upper right', framealpha=0.9)

            # Add a horizontal line at zero
            ax.axhline(y=0, color='#888888', linestyle='-', linewidth=0.8)

            plt.tight_layout()

            # Save to buffer
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
            plt.close(fig)
            buf.seek(0)

            return buf

        except Exception as e:
            self.logger.error(f"Error generating double waveform: {e}")
            self.logger.error(traceback.format_exc())
            return None

    def initialize_speech_services(self) -> bool:
        """
        Initialize Azure Speech services with improved error handling.

        Returns:
            bool: True if speech services were successfully initialized
        """
        if not AZURE_SPEECH_AVAILABLE:
            self.logger.warning("Azure Speech Services package not installed")
            return False

        if not self.settings:
            self.logger.warning("Settings not available for speech services")
            return False

        # Check if transcription is enabled
        transcription_enabled = self.settings.value(
            "enable_transcription", "false") == "true"
        if not transcription_enabled:
            self.logger.info("Speech transcription is disabled in settings")
            return False

        # Get credentials with fallback to environment variables
        azure_key = self.settings.value("azure_key", "")
        azure_region = self.settings.value("azure_region", "")

        if not azure_key or not azure_region:
            self.logger.warning("Azure credentials not found in settings")
            return False

        try:
            # Initialize the speech config
            self.speech_config = speechsdk.SpeechConfig(
                subscription=azure_key,
                region=azure_region
            )
            self.logger.info(
                f"Speech services initialized with region: {azure_region}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize speech services: {e}")
            self.logger.error(traceback.format_exc())
            return False

    def load_audio(self, audio_path: str, duration: Optional[float] = None, channel: int = 0, all_channels: bool = False) -> Tuple[Optional[np.ndarray], Optional[int], Optional[float], Optional[int]]:
        """
        Load audio with optimized memory usage and error handling.

        Args:
            audio_path: Path to the audio file
            duration: Maximum duration to load in seconds (uses chunk_duration if None)
            channel: Channel to load (0 for left/mono, 1 for right, etc.)
            all_channels: If True, load all channels as multi-dimensional array

        Returns:
            Tuple of (audio_data, sample_rate, total_duration, num_channels) or (None, None, None, None) on error
        """
        if duration is None:
            duration = self.chunk_duration

        start_time = time.time()
        self.logger.info(
            f"Loading audio file: {audio_path}, channel: {channel if not all_channels else 'all'}")

        try:
            # Validate file
            if not os.path.exists(audio_path):
                self.logger.error(f"File not found: {audio_path}")
                return None, None, None, None

            # Get file information
            file_size = os.path.getsize(audio_path)
            if file_size == 0:
                self.logger.error(f"File is empty: {audio_path}")
                return None, None, None, None

            self.logger.debug(f"File size: {file_size/1024:.1f} KB")

            # Check cache for sample rate
            target_sr = None
            if audio_path in self.sr_cache:
                target_sr = self.sr_cache[audio_path]
                self.logger.debug(f"Using cached sample rate: {target_sr}")

            # Get file information
            try:
                info = sf.info(audio_path)
                num_channels = info.channels

                if target_sr is None:
                    target_sr = info.samplerate
                    self.sr_cache[audio_path] = target_sr

                # Get total duration using cached value or soundfile
                if audio_path in self.duration_cache:
                    total_duration = self.duration_cache[audio_path]
                else:
                    total_duration = info.duration
                    self.duration_cache[audio_path] = total_duration

                self.logger.debug(
                    f"Audio info - SR: {target_sr}Hz, Duration: {total_duration:.2f}s, Channels: {info.channels}")

            except Exception as info_e:
                self.logger.warning(
                    f"Could not get audio info with soundfile: {info_e}")
                # Fallback to librosa for getting info
                try:
                    duration_raw = librosa.get_duration(path=audio_path)
                    total_duration = float(duration_raw)
                    self.duration_cache[audio_path] = total_duration

                    # Try to get channel info
                    try:
                        y, sr = librosa.load(
                            audio_path, sr=None, mono=False, duration=0.1)
                        num_channels = y.shape[0] if len(y.shape) > 1 else 1
                    except:
                        num_channels = 1

                    if target_sr is None:
                        # Use a standard sample rate as fallback
                        target_sr = 44100
                        self.sr_cache[audio_path] = target_sr

                    self.logger.debug(
                        f"Using librosa fallback - SR: {target_sr}Hz, Duration: {total_duration:.2f}s, Channels: {num_channels}")

                except Exception as e:
                    self.logger.error(f"Failed to get audio info: {e}")
                    return None, None, None, None

            # Validate requested channel if not loading all channels
            if not all_channels and channel >= num_channels:
                self.logger.error(
                    f"Requested channel {channel} exceeds available channels ({num_channels})")
                return None, None, None, None

            # For initial preview, load only first few seconds
            preview_duration = min(
                duration, total_duration) if duration != -1 else total_duration
            self.logger.debug(f"Loading {preview_duration:.2f}s preview")

            # Use soundfile for faster loading
            try:
                with sf.SoundFile(audio_path) as sf_file:
                    frames_to_read = int(
                        preview_duration * sf_file.samplerate) if preview_duration != total_duration else -1
                    y = sf_file.read(frames_to_read)

                    # Handle multi-channel audio based on all_channels flag
                    if len(y.shape) > 1:
                        if not all_channels:
                            if channel < y.shape[1]:
                                y = y[:, channel]  # Extract requested channel
                            else:
                                self.logger.warning(
                                    f"Channel {channel} not available, using first channel")
                                y = y[:, 0]
                        # else: keep all channels intact

                    # Resample if needed
                    if sf_file.samplerate != target_sr:
                        if all_channels and len(y.shape) > 1:
                            # Resample multi-channel data correctly: compute new frame count
                            orig_frames = y.shape[0]
                            num_channels = y.shape[1]
                            new_len = int(orig_frames * target_sr / sf_file.samplerate)
                            # Allocate with shape (new_frames, num_channels)
                            y_resampled = np.zeros((new_len, num_channels), dtype=y.dtype)
                            for ch in range(num_channels):
                                y_resampled[:, ch] = librosa.resample(
                                    y[:, ch], orig_sr=sf_file.samplerate, target_sr=target_sr)
                            y = y_resampled
                        else:
                            y = librosa.resample(
                                y, orig_sr=sf_file.samplerate, target_sr=target_sr)

                    actual_sr = target_sr
            except Exception as sf_e:
                self.logger.warning(
                    f"Soundfile loading failed, trying librosa: {sf_e}")

                # Fallback to librosa
                try:
                    if duration == -1:
                        y, actual_sr = librosa.load(
                            audio_path,
                            sr=target_sr,
                            mono=not all_channels  # Keep channels if all_channels is True
                        )
                    else:
                        y, actual_sr = librosa.load(
                            audio_path,
                            sr=target_sr,
                            offset=0,
                            duration=preview_duration,
                            mono=not all_channels  # Keep channels if all_channels is True
                        )

                    # librosa returns multi-channel arrays as (channels, frames) when mono=False.
                    # Normalize the shape so that all-channel data is (frames, channels).
                    if isinstance(y, np.ndarray) and y.ndim > 1:
                        if not all_channels:
                            # We requested a single channel: librosa returns (channels, frames)
                            # Pick the requested channel (or first available) which is y[channel]
                            if channel < y.shape[0]:
                                y = y[channel]
                            else:
                                self.logger.warning(f"Channel {channel} not available from librosa, using channel 0")
                                y = y[0]
                        else:
                            # all_channels=True: transpose to (frames, channels)
                            if y.shape[0] != 0:
                                y = y.T
                except Exception as e:
                    self.logger.error(f"All audio loading methods failed: {e}")
                    self.logger.error(traceback.format_exc())
                    return None, None, None, None

            # Manage caches to prevent memory leaks
            self._maintain_cache_size()

            end_time = time.time()
            self.logger.info(
                f"Audio loaded in {end_time - start_time:.2f}s - Shape: {y.shape}, SR: {actual_sr}Hz")

            return y, actual_sr, total_duration, num_channels

        except Exception as e:
            self.logger.error(f"Unexpected error loading audio: {e}")
            self.logger.error(traceback.format_exc())
            return None, None, None, None

    def _maintain_cache_size(self):
        """Prevent cache from growing too large"""
        for cache, name in [
            (self.sr_cache, "sample rate"),
            (self.duration_cache, "duration"),
            (self.analysis_cache, "analysis")
        ]:
            if len(cache) > self.max_cache_size:
                # Remove oldest items (assuming keys were added in order)
                items_to_remove = len(cache) - self.max_cache_size
                keys_to_remove = list(cache.keys())[:items_to_remove]
                for key in keys_to_remove:
                    del cache[key]
                self.logger.debug(
                    f"Cleaned {name} cache: removed {items_to_remove} items")

    def get_audio_metadata(self, file_path: str, total_duration: Optional[float] = None) -> str:
        """
        Extract metadata with improved error handling.

        Args:
            file_path: Path to the audio file
            total_duration: Optional pre-calculated duration

        Returns:
            str: Formatted metadata as a string
        """
        try:
            self.logger.info(f"Starting metadata extraction for: {file_path}")

            # If duration not provided, try to get it
            if total_duration is None:
                self.logger.debug(
                    "Duration not provided, attempting to retrieve")
                if file_path in self.duration_cache:
                    total_duration = self.duration_cache[file_path]
                    self.logger.debug(
                        f"Using cached duration: {total_duration}s")
                else:
                    try:
                        total_duration = librosa.get_duration(path=file_path)
                        self.logger.debug(
                            f"Calculated duration: {total_duration}s")
                    except Exception as e:
                        self.logger.warning(f"Could not get duration: {e}")
                        total_duration = 0
                        self.logger.debug("Setting duration to 0 as fallback")

            # Format duration
            minutes = int(total_duration // 60)
            seconds = int(total_duration % 60)
            duration_str = f"{minutes}:{seconds:02d}"
            self.logger.debug(f"Formatted duration: {duration_str}")

            # Get sample rate
            sample_rate = None
            if file_path in self.sr_cache:
                sample_rate = self.sr_cache[file_path]
                self.logger.debug(
                    f"Using cached sample rate: {sample_rate} Hz")
            else:
                self.logger.debug(
                    "Sample rate not in cache, attempting to retrieve")
                try:
                    info = sf.info(file_path)
                    sample_rate = info.samplerate
                    self.sr_cache[file_path] = sample_rate
                    self.logger.debug(
                        f"Retrieved sample rate via soundfile: {sample_rate} Hz")
                except Exception as sf_e:
                    self.logger.warning(
                        f"Could not get sample rate with soundfile: {sf_e}")
                    # Fallback
                    try:
                        y, sr = librosa.load(file_path, sr=None, duration=0.1)
                        sample_rate = sr
                        self.sr_cache[file_path] = sample_rate
                        self.logger.debug(
                            f"Retrieved sample rate via librosa: {sample_rate} Hz")
                    except Exception as e:
                        self.logger.warning(f"Could not get sample rate: {e}")

            # Collect all metadata
            self.logger.debug("Building metadata information list")
            info = [f"Duration: {duration_str}"]

            if sample_rate:
                info.append(f"Sample Rate: {sample_rate} Hz")

            # Try to get additional metadata
            num_channels = None
            self.logger.debug(
                "Attempting to retrieve additional metadata via mutagen")
            if MUTAGEN_AVAILABLE:
                try:
                    audio = mutagen.File(file_path)
                    if audio:
                        self.logger.debug(
                            f"Mutagen loaded file successfully: {type(audio)}")
                        if hasattr(audio.info, 'channels'):
                            num_channels = audio.info.channels
                            info.append(f"Channels: {num_channels}")
                            self.logger.debug(f"Found {num_channels} channels")
                        else:
                            self.logger.debug(
                                "No channel information available in mutagen")

                        if hasattr(audio.info, 'bitrate'):
                            info.append(
                                f"Bitrate: {audio.info.bitrate // 1000} kbps")

                        # Extract any available tags
                        tags = []
                        if hasattr(audio, 'tags') and audio.tags:
                            self.logger.debug("Extracting tags from mutagen")
                            for key in ['title', 'artist', 'album', 'date', 'genre']:
                                if key in audio.tags:
                                    tags.append(
                                        f"{key.capitalize()}: {audio.tags[key][0]}")

                        # MP3 specific
                        if hasattr(audio, 'ID3') and audio.ID3:
                            self.logger.debug("Extracting ID3 tags")
                            for frame in audio.ID3.values():
                                if frame.FrameID == 'TXXX':
                                    tags.append(
                                        f"{frame.desc}: {frame.text[0]}")

                        # Add non-empty tags
                        if tags:
                            self.logger.debug(
                                f"Adding {len(tags)} metadata tags")
                            info.extend(tags)
                    else:
                        self.logger.debug(
                            "Mutagen could not parse file format")
                except Exception as e:
                    self.logger.warning(
                        f"Error reading metadata with mutagen: {e}")
                    info.append("Additional metadata unavailable")
            else:
                self.logger.debug("Mutagen not available")
                info.append(
                    "Detailed metadata unavailable (mutagen not installed)")

            # If num_channels is still None, try to get it from soundfile
            if num_channels is None:
                self.logger.debug(
                    "Channels not found in mutagen, trying alternative methods")
                try:
                    sf_info = sf.info(file_path)
                    num_channels = sf_info.channels
                    if "Channels:" not in ''.join(info):  # Avoid duplication
                        info.append(f"Channels: {num_channels}")
                    self.logger.debug(
                        f"Found {num_channels} channels via soundfile")
                except Exception as e:
                    self.logger.warning(
                        f"Could not get channel info from soundfile: {e}")
                    # One more fallback
                    try:
                        y_check, _, _, chans = self.load_audio(
                            file_path, duration=0.1, all_channels=True)
                        if chans is not None:
                            num_channels = chans
                            # Avoid duplication
                            if "Channels:" not in ''.join(info):
                                info.append(f"Channels: {num_channels}")
                            self.logger.debug(
                                f"Found {num_channels} channels via load_audio")
                    except Exception as e:
                        self.logger.warning(f"Could not get channel info: {e}")

            # Get file information
            self.logger.debug("Getting file system information")
            try:
                file_stat = os.stat(file_path)
                file_size_mb = file_stat.st_size / (1024 * 1024)
                mod_time = time.strftime(
                    '%Y-%m-%d %H:%M:%S', time.localtime(file_stat.st_mtime))

                info.append(f"File Size: {file_size_mb:.2f} MB")
                info.append(f"Modified: {mod_time}")
                self.logger.debug(
                    f"File size: {file_size_mb:.2f} MB, Modified: {mod_time}")
            except Exception as e:
                self.logger.warning(f"Could not get file stats: {e}")

            metadata = "\n".join(info)
            self.logger.info(
                f"Metadata extraction complete: {len(info)} fields")
            self.logger.debug(f"Final metadata: {metadata}")
            return metadata

        except Exception as e:
            self.logger.error(f"Error in get_audio_metadata: {e}")
            self.logger.error(traceback.format_exc())
            return f"Error reading metadata: {str(e)}"

    def transcribe_audio(self, audio_path: str, language: Optional[str] = None, channel: int = -1) -> str:
        """
        Transcribe audio with language detection and error handling.

        Args:
            audio_path: Path to the audio file
            language: Optional specific language code
            channel: Channel to transcribe (-1 for mono mix, 0 for left, 1 for right, etc.)

        Returns:
            str: Transcription result or error message
        """

        if not AZURE_SPEECH_AVAILABLE:
            return "Transcription unavailable - Azure Speech SDK not installed"

        start_time = time.time()
        self.logger.info(
            f"Starting transcription for {audio_path}, channel: {channel}")

        # First, check if transcription is enabled
        transcription_enabled = False
        if self.settings:
            transcription_enabled = self.settings.value(
                "enable_transcription", "false") == "true"

        if not transcription_enabled:
            self.logger.info("Transcription is disabled in settings")
            return "Transcription is disabled in settings"

        # Initialize speech services if needed
        if self.speech_config is None:
            if not self.initialize_speech_services():
                self.logger.warning("Speech services not initialized")
                return "Transcription unavailable - Azure credentials not configured"

        temp_wav = None
        speech_recognizer = None

        try:
            # Create a unique temp file path
            temp_dir = tempfile.gettempdir()
            unique_id = f"{int(time.time())}_{os.path.basename(audio_path)}_ch{channel}"
            temp_wav = os.path.join(temp_dir, f"transcribe_{unique_id}.wav")
            self.logger.debug(f"Temporary WAV file: {temp_wav}")

            # Check for cached result
            cache_key = f"transcription_{audio_path}_{language or 'auto'}_ch{channel}"
            if cache_key in self.analysis_cache:
                self.logger.info("Using cached transcription")
                return self.analysis_cache[cache_key]

            # Get duration based on transcription-specific settings
            transcription_duration = self.settings.value(
                "transcription_duration", "preview")

            if transcription_duration == "preview":
                # Use preview duration
                use_whole_signal = self.settings.value(
                    "use_whole_signal", "false") == "true"
                if use_whole_signal:
                    # If whole signal is enabled, use full file
                    max_duration = None
                else:
                    try:
                        max_duration = float(self.settings.value(
                            "preview_duration", "10.0"))
                    except (ValueError, TypeError):
                        max_duration = 10.0
            elif transcription_duration == "60":
                # Use fixed 60 seconds
                max_duration = 60.0
            elif transcription_duration == "full":
                # Use the entire file
                max_duration = None  # No limit
            else:
                # Default fallback
                max_duration = 30.0

            self.logger.debug(
                f"Transcription duration set to: {transcription_duration}, loading {max_duration if max_duration else 'all'} seconds")

            y, sr = None, None
            self.logger.info(
                f"Attempting to load audio with librosa: max_duration={max_duration}")
            try:
                # Handle channel selection for librosa
                if channel >= 0:
                    # Load specific channel (non-mono)
                    if max_duration is None:
                        y_multi, sr = librosa.load(
                            audio_path, sr=None, mono=False, duration=None)
                        self.logger.info(
                            f"Loaded FULL audio (channel mode): Total duration = {y_multi.shape[1]/sr:.2f} seconds")
                    else:
                        y_multi, sr = librosa.load(
                            audio_path, sr=None, mono=False, duration=max_duration)
                        self.logger.info(
                            f"Loaded LIMITED audio (channel mode): Duration = {y_multi.shape[1]/sr:.2f} seconds (limit was {max_duration}s)")

                    # Check if requested channel exists
                    if len(y_multi.shape) > 1 and channel < y_multi.shape[0]:
                        y = y_multi[channel]
                    else:
                        self.logger.warning(
                            f"Channel {channel} not available, defaulting to channel 0")
                        y = y_multi[0] if len(y_multi.shape) > 1 else y_multi
                else:
                    # Load as mono mix (default)
                    if max_duration is None:
                        y, sr = librosa.load(
                            audio_path, sr=None, mono=True, duration=None)
                        self.logger.info(
                            f"Loaded FULL audio (mono mode): Total duration = {len(y)/sr:.2f} seconds")
                    else:
                        y, sr = librosa.load(
                            audio_path, sr=None, mono=True, duration=max_duration)
                        self.logger.info(
                            f"Loaded LIMITED audio (mono mode): Duration = {len(y)/sr:.2f} seconds (limit was {max_duration}s)")

            except Exception as load_e:
                self.logger.warning(f"LibROSA loading failed: {load_e}")
                try:
                    # Fallback to soundfile
                    self.logger.info(
                        f"Attempting soundfile fallback with max_duration={max_duration}")
                    with sf.SoundFile(audio_path) as f:
                        self.logger.info(
                            f"SoundFile info: frames={f.frames}, sr={f.samplerate}, duration={f.frames/f.samplerate:.2f}s, channels={f.channels}")

                        if max_duration is None:
                            # Read all frames
                            self.logger.info(
                                f"Reading ALL frames ({f.frames}) from soundfile")
                            data = f.read()
                            self.logger.info(
                                f"Read complete file: {len(data)/f.samplerate:.2f}s of audio")
                        else:
                            max_frames = int(f.samplerate * max_duration)
                            self.logger.info(
                                f"Reading LIMITED frames: {max_frames}/{f.frames} from soundfile")
                            data = f.read(max_frames)
                            self.logger.info(
                                f"Read partial file: {len(data)/f.samplerate:.2f}s of audio")

                        sr = f.samplerate
                        self.logger.info(f"Loaded data shape: {data.shape}")

                        # Handle channel selection for soundfile
                        if len(data.shape) > 1:  # Multi-channel
                            self.logger.info(
                                f"Multi-channel audio: {data.shape[1]} channels detected")
                            if channel >= 0 and channel < data.shape[1]:
                                # Extract specific channel
                                self.logger.info(
                                    f"Extracting channel {channel}")
                                y = data[:, channel]
                            else:
                                # Default to mono mix
                                self.logger.info(
                                    f"Creating mono mix from {data.shape[1]} channels")
                                y = np.mean(data, axis=1)
                        else:
                            # Already mono
                            self.logger.info("Already mono audio, using as is")
                            y = data

                        self.logger.info(
                            f"Final audio for transcription: {len(y)/sr:.2f}s, {len(y)} samples at {sr}Hz")

                except Exception as sf_e:
                    self.logger.error(f"All loading methods failed: {sf_e}")
                    return "Failed to load audio for transcription"

            if y is None or sr is None:
                self.logger.error("Failed to load audio data")
                return "Failed to load audio data for transcription"

            # Write to temporary WAV file
            self.logger.debug(
                f"Writing temporary WAV with {len(y)} samples at {sr}Hz")
            sf.write(temp_wav, y, sr, format='WAV')

            # Configure language detection or specific language
            if language:
                self.logger.info(f"Using specified language: {language}")
                self.speech_config.speech_recognition_language = language
                auto_detect_config = None
            else:
                self.logger.info("Using auto language detection")
                # Limit to 4 languages since the error mentioned 4 max in DetectAudioAtStart mode
                auto_detect_config = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
                    languages=["en-US", "fr-FR", "de-DE", "es-ES"]
                )

            # Create speech recognizer
            audio_config = speechsdk.AudioConfig(filename=temp_wav)

            if auto_detect_config:
                speech_recognizer = speechsdk.SpeechRecognizer(
                    speech_config=self.speech_config,
                    audio_config=audio_config,
                    auto_detect_source_language_config=auto_detect_config
                )
            else:
                speech_recognizer = speechsdk.SpeechRecognizer(
                    speech_config=self.speech_config,
                    audio_config=audio_config
                )

            # Continuous recognition implementation
            self.logger.info("Starting continuous recognition")
            transcript_segments = []
            done = False

            def stop_cb(evt):
                nonlocal done
                self.logger.info("Recognition stopped")
                done = True

            def recognized_cb(evt):
                nonlocal transcript_segments
                if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
                    segment_text = evt.result.text
                    transcript_segments.append(segment_text)
                    self.logger.info(
                        f"Recognized segment ({len(segment_text)} chars): {segment_text}")

            # Connect callbacks
            speech_recognizer.recognized.connect(recognized_cb)
            speech_recognizer.session_stopped.connect(stop_cb)
            speech_recognizer.canceled.connect(stop_cb)

            # Start continuous recognition
            speech_recognizer.start_continuous_recognition()

            # Wait for completion (with timeout)
            start_time_recognition = time.time()
            timeout = 300  # 5 minutes timeout
            self.logger.info(
                f"Waiting for recognition to complete (timeout: {timeout}s)")
            while not done and time.time() - start_time_recognition < timeout:
                time.sleep(0.5)

            # Stop recognition
            speech_recognizer.stop_continuous_recognition()

            # Join all recognized text
            full_transcript = " ".join(transcript_segments)
            self.logger.info(
                f"Full transcription complete: {len(full_transcript)} chars")

            # Get language (from first segment if available)
            detected_language = "unknown"
            try:
                if hasattr(speech_recognizer, 'properties'):
                    # Check if properties has a get method
                    if hasattr(speech_recognizer.properties, 'get'):
                        detected_language = speech_recognizer.properties.get(
                            speechsdk.PropertyId.SpeechServiceConnection_RecoLanguage, "unknown")
                    # If no get method, try dictionary-style access
                    elif len(transcript_segments) > 0:
                        # Try to get from the first result if available
                        detected_language = "auto-detected"
            except Exception as e:
                self.logger.warning(f"Could not get detected language: {e}")
                detected_language = "unknown"

            # Format result
            channel_info = "mono mix" if channel < 0 else f"channel {channel+1}"
            output = f"Language: {detected_language}\nChannel: {channel_info}\nTranscript: {full_transcript}"

            # Cache result
            if len(self.analysis_cache) < self.max_cache_size:
                self.analysis_cache[cache_key] = output

            elapsed = time.time() - start_time
            self.logger.info(f"Transcription completed in {elapsed:.2f}s")
            return output

        except Exception as e:
            self.logger.error(f"Error in transcription: {e}")
            self.logger.error(traceback.format_exc())
            return f"Transcription error: {str(e)}"
        finally:
            # Clean up resources
            if speech_recognizer:
                speech_recognizer = None

            # Clean up temp file
            if temp_wav and os.path.exists(temp_wav):
                try:
                    os.unlink(temp_wav)
                except Exception as e:
                    self.logger.warning(
                        f"Could not delete temp file {temp_wav}: {e}")

    def process_audio_file(self, file_path: str, channel: int = 0, run_transcription: bool = False, force_refresh: bool = False) -> Optional[Tuple[str, str, io.BytesIO, Dict, str, int, Optional[float]]]:
        """
        Process audio file with comprehensive analysis and caching.

        Args:
            file_path: Path to the audio file
            channel: Channel to process (0 for left/mono, 1 for right, etc.)
            run_transcription: Whether to run transcription immediately
            force_refresh: Whether to force recalculation even if cache exists

        Returns:
            Tuple of (file_path, metadata, visualization_buffer, transcription, num_channels, channel, time_delay)
            or None on error
        """
        start_time = time.time()
        self.logger.info(
            f"Processing audio file: {file_path}, channel: {channel}, force_refresh: {force_refresh}")

        try:
            # Check cache first - only if not forcing refresh
            cache_key = f"{channel}_full_analysis"

            if not force_refresh and file_path in self.analysis_cache and cache_key in self.analysis_cache[file_path] and self.is_cache_valid(file_path):
                self.logger.info(
                    f"Using cached analysis for {file_path}, channel {channel}")
                return self.analysis_cache[file_path][cache_key]

            # Load audio with error handling
            y, sr, total_duration, num_channels = self.load_audio(
                file_path, duration=-1, channel=channel)
            if y is None:
                self.logger.error("Failed to load audio")
                return None

            # Generate metadata
            metadata = self.get_audio_metadata(file_path, total_duration)

            # Add channels info to metadata
            if num_channels > 1:
                metadata += f"\nChannels: {num_channels} (showing channel {channel+1})"

            # Generate only waveform visualization for overview tab
            viz_buffer = self.generate_waveform(y, sr)

            # Calculate time delay for stereo files
            time_delay = None
            if num_channels > 1:
                try:
                    time_delay = self.calculate_time_delay(file_path)
                    self.logger.info(f"Calculated time delay: {time_delay}")
                except Exception as e:
                    self.logger.error(f"Error calculating time delay: {e}")

            # Transcription only if explicitly requested
            transcription = None
            if run_transcription and self.settings and self.settings.value("enable_transcription", "false") == "true":
                transcription = self.transcribe_audio(file_path)

            # Prepare result with time delay
            result = (file_path, metadata, viz_buffer, transcription,
                      num_channels, channel, time_delay)

            # Store current modification time with cache
            if file_path not in self.analysis_cache:
                self.analysis_cache[file_path] = {}
            self.analysis_cache[file_path]['mtime'] = os.path.getmtime(
                file_path)

            # Cache result if not too large
            if viz_buffer is None or viz_buffer.getbuffer().nbytes < 5*1024*1024:  # 5MB limit
                self.analysis_cache[file_path][cache_key] = result

            elapsed = time.time() - start_time
            self.logger.info(f"Audio processing completed in {elapsed:.2f}s")

            return result

        except Exception as e:
            self.logger.error(f"Error in process_audio_file: {e}")
            self.logger.error(traceback.format_exc())
            return None

    def set_spectrogram_params(self, n_fft: int = 2048, hop_length: int = 512, figure_size: Tuple[int, int] = (10, 5)):
        """
        Configure spectrogram generation parameters.

        Args:
            n_fft: FFT window size
            hop_length: Hop length between frames
            figure_size: Matplotlib figure size
        """
        self.spec_n_fft = n_fft
        self.spec_hop_length = hop_length
        self.spec_figure_size = figure_size
        self.logger.debug(
            f"Set spectrogram params: n_fft={n_fft}, hop_length={hop_length}")

    def clear_cache(self, file_path: Optional[str] = None):
        """
        Clear analysis cache for a specific file or all files.

        Args:
            file_path: Path to clear cache for, or None to clear all
        """
        if file_path:
            # Clear specific file
            if file_path in self.sr_cache:
                del self.sr_cache[file_path]
            if file_path in self.duration_cache:
                del self.duration_cache[file_path]
            if file_path in self.analysis_cache:
                del self.analysis_cache[file_path]
            self.logger.debug(f"Cleared cache for {file_path}")
        else:
            # Clear all caches
            self.sr_cache.clear()
            self.duration_cache.clear()
            self.analysis_cache.clear()
            self.logger.info("Cleared all analysis caches")

    def get_cache_stats(self) -> Dict[str, int]:
        """
        Get statistics about current cache usage.

        Returns:
            Dictionary with cache statistics
        """
        return {
            'sample_rate_cache': len(self.sr_cache),
            'duration_cache': len(self.duration_cache),
            'analysis_cache': len(self.analysis_cache),
            'max_cache_size': self.max_cache_size
        }

    def generate_waveform(self, y: np.ndarray, sr: int) -> Optional[io.BytesIO]:
        """
        Generate optimized waveform visualization.

        Args:
            y: Audio data
            sr: Sample rate

        Returns:
            BytesIO buffer containing the visualization image or None on error
        """
        try:
            # Close any existing figures
            plt.close('all')

            # Create figure with appropriate size
            fig = plt.figure(figsize=(10, 2.5), facecolor='white')

            # Optimize data for display
            max_points = 10000
            if len(y) > max_points:
                decimation_factor = len(y) // max_points
                y_decimated = y[::decimation_factor]
                time_decimated = np.linspace(0, len(y) / sr, len(y_decimated))
            else:
                y_decimated = y
                time_decimated = np.linspace(0, len(y) / sr, len(y))

            # Plot with improved styling
            ax = fig.add_subplot(111)
            ax.plot(time_decimated, y_decimated, color='#3465a4', linewidth=1)
            ax.set_title('Waveform', fontsize=12)
            ax.set_xlabel('Time (s)', fontsize=10)
            ax.set_ylabel('Amplitude', fontsize=10)
            ax.set_ylim(-1.1, 1.1)
            ax.grid(True, linestyle='--', alpha=0.7, color='#cccccc')
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)

            plt.tight_layout()

            # Save to buffer
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
            plt.close(fig)
            buf.seek(0)

            return buf

        except Exception as e:
            self.logger.error(f"Error generating waveform: {e}")
            self.logger.error(traceback.format_exc())
            return None

    def generate_spectrogram(self, y: np.ndarray, sr: int, high_quality: bool = False) -> Optional[io.BytesIO]:
        """
        Generate spectrogram with quality settings.

        Args:
            y: Audio data
            sr: Sample rate
            high_quality: Whether to use higher quality settings

        Returns:
            BytesIO buffer containing the visualization image or None on error
        """
        try:
            plt.close('all')

            # Adjust parameters based on quality setting
            if high_quality:
                n_fft = min(4096, len(y))
                hop_length = n_fft // 4
                fig_size = (12, 6)
                dpi = 150
            else:
                n_fft = min(2048, len(y))
                hop_length = n_fft // 2
                fig_size = (10, 5)
                dpi = 100

            # Create figure
            fig = plt.figure(figsize=fig_size, facecolor='white')

            # Create custom grid layout
            gs = plt.GridSpec(1, 2, width_ratios=[20, 1])

            # Generate spectrogram data
            D = librosa.stft(y, n_fft=n_fft, hop_length=hop_length)
            S_db = librosa.amplitude_to_db(np.abs(D), ref=np.max)

            # Plot spectrogram
            ax = fig.add_subplot(gs[0])
            img = librosa.display.specshow(
                S_db,
                sr=sr,
                hop_length=hop_length,
                x_axis='time',
                y_axis='hz',
                cmap='viridis',
                ax=ax
            )
            ax.set_title('Spectrogram', fontsize=12)
            ax.set_xlabel('Time (s)', fontsize=10)
            ax.set_ylabel('Frequency (Hz)', fontsize=10)

            # Add colorbar
            cax = fig.add_subplot(gs[1])
            plt.colorbar(img, cax=cax, format='%+2.0f dB')

            plt.tight_layout()

            # Save figure to buffer
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=dpi, bbox_inches='tight')
            plt.close(fig)
            buf.seek(0)

            return buf

        except Exception as e:
            self.logger.error(f"Error generating spectrogram: {e}")
            self.logger.error(traceback.format_exc())
            return None

    def generate_mel_spectrogram(self, y: np.ndarray, sr: int) -> Optional[io.BytesIO]:
        """
        Generate mel spectrogram visualization.

        Args:
            y: Audio data
            sr: Sample rate

        Returns:
            BytesIO buffer containing the visualization image or None on error
        """
        try:
            plt.close('all')

            # Create figure
            fig = plt.figure(figsize=(10, 5), facecolor='white')

            # Calculate mel spectrogram
            S = librosa.feature.melspectrogram(
                y=y, sr=sr, n_mels=128, fmax=8000)
            S_dB = librosa.power_to_db(S, ref=np.max)

            # Plot
            ax = plt.subplot(111)
            img = librosa.display.specshow(
                S_dB, x_axis='time', y_axis='mel', sr=sr, fmax=8000, ax=ax)
            plt.colorbar(img, format='%+2.0f dB')
            plt.title('Mel Spectrogram')
            plt.tight_layout()

            # Save to buffer
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
            plt.close(fig)
            buf.seek(0)

            return buf

        except Exception as e:
            self.logger.error(f"Error generating mel spectrogram: {e}")
            self.logger.error(traceback.format_exc())
            return None

    def generate_chromagram(self, y: np.ndarray, sr: int) -> Optional[io.BytesIO]:
        """
        Generate chromagram for tonal content analysis.

        Args:
            y: Audio data
            sr: Sample rate

        Returns:
            BytesIO buffer containing the visualization image or None on error
        """
        try:
            plt.close('all')

            # Compute chromagram
            # Use harmonic separation to focus on tonal content
            y_harmonic = librosa.effects.harmonic(y)
            chroma = librosa.feature.chroma_cqt(y=y_harmonic, sr=sr)

            # Create plot
            fig = plt.figure(figsize=(10, 4), facecolor='white')
            ax = plt.subplot(111)
            img = librosa.display.specshow(
                chroma,
                y_axis='chroma',
                x_axis='time',
                ax=ax,
                cmap='coolwarm'
            )
            plt.colorbar(img)
            plt.title('Chromagram (Pitch Class Content)')
            plt.tight_layout()

            # Save to buffer
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
            plt.close(fig)
            buf.seek(0)

            return buf

        except Exception as e:
            self.logger.error(f"Error generating chromagram: {e}")
            self.logger.error(traceback.format_exc())
            return None

    def generate_visualizations(self, y: np.ndarray, sr: int, file_path: str, quality: str = 'normal', channel: int = 0) -> Optional[io.BytesIO]:
        """
        Generate combined visualizations with progress updates.

        Args:
            y: Audio data
            sr: Sample rate
            file_path: Path to the audio file (for caching)
            quality: Visualization quality ('normal' or 'high')
            channel: Channel number (for caching)

        Returns:
            BytesIO buffer containing the visualization image or None on error
        """
        start_time = time.time()
        self.logger.info(
            f"Generating visualizations for {file_path}, channel {channel}")

        try:
            # Check if visualization in cache
            cache_key = f"{file_path}_{channel}_{quality}"
            if cache_key in self.analysis_cache:
                self.logger.info("Using cached visualizations")
                return self.analysis_cache[cache_key].get('visualizations')

            # Close any existing plots
            plt.close('all')

            # Create multi-panel figure
            fig = plt.figure(figsize=(12, 8), facecolor='white')

            # Configure grid layout - waveform on top, spectrogram below
            gs = plt.GridSpec(2, 1, height_ratios=[1, 2], hspace=0.3)

            # Generate and plot waveform
            waveform_start = time.time()
            self.logger.debug("Generating waveform...")

            # Optimize display by decimating
            max_points = 10000
            if len(y) > max_points:
                decimation_factor = len(y) // max_points
                y_decimated = y[::decimation_factor]
                time_decimated = np.linspace(0, len(y) / sr, len(y_decimated))
            else:
                y_decimated = y
                time_decimated = np.linspace(0, len(y) / sr, len(y))

            # Plot waveform
            ax0 = fig.add_subplot(gs[0])
            ax0.plot(time_decimated, y_decimated, color='#3465a4', linewidth=1)
            channel_label = f"Channel {channel+1}" if channel > 0 else "Left/Mono Channel"
            ax0.set_title(f'Waveform - {channel_label}', fontsize=12)
            ax0.set_xlabel('Time (s)', fontsize=10)
            ax0.set_ylabel('Amplitude', fontsize=10)
            ax0.set_ylim(-1.1, 1.1)
            ax0.grid(True, linestyle='--', alpha=0.7, color='#cccccc')
            ax0.spines['top'].set_visible(False)
            ax0.spines['right'].set_visible(False)

            waveform_time = time.time() - waveform_start
            self.logger.debug(f"Waveform generated in {waveform_time:.2f}s")

            # Generate spectrogram subplot with separate colorbar
            spec_start = time.time()
            self.logger.debug("Generating spectrogram...")

            # Create nested GridSpec for spectrogram and colorbar
            gs1 = gridspec.GridSpecFromSubplotSpec(
                1, 2, subplot_spec=gs[1], width_ratios=[20, 1])
            ax1 = fig.add_subplot(gs1[0])

            # Configure spectrogram quality
            if quality == 'high':
                n_fft = min(4096, len(y))
                hop_length = n_fft // 4
            else:
                n_fft = min(2048, len(y))
                hop_length = n_fft // 2

            # Calculate spectrogram
            D = librosa.stft(y, n_fft=n_fft, hop_length=hop_length)
            S_db = librosa.amplitude_to_db(np.abs(D), ref=np.max)

            # Plot spectrogram
            img = librosa.display.specshow(
                S_db,
                sr=sr,
                hop_length=hop_length,
                x_axis='time',
                y_axis='log',
                ax=ax1,
                cmap='viridis'
            )
            ax1.set_title(f'Spectrogram - {channel_label}', fontsize=12)
            ax1.set_xlabel('Time (s)', fontsize=10)
            ax1.set_ylabel('Frequency (Hz)', fontsize=10)

            # Add colorbar
            cax = fig.add_subplot(gs1[1])
            plt.colorbar(img, cax=cax, format='%+2.0f dB')

            spec_time = time.time() - spec_start
            self.logger.debug(f"Spectrogram generated in {spec_time:.2f}s")

            # Final layout adjustments
            plt.tight_layout()

            # Save to buffer
            save_start = time.time()
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
            plt.close(fig)
            buf.seek(0)

            save_time = time.time() - save_start
            self.logger.debug(f"Visualization saved in {save_time:.2f}s")

            total_time = time.time() - start_time
            self.logger.info(f"Visualizations generated in {total_time:.2f}s")

            # Cache result
            if len(self.analysis_cache) < self.max_cache_size:
                if cache_key not in self.analysis_cache:
                    self.analysis_cache[cache_key] = {}
                self.analysis_cache[cache_key]['visualizations'] = buf

            return buf

        except Exception as e:
            self.logger.error(f"Error generating visualizations: {e}")
            self.logger.error(traceback.format_exc())
            return None
