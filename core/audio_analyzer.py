"""
Audio Analyzer Module
---------------------
Core functionality for audio file analysis: decoding, statistics, visualizations
and optional Azure speech transcription.

Heavy libraries (librosa, PyAV, Azure SDK) are imported on first use so the
tray icon appears quickly at Windows login.
"""

import os
import io
import time
import logging
import traceback
import tempfile
from collections import Counter
from typing import Optional, Dict, Any

import numpy as np
import soundfile as sf
import matplotlib
matplotlib.use('Agg')  # Non-GUI backend; figures are rendered to PNG buffers
from matplotlib.figure import Figure

try:
    import mutagen
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

try:
    import importlib.util
    AZURE_SPEECH_AVAILABLE = importlib.util.find_spec(
        "azure.cognitiveservices.speech") is not None
except (ImportError, ValueError):
    AZURE_SPEECH_AVAILABLE = False


# Spectrogram-type views and the double waveform never process more than this,
# even with "use whole signal": a 2 h file would otherwise need several GB of RAM.
MAX_VIZ_SECONDS = 600
# Stereo delay is estimated on the start of the file only.
DELAY_WINDOW_SECONDS = 30
# Peak-to-noise ratio of the GCC-PHAT curve below which the delay is flagged unreliable.
DELAY_CONFIDENCE_MIN = 20.0
# Number of min/max buckets drawn in a waveform.
WAVEFORM_POINTS = 2000
# Samples at or above this absolute level are counted as clipped.
CLIP_LEVEL = 0.999

_BIT_DEPTHS = {
    'PCM_S8': '8-bit', 'PCM_U8': '8-bit', 'PCM_16': '16-bit', 'PCM_24': '24-bit',
    'PCM_32': '32-bit', 'FLOAT': '32-bit float', 'DOUBLE': '64-bit float',
}


class TranscriptionCancelled(Exception):
    """Raised when the user cancels a running transcription."""


def _librosa():
    """Import librosa lazily (it pulls numba/llvmlite and takes seconds to load)."""
    import librosa
    import librosa.display  # noqa: F401 - registers librosa.display
    return librosa


def _png(fig: Figure, dpi: int = 100) -> io.BytesIO:
    """Render a matplotlib Figure to a PNG buffer."""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=dpi, bbox_inches='tight')
    buf.seek(0)
    return buf


class AudioAnalyzer:
    """Audio analyzer with caching, streaming statistics and thread-safe plotting."""

    def __init__(self, settings=None):
        self.logger = logging.getLogger("AudioAnalyzer")
        self.settings = settings
        self.speech_config = None
        self.initialized = False

        self.info_cache = {}       # (path, mtime, size) -> info dict
        self.analysis_cache = {}   # path -> {mtime, "<ch>_full_analysis"}; transcription keys
        self._delay_cache = {}     # (path, mtime) -> delay dict or None
        self.max_cache_size = 20

        self.chunk_duration = 10.0  # Default preview duration in seconds
        self.spec_n_fft = 2048
        self.spec_hop_length = 512

        matplotlib.rcParams['figure.dpi'] = 100
        matplotlib.rcParams['savefig.dpi'] = 150
        matplotlib.rcParams['font.size'] = 10

        self.logger.info("AudioAnalyzer initialized")

    def warm_up(self):
        """Pre-import heavy libraries (called from a background thread after startup)."""
        try:
            _librosa()
            self.logger.info("librosa pre-loaded")
        except Exception as e:
            self.logger.warning(f"librosa pre-load failed: {e}")

    def is_cache_valid(self, file_path: str) -> bool:
        """Check if cached analysis for a file is still valid (file not modified)."""
        if not os.path.exists(file_path):
            return False

        current_mtime = os.path.getmtime(file_path)

        if 'mtime' not in self.analysis_cache.get(file_path, {}):
            if file_path not in self.analysis_cache:
                self.analysis_cache[file_path] = {}
            self.analysis_cache[file_path]['mtime'] = current_mtime
            return False

        cached_mtime = self.analysis_cache[file_path]['mtime']
        if current_mtime > cached_mtime:
            self.logger.info(
                f"File {file_path} has been modified since last analysis")
            self.analysis_cache[file_path]['mtime'] = current_mtime
            return False

        return True

    # ------------------------------------------------------------------ #
    # Stereo delay (GCC-PHAT)
    # ------------------------------------------------------------------ #

    def gcc_phat(self, s1: np.ndarray, s2: np.ndarray, fs: int,
                 fmin: float = 0, fmax: float = 8000):
        """
        GCC-PHAT delay between two signals, restricted to the [fmin, fmax] band.

        Returns:
            (delay_ms, confidence): delay of the correlation peak and its
            peak-to-noise ratio (peak / standard deviation of the curve).
        """
        from scipy.fft import next_fast_len

        n = len(s1)
        nfft = next_fast_len(2 * n)  # zero-padded: no circular wrap-around
        X1 = np.fft.rfft(s1, nfft)
        X2 = np.fft.rfft(s2, nfft)
        Pxy = X1 * np.conj(X2)

        freqs = np.fft.rfftfreq(nfft, 1.0 / fs)
        band = (freqs >= fmin) & (freqs <= fmax)
        mag = np.abs(Pxy)
        R = np.zeros_like(Pxy)
        keep = band & (mag > 1e-12)
        R[keep] = Pxy[keep] / mag[keep]

        g = np.fft.irfft(R, nfft)
        # Reorder to lags -(n-1) .. (n-1)
        g = np.concatenate((g[-(n - 1):], g[:n])) if n > 1 else g[:1]
        lags = np.arange(-(n - 1), n)

        peak = int(np.argmax(g))
        std = float(np.std(g))
        confidence = float(g[peak] / std) if std > 0 else 0.0
        delay_ms = float(lags[peak]) / fs * 1000.0
        return delay_ms, confidence

    def calculate_time_delay(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        Delay between the first two channels, measured on the first
        DELAY_WINDOW_SECONDS. Cached per file (it does not depend on the
        displayed channel).

        Returns:
            {"ms": float, "confidence": float, "reliable": bool} or None.
        """
        try:
            key = (file_path, os.path.getmtime(file_path))
            if key in self._delay_cache:
                return self._delay_cache[key]

            y, sr, _, num_channels = self.load_audio(
                file_path, duration=DELAY_WINDOW_SECONDS, all_channels=True)
            result = None
            if y is not None and num_channels >= 2 and len(y) > 1:
                left, right = y[:, 0], y[:, 1]
                if np.max(np.abs(left)) > 1e-8 and np.max(np.abs(right)) > 1e-8:
                    delay_ms, confidence = self.gcc_phat(left, right, sr)
                    result = {
                        "ms": delay_ms,
                        "confidence": confidence,
                        "reliable": confidence >= DELAY_CONFIDENCE_MIN,
                    }
                    self.logger.info(
                        f"Time delay: {delay_ms:.3f} ms (confidence {confidence:.1f})")

            self._delay_cache[key] = result
            return result

        except Exception as e:
            self.logger.error(f"Error calculating time delay: {e}")
            self.logger.error(traceback.format_exc())
            return None

    # ------------------------------------------------------------------ #
    # Setup
    # ------------------------------------------------------------------ #

    def initialize(self) -> bool:
        """Fully initialize the analyzer with settings."""
        if self.initialized:
            return True

        try:
            self.logger.info("Initializing audio analyzer")
            if self.settings:
                self.chunk_duration = float(
                    self.settings.value("preview_duration", "10.0"))
            self.initialized = True
            return True

        except Exception as e:
            self.logger.error(f"Initialization failed: {e}")
            self.logger.error(traceback.format_exc())
            return False

    def initialize_speech_services(self) -> bool:
        """Create the Azure speech config from settings. Returns True on success."""
        if not AZURE_SPEECH_AVAILABLE:
            self.logger.warning("Azure Speech Services package not installed")
            return False

        if not self.settings:
            return False

        if self.settings.value("enable_transcription", "false") != "true":
            self.logger.info("Speech transcription is disabled in settings")
            return False

        azure_key = self.settings.value("azure_key", "")
        azure_region = self.settings.value("azure_region", "")
        if not azure_key or not azure_region:
            self.logger.warning("Azure credentials not found in settings")
            return False

        try:
            import azure.cognitiveservices.speech as speechsdk
            self.speech_config = speechsdk.SpeechConfig(
                subscription=azure_key, region=azure_region)
            self.logger.info(
                f"Speech services initialized with region: {azure_region}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize speech services: {e}")
            self.logger.error(traceback.format_exc())
            return False

    # ------------------------------------------------------------------ #
    # Decoding
    # ------------------------------------------------------------------ #

    def get_audio_info(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        Basic stream information without decoding the whole file.
        Uses soundfile (WAV/FLAC/MP3/OGG/AIFF...) and falls back to PyAV
        (bundled FFmpeg: M4A/AAC/WMA/MP4/APE/WavPack/Opus...).
        """
        try:
            stat = os.stat(file_path)
        except OSError as e:
            self.logger.error(f"Cannot stat {file_path}: {e}")
            return None

        key = (file_path, stat.st_mtime, stat.st_size)
        if key in self.info_cache:
            return self.info_cache[key]

        info = None
        try:
            sfi = sf.info(file_path)
            info = {
                "sr": sfi.samplerate, "channels": sfi.channels,
                "duration": sfi.duration, "frames": sfi.frames,
                "subtype": sfi.subtype, "decoder": "sf",
            }
        except Exception as sf_e:
            self.logger.debug(f"soundfile cannot read {file_path}: {sf_e}")
            try:
                info = self._av_info(file_path)
            except Exception as av_e:
                self.logger.error(f"Unsupported or unreadable audio: {av_e}")

        if info:
            self.info_cache[key] = info
        return info

    def _av_info(self, file_path: str) -> Dict[str, Any]:
        import av
        with av.open(file_path) as container:
            stream = container.streams.audio[0]
            sr = stream.codec_context.sample_rate
            channels = stream.codec_context.channels
            if stream.duration is not None and stream.time_base is not None:
                duration = float(stream.duration * stream.time_base)
            elif container.duration is not None:
                duration = container.duration / 1_000_000
            else:
                duration = 0.0
            return {
                "sr": sr, "channels": channels, "duration": duration,
                "frames": int(duration * sr),
                "subtype": stream.codec_context.name.upper(), "decoder": "av",
            }

    def _av_decode(self, file_path: str, max_seconds: Optional[float] = None):
        """Decode with PyAV to float32 array of shape (frames, channels)."""
        import av
        with av.open(file_path) as container:
            stream = container.streams.audio[0]
            sr = stream.codec_context.sample_rate
            channels = stream.codec_context.channels
            resampler = av.AudioResampler(
                format='fltp', layout=stream.codec_context.layout.name, rate=sr)
            limit = int(max_seconds * sr) if max_seconds else None
            chunks, total = [], 0
            for frame in container.decode(stream):
                for out in resampler.resample(frame):
                    arr = out.to_ndarray()  # (channels, samples)
                    chunks.append(arr)
                    total += arr.shape[1]
                if limit is not None and total >= limit:
                    break

        if chunks:
            y = np.concatenate(chunks, axis=1).T
        else:
            y = np.zeros((0, channels), dtype=np.float32)
        if limit is not None:
            y = y[:limit]
        return np.ascontiguousarray(y, dtype=np.float32), sr

    def load_audio(self, audio_path: str, duration: Optional[float] = None,
                   channel: int = 0, all_channels: bool = False):
        """
        Load audio as float32.

        Args:
            duration: seconds to load from the start (-1 = whole file,
                      None = preview duration)
            channel: channel to return when all_channels is False
            all_channels: return shape (frames, channels) instead of one channel

        Returns:
            (audio_data, sample_rate, total_duration, num_channels), or
            (None, None, None, None) on error.
        """
        if duration is None:
            duration = self.chunk_duration

        start_time = time.time()
        try:
            info = self.get_audio_info(audio_path)
            if info is None:
                return None, None, None, None

            num_channels = info["channels"]
            if not all_channels and channel >= num_channels:
                self.logger.error(
                    f"Requested channel {channel} exceeds available channels ({num_channels})")
                return None, None, None, None

            seconds = None if duration == -1 or duration >= info["duration"] else duration

            y = None
            sr = info["sr"]
            if info["decoder"] == "sf":
                try:
                    with sf.SoundFile(audio_path) as f:
                        frames = -1 if seconds is None else int(seconds * f.samplerate)
                        y = f.read(frames, dtype='float32', always_2d=True)
                except Exception as sf_e:
                    self.logger.warning(f"soundfile read failed, trying PyAV: {sf_e}")
            if y is None:
                y, sr = self._av_decode(audio_path, seconds)

            if not all_channels:
                y = y[:, channel]

            self.logger.info(
                f"Audio loaded in {time.time() - start_time:.2f}s - Shape: {y.shape}, SR: {sr}Hz")
            return y, sr, info["duration"], num_channels

        except Exception as e:
            self.logger.error(f"Unexpected error loading audio: {e}")
            self.logger.error(traceback.format_exc())
            return None, None, None, None

    def _maintain_cache_size(self):
        """Prevent caches from growing too large (oldest entries dropped first)."""
        for cache in (self.info_cache, self.analysis_cache, self._delay_cache):
            excess = len(cache) - self.max_cache_size
            if excess > 0:
                for key in list(cache.keys())[:excess]:
                    del cache[key]

    # ------------------------------------------------------------------ #
    # Waveform envelope and level statistics
    # ------------------------------------------------------------------ #

    @staticmethod
    def _accumulate(x: np.ndarray, bucket: int, acc: Dict[str, Any]):
        """Add one block of samples to the min/max envelope and level stats."""
        if len(x) == 0:
            return
        ax = np.abs(x)
        acc["peak"] = max(acc["peak"], float(ax.max()))
        acc["clipped"] += int(np.count_nonzero(ax >= CLIP_LEVEL))
        full = len(x) // bucket * bucket
        if full:
            r = x[:full].reshape(-1, bucket)
            acc["mins"].append(r.min(axis=1))
            acc["maxs"].append(r.max(axis=1))
        if full < len(x):
            acc["mins"].append(np.array([x[full:].min()]))
            acc["maxs"].append(np.array([x[full:].max()]))

    @staticmethod
    def _finish(acc: Dict[str, Any]):
        mins = np.concatenate(acc["mins"]) if acc["mins"] else np.zeros(1)
        maxs = np.concatenate(acc["maxs"]) if acc["maxs"] else np.zeros(1)
        return mins, maxs, acc["peak"], acc["clipped"]

    def _scan_channel(self, file_path: str, channel: int, info: Dict[str, Any]):
        """
        One pass over a channel: min/max envelope, peak level and clipped
        sample count. Streams soundfile-readable files in blocks (constant
        memory); other formats are decoded in full.
        """
        acc = {"mins": [], "maxs": [], "peak": 0.0, "clipped": 0}

        if info["decoder"] == "sf":
            bucket = max(1, info["frames"] // WAVEFORM_POINTS)
            blocksize = bucket * 64
            for block in sf.blocks(file_path, blocksize=blocksize,
                                   dtype='float32', always_2d=True):
                self._accumulate(block[:, channel], bucket, acc)
        else:
            y, _, _, _ = self.load_audio(file_path, duration=-1, channel=channel)
            if y is None:
                return None
            bucket = max(1, len(y) // WAVEFORM_POINTS)
            self._accumulate(y, bucket, acc)

        return self._finish(acc)

    def _envelope(self, y: np.ndarray):
        acc = {"mins": [], "maxs": [], "peak": 0.0, "clipped": 0}
        self._accumulate(y, max(1, len(y) // WAVEFORM_POINTS), acc)
        mins, maxs, _, _ = self._finish(acc)
        return mins, maxs

    def _plot_envelope(self, mins, maxs, duration: float, title: str = 'Waveform'):
        fig = Figure(figsize=(10, 2.5), facecolor='white')
        ax = fig.add_subplot(111)
        t = np.linspace(0, duration, len(maxs))
        if np.array_equal(mins, maxs):
            ax.plot(t, maxs, color='#3465a4', linewidth=1)
        else:
            ax.fill_between(t, mins, maxs, color='#3465a4', linewidth=0.5)
        ax.set_title(title, fontsize=12)
        ax.set_xlabel('Time (s)', fontsize=10)
        ax.set_ylabel('Amplitude', fontsize=10)
        ax.set_ylim(-1.1, 1.1)
        ax.grid(True, linestyle='--', alpha=0.7, color='#cccccc')
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        fig.tight_layout()
        return _png(fig)

    # ------------------------------------------------------------------ #
    # Metadata
    # ------------------------------------------------------------------ #

    def get_audio_metadata(self, file_path: str, info: Dict[str, Any], channel: int = 0,
                           peak: Optional[float] = None, clipped: Optional[int] = None) -> str:
        """Format metadata and level statistics as display text."""
        try:
            total = int(info["duration"])
            hours, rem = divmod(total, 3600)
            minutes, seconds = divmod(rem, 60)
            duration_str = (f"{hours}:{minutes:02d}:{seconds:02d}" if hours
                            else f"{minutes}:{seconds:02d}")

            lines = [f"Duration: {duration_str}", f"Sample Rate: {info['sr']} Hz"]

            channels_line = f"Channels: {info['channels']}"
            if info["channels"] > 1:
                channels_line += f" (showing channel {channel + 1})"
            lines.append(channels_line)

            bit_depth = _BIT_DEPTHS.get(info["subtype"])
            audio = None
            if MUTAGEN_AVAILABLE:
                try:
                    audio = mutagen.File(file_path, easy=True)
                except Exception as e:
                    self.logger.warning(f"mutagen could not read tags: {e}")
            if not bit_depth and audio is not None:
                bits = getattr(audio.info, 'bits_per_sample', 0)
                if bits:
                    bit_depth = f"{bits}-bit"
            lines.append(f"Format: {info['subtype']}" +
                         (f" ({bit_depth})" if bit_depth else ""))

            if audio is not None:
                bitrate = getattr(audio.info, 'bitrate', 0)
                if bitrate:
                    lines.append(f"Bitrate: {int(bitrate) // 1000} kbps")
                if audio.tags:
                    for key in ['title', 'artist', 'album', 'date', 'genre']:
                        try:
                            value = audio.tags.get(key)
                        except Exception:
                            value = None
                        if value:
                            lines.append(f"{key.capitalize()}: {value[0]}")

            if peak is not None:
                peak_db = f"{round(20 * np.log10(peak), 1) + 0.0} dBFS" if peak > 0 else "-inf dBFS (silence)"
                lines.append(f"Peak: {peak_db}")
            if clipped is not None:
                lines.append(f"Clipped samples (≥ {CLIP_LEVEL}): {clipped}")

            stat = os.stat(file_path)
            lines.append(f"File Size: {stat.st_size / (1024 * 1024):.2f} MB")
            lines.append("Modified: " + time.strftime(
                '%Y-%m-%d %H:%M:%S', time.localtime(stat.st_mtime)))

            return "\n".join(lines)

        except Exception as e:
            self.logger.error(f"Error in get_audio_metadata: {e}")
            self.logger.error(traceback.format_exc())
            return f"Error reading metadata: {str(e)}"

    # ------------------------------------------------------------------ #
    # Transcription
    # ------------------------------------------------------------------ #

    def transcribe_audio(self, audio_path: str, language: Optional[str] = None,
                         channel: int = -1, should_cancel=None) -> str:
        """
        Transcribe audio with Azure Speech.

        Args:
            language: language code, or None/"" for auto-detection
            channel: channel to transcribe (-1 = mono mix)
            should_cancel: optional callable returning True to abort

        Returns:
            Formatted transcription text.

        Raises:
            RuntimeError: with a user-readable reason when transcription fails.
            TranscriptionCancelled: when should_cancel() returned True.
        """
        if not AZURE_SPEECH_AVAILABLE:
            raise RuntimeError("Azure Speech SDK is not installed.")
        if not self.settings or self.settings.value("enable_transcription", "false") != "true":
            raise RuntimeError("Transcription is disabled. Enable it in Settings → Transcription.")
        if self.speech_config is None and not self.initialize_speech_services():
            raise RuntimeError(
                "Azure credentials are not configured. Set them in Settings → Transcription.")

        import azure.cognitiveservices.speech as speechsdk
        import soxr

        cache_key = f"transcription_{audio_path}_{language or 'auto'}_ch{channel}"
        if cache_key in self.analysis_cache:
            self.logger.info("Using cached transcription")
            return self.analysis_cache[cache_key]

        transcription_duration = self.settings.value("transcription_duration", "preview")
        if transcription_duration == "preview":
            if self.settings.value("use_whole_signal", "false") == "true":
                max_duration = -1
            else:
                try:
                    max_duration = float(self.settings.value("preview_duration", "10.0"))
                except (ValueError, TypeError):
                    max_duration = 10.0
        elif transcription_duration == "60":
            max_duration = 60.0
        elif transcription_duration == "full":
            max_duration = -1
        else:
            max_duration = 30.0

        y, sr, _, num_channels = self.load_audio(
            audio_path, duration=max_duration, all_channels=True)
        if y is None or len(y) == 0:
            raise RuntimeError("Could not read the audio file.")

        x = y[:, channel] if 0 <= channel < num_channels else y.mean(axis=1)
        if sr != 16000:  # Azure expects 16 kHz mono 16-bit PCM
            x = soxr.resample(x, sr, 16000)
        seconds = len(x) / 16000

        fd, temp_wav = tempfile.mkstemp(prefix="audiotooltip_", suffix=".wav")
        os.close(fd)
        speech_recognizer = None
        audio_config = None
        try:
            sf.write(temp_wav, x, 16000, subtype='PCM_16')

            if language:
                self.speech_config.speech_recognition_language = language
                auto_detect_config = None
            else:
                # DetectAudioAtStart mode accepts at most 4 candidate languages
                auto_detect_config = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
                    languages=["en-US", "fr-FR", "de-DE", "es-ES"])

            audio_config = speechsdk.AudioConfig(filename=temp_wav)
            kwargs = {"speech_config": self.speech_config, "audio_config": audio_config}
            if auto_detect_config:
                kwargs["auto_detect_source_language_config"] = auto_detect_config
            speech_recognizer = speechsdk.SpeechRecognizer(**kwargs)

            segments, detected = [], []
            state = {"done": False, "error": None}

            def recognized_cb(evt):
                if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
                    segments.append(evt.result.text)
                    if auto_detect_config:
                        try:
                            lang = speechsdk.AutoDetectSourceLanguageResult(evt.result).language
                            if lang:
                                detected.append(lang)
                        except Exception:
                            pass

            def canceled_cb(evt):
                details = evt.cancellation_details
                if details.reason == speechsdk.CancellationReason.Error:
                    state["error"] = details.error_details or str(details.reason)
                state["done"] = True

            def stopped_cb(evt):
                state["done"] = True

            speech_recognizer.recognized.connect(recognized_cb)
            speech_recognizer.canceled.connect(canceled_cb)
            speech_recognizer.session_stopped.connect(stopped_cb)

            speech_recognizer.start_continuous_recognition()

            timeout = max(300.0, seconds * 1.5 + 60)
            started = time.time()
            cancelled = timed_out = False
            while not state["done"]:
                if should_cancel and should_cancel():
                    cancelled = True
                    break
                if time.time() - started > timeout:
                    timed_out = True
                    break
                time.sleep(0.2)

            speech_recognizer.stop_continuous_recognition()

            if cancelled:
                raise TranscriptionCancelled()
            if state["error"]:
                raise RuntimeError(f"Azure Speech error: {state['error']}")

            text = " ".join(segments).strip()
            if not text:
                raise RuntimeError("No speech detected in the selected audio.")

            detected_language = language or (
                Counter(detected).most_common(1)[0][0] if detected else "unknown")
            channel_info = "mono mix" if channel < 0 else f"channel {channel + 1}"
            output = (f"Language: {detected_language}\nChannel: {channel_info}\n"
                      f"Transcript: {text}")
            if timed_out:
                output += f"\n\n[Stopped after {int(timeout)} s timeout — transcript is incomplete]"
            elif len(self.analysis_cache) < self.max_cache_size:
                self.analysis_cache[cache_key] = output
            return output

        finally:
            speech_recognizer = None
            audio_config = None
            try:
                os.unlink(temp_wav)
            except OSError as e:
                self.logger.warning(f"Could not delete temp file {temp_wav}: {e}")

    # ------------------------------------------------------------------ #
    # Overview analysis
    # ------------------------------------------------------------------ #

    def process_audio_file(self, file_path: str, channel: int = 0,
                           run_transcription: bool = False, force_refresh: bool = False):
        """
        Overview analysis of one channel: metadata, level stats, waveform of
        the whole file and stereo delay.

        Returns:
            (file_path, metadata, waveform_buffer, transcription, num_channels,
             channel, time_delay) or None on error.
        """
        start_time = time.time()
        self.logger.info(
            f"Processing audio file: {file_path}, channel: {channel}, force_refresh: {force_refresh}")

        try:
            cache_key = f"{channel}_full_analysis"
            if (not force_refresh and file_path in self.analysis_cache
                    and cache_key in self.analysis_cache[file_path]
                    and self.is_cache_valid(file_path)):
                self.logger.info(f"Using cached analysis for {file_path}, channel {channel}")
                return self.analysis_cache[file_path][cache_key]

            if force_refresh:
                self.clear_cache(file_path)

            info = self.get_audio_info(file_path)
            if info is None:
                return None
            if channel >= info["channels"]:
                self.logger.error(f"Channel {channel} not available")
                return None

            scan = self._scan_channel(file_path, channel, info)
            if scan is None:
                return None
            mins, maxs, peak, clipped = scan

            viz_buffer = self._plot_envelope(mins, maxs, info["duration"])
            metadata = self.get_audio_metadata(file_path, info, channel, peak, clipped)

            time_delay = None
            if info["channels"] > 1:
                time_delay = self.calculate_time_delay(file_path)

            transcription = None
            if run_transcription:
                try:
                    transcription = self.transcribe_audio(file_path)
                except Exception as e:
                    self.logger.warning(f"Transcription skipped: {e}")

            result = (file_path, metadata, viz_buffer, transcription,
                      info["channels"], channel, time_delay)

            if file_path not in self.analysis_cache:
                self.analysis_cache[file_path] = {}
            self.analysis_cache[file_path]['mtime'] = os.path.getmtime(file_path)
            self.analysis_cache[file_path][cache_key] = result
            self._maintain_cache_size()

            self.logger.info(f"Audio processing completed in {time.time() - start_time:.2f}s")
            return result

        except Exception as e:
            self.logger.error(f"Error in process_audio_file: {e}")
            self.logger.error(traceback.format_exc())
            return None

    def set_spectrogram_params(self, n_fft: int = 2048, hop_length: int = 512, figure_size=(10, 5)):
        """Configure spectrogram generation parameters."""
        self.spec_n_fft = n_fft
        self.spec_hop_length = hop_length
        self.spec_figure_size = figure_size

    def clear_cache(self, file_path: Optional[str] = None):
        """Clear caches for a specific file or all files."""
        if file_path:
            for cache in (self.info_cache, self._delay_cache):
                for key in [k for k in cache if k[0] == file_path]:
                    del cache[key]
            self.analysis_cache.pop(file_path, None)
        else:
            self.info_cache.clear()
            self._delay_cache.clear()
            self.analysis_cache.clear()

    def get_cache_stats(self) -> Dict[str, int]:
        """Get statistics about current cache usage."""
        return {
            'info_cache': len(self.info_cache),
            'delay_cache': len(self._delay_cache),
            'analysis_cache': len(self.analysis_cache),
            'max_cache_size': self.max_cache_size
        }

    # ------------------------------------------------------------------ #
    # Visualizations (each builds its own Figure: safe across worker threads)
    # ------------------------------------------------------------------ #

    def generate_waveform(self, y: np.ndarray, sr: int) -> Optional[io.BytesIO]:
        """Waveform drawn as a min/max envelope so peaks and clipping stay visible."""
        try:
            mins, maxs = self._envelope(y)
            return self._plot_envelope(mins, maxs, len(y) / sr)
        except Exception as e:
            self.logger.error(f"Error generating waveform: {e}")
            self.logger.error(traceback.format_exc())
            return None

    def generate_double_waveform(self, file_path: str, duration: float = -1) -> Optional[io.BytesIO]:
        """
        Stereo view: left channel envelope above zero (red), right channel
        envelope below zero (blue). Returns None for non-stereo files.
        """
        try:
            y, sr, _, num_channels = self.load_audio(
                file_path, duration=duration, all_channels=True)
            if y is None or num_channels < 2:
                self.logger.warning(
                    f"Double waveform requires stereo audio, found {num_channels} channels")
                return None

            _, left_max = self._envelope(y[:, 0])
            right_min, _ = self._envelope(y[:, 1])
            left_pos = np.maximum(left_max, 0)
            right_neg = np.minimum(right_min, 0)
            t = np.linspace(0, len(y) / sr, len(left_pos))

            fig = Figure(figsize=(10, 4), facecolor='white')
            ax = fig.add_subplot(111)
            ax.fill_between(t, left_pos, 0, color='#e74c3c', alpha=0.7,
                            label='Left Channel (positive)')
            ax.fill_between(t, right_neg, 0, color='#3498db', alpha=0.7,
                            label='Right Channel (negative)')
            ax.set_title('Double Waveform - Stereo Channels', fontsize=12)
            ax.set_xlabel('Time (s)', fontsize=10)
            ax.set_ylabel('Amplitude', fontsize=10)
            ax.set_ylim(-1.1, 1.1)
            ax.grid(True, linestyle='--', alpha=0.7, color='#cccccc')
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.legend(loc='upper right', framealpha=0.9)
            ax.axhline(y=0, color='#888888', linestyle='-', linewidth=0.8)
            fig.tight_layout()
            return _png(fig)

        except Exception as e:
            self.logger.error(f"Error generating double waveform: {e}")
            self.logger.error(traceback.format_exc())
            return None

    def generate_spectrogram(self, y: np.ndarray, sr: int, high_quality: bool = False) -> Optional[io.BytesIO]:
        """Linear-frequency spectrogram in dB."""
        try:
            librosa = _librosa()
            if high_quality:
                n_fft = min(4096, len(y))
                hop_length = max(1, n_fft // 4)
                fig_size, dpi = (12, 6), 150
            else:
                n_fft = min(2048, len(y))
                hop_length = max(1, n_fft // 2)
                fig_size, dpi = (10, 5), 100

            D = librosa.stft(y, n_fft=n_fft, hop_length=hop_length)
            S_db = librosa.amplitude_to_db(np.abs(D), ref=np.max)

            fig = Figure(figsize=fig_size, facecolor='white')
            gs = fig.add_gridspec(1, 2, width_ratios=[20, 1])
            ax = fig.add_subplot(gs[0])
            img = librosa.display.specshow(
                S_db, sr=sr, hop_length=hop_length, x_axis='time', y_axis='hz',
                cmap='jet', ax=ax)
            ax.set_title('Spectrogram', fontsize=12)
            ax.set_xlabel('Time (s)', fontsize=10)
            ax.set_ylabel('Frequency (Hz)', fontsize=10)
            fig.colorbar(img, cax=fig.add_subplot(gs[1]), format='%+2.0f dB')
            fig.tight_layout()
            return _png(fig, dpi=dpi)

        except Exception as e:
            self.logger.error(f"Error generating spectrogram: {e}")
            self.logger.error(traceback.format_exc())
            return None

    def generate_mel_spectrogram(self, y: np.ndarray, sr: int) -> Optional[io.BytesIO]:
        """Mel spectrogram in dB."""
        try:
            librosa = _librosa()
            S = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=128, fmax=8000)
            S_dB = librosa.power_to_db(S, ref=np.max)

            fig = Figure(figsize=(10, 5), facecolor='white')
            ax = fig.add_subplot(111)
            img = librosa.display.specshow(
                S_dB, x_axis='time', y_axis='mel', sr=sr, fmax=8000, ax=ax)
            fig.colorbar(img, ax=ax, format='%+2.0f dB')
            ax.set_title('Mel Spectrogram')
            fig.tight_layout()
            return _png(fig)

        except Exception as e:
            self.logger.error(f"Error generating mel spectrogram: {e}")
            self.logger.error(traceback.format_exc())
            return None

    def generate_chromagram(self, y: np.ndarray, sr: int) -> Optional[io.BytesIO]:
        """Chromagram of the harmonic part (pitch class content)."""
        try:
            librosa = _librosa()
            y_harmonic = librosa.effects.harmonic(y)
            chroma = librosa.feature.chroma_cqt(y=y_harmonic, sr=sr)

            fig = Figure(figsize=(10, 4), facecolor='white')
            ax = fig.add_subplot(111)
            img = librosa.display.specshow(
                chroma, y_axis='chroma', x_axis='time', ax=ax, cmap='coolwarm')
            fig.colorbar(img, ax=ax)
            ax.set_title('Chromagram (Pitch Class Content)')
            fig.tight_layout()
            return _png(fig)

        except Exception as e:
            self.logger.error(f"Error generating chromagram: {e}")
            self.logger.error(traceback.format_exc())
            return None
