"""
Audio Tooltip Application
--------------------------------
Main application entry point that integrates all components.
"""

from utils.logging_utils import setup_logging, get_module_logger
from utils.file_utils import (
    is_audio_file, load_recent_files, save_recent_files,
    add_recent_file, AUDIO_EXTENSIONS, validate_audio_file_path
)
from ui.progress_dialog import ProgressDialog
from ui.settings_dialog import SettingsDialog
from ui.tooltip import EnhancedTooltip
from core.audio_playback import AudioPlayback
from core.audio_analyzer import AudioAnalyzer, TranscriptionCancelled, MAX_VIZ_SECONDS
import os
import sys
import time
import threading
import gc
import logging
import traceback
import argparse
import ctypes

# Close PyInstaller native splash screen as early as possible
try:
    import pyi_splash
    pyi_splash.update_text("Loading components...")
except ImportError:
    pyi_splash = None
try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except Exception:
    # Keyboard module unavailable — disable hotkey features gracefully
    keyboard = None
    KEYBOARD_AVAILABLE = False
import subprocess

# Import PyQt components
from PyQt5.QtGui import QIcon, QPixmap, QFont, QColor, QCursor, QPainter
from PyQt5.QtCore import (Qt, QSettings, QTimer, QThread, pyqtSignal,
                          QT_VERSION_STR, pyqtSlot)
from PyQt5.QtWidgets import (QApplication, QWidget, QSystemTrayIcon, QMenu, QAction,
                             QMessageBox, QFileDialog, QDialog, QVBoxLayout, QLabel, QPushButton, QSplashScreen, QProgressBar)
import signal
from functools import partial

signal.signal(signal.SIGINT, signal.SIG_DFL)  # Allows CTRL+C to terminate


# Windows integration - with graceful fallbacks
try:
    import win32api
    import win32gui
    from win32com.client import Dispatch
    import pythoncom
    WINDOWS_API_AVAILABLE = True
except ImportError:
    WINDOWS_API_AVAILABLE = False

# Window classes of File Explorer windows
EXPLORER_WINDOW_CLASSES = ("CabinetWClass", "ExploreWClass")
GA_ROOT = 2  # GetAncestor flag: top-level window
DROP_WINDOW_HOTKEY = "alt+shift+d"  # Alt+D is the address-bar shortcut in browsers and Explorer

HELP_TEXT = (
    "3 ways to analyze audio:\n\n"
    "1) Select an audio file in File Explorer and press Alt+A\n"
    "2) Select an audio file in File Explorer, then middle-click in that window\n"
    "3) Press Alt+Shift+D to open the drop window and drag files onto it\n\n"
    "Audio Tooltip runs in the system tray (hidden icons): right-click its icon "
    "for recent files and settings."
)


class DropTargetWindow(QWidget):
    """Window that accepts audio file drops for analysis"""

    file_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Audio Tooltip - Drop Files Here")
        self.setAcceptDrops(True)
        self.setMinimumSize(300, 200)

        # Set up UI
        layout = QVBoxLayout(self)

        # Add drop zone label
        drop_label = QLabel("Drop Audio Files Here")
        drop_label.setAlignment(Qt.AlignCenter)
        drop_label.setStyleSheet("""
            font-size: 18px;
            font-weight: bold;
            color: #666;
            padding: 20px;
            border: 3px dashed #aaa;
            border-radius: 10px;
        """)

        # Add instructions
        instructions = QLabel(
            "Drop audio files here for quick analysis\n"
            "Supported formats: MP3, WAV, FLAC, OGG, etc."
        )
        instructions.setAlignment(Qt.AlignCenter)
        instructions.setStyleSheet("color: #666; margin-top: 15px;")

        # Add a button to browse files
        browse_button = QPushButton("Or Browse for Audio Files...")
        browse_button.clicked.connect(self.browse_files)

        # Add widgets to layout
        layout.addWidget(drop_label, 1)
        layout.addWidget(instructions, 0)
        layout.addWidget(browse_button, 0)

    def dragEnterEvent(self, event):
        """Handle drag enter event"""
        if event.mimeData().hasUrls():
            # Check if any URL is a file with audio extension
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                if is_audio_file(file_path) and os.path.exists(file_path):
                    event.acceptProposedAction()
                    return

    def dropEvent(self, event):
        """Handle drop event"""
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if is_audio_file(file_path) and os.path.exists(file_path):
                self.file_dropped.emit(file_path)
                # Process only the first valid audio file
                break

        event.acceptProposedAction()

    def browse_files(self):
        """Open file dialog to browse for audio files"""
        file_filters = f"Audio Files ({' '.join(['*' + ext for ext in AUDIO_EXTENSIONS])})"

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Audio File",
            "",
            file_filters
        )

        if file_path:
            self.file_dropped.emit(file_path)


class TranscriptionWorker(QThread):
    """Worker thread for speech transcription"""

    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    file_saved = pyqtSignal(str)  # New signal for file path

    def __init__(self, analyzer, file_path, channel, language=None, transcription_channel=-1):
        super().__init__()
        self.analyzer = analyzer
        self.file_path = file_path
        self.channel = channel
        self.transcription_channel = transcription_channel
        self.language = language
        self.logger = get_module_logger("TranscriptionWorker")
        self._cancelled = False

    def cancel(self):
        """Ask the running transcription to stop."""
        self._cancelled = True

    def run(self):
        """Transcribe the audio file"""
        self.logger.info(
            f"Starting transcription for {self.file_path}, language: {self.language or 'auto'}, " +
            f"transcription channel: {self.transcription_channel}")

        try:
            transcription = self.analyzer.transcribe_audio(
                self.file_path, self.language, self.transcription_channel,
                should_cancel=lambda: self._cancelled)
        except TranscriptionCancelled:
            self.logger.info("Transcription cancelled")
            return
        except Exception as e:
            self.logger.error(f"Error in transcription: {e}")
            self.logger.error(traceback.format_exc())
            self.error.emit(str(e))
            return

        if self._cancelled:
            return

        base_name = os.path.splitext(os.path.basename(self.file_path))[0]
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        lang_code = self.language or "auto"
        channel_info = f"ch{self.transcription_channel + 1}" if self.transcription_channel >= 0 else "mono"
        file_name = f"{base_name}_{channel_info}_{lang_code}_{timestamp}_transcript.txt"

        # Save next to the audio file; fall back to the app data folder if that
        # folder is read-only.
        output_file = None
        fallback_dir = os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "AudioTooltip", "Transcripts")
        for folder in (os.path.dirname(self.file_path), fallback_dir):
            try:
                os.makedirs(folder, exist_ok=True)
                candidate = os.path.join(folder, file_name)
                with open(candidate, 'w', encoding='utf-8') as f:
                    f.write(transcription)
                output_file = candidate
                break
            except OSError as e:
                self.logger.warning(f"Could not save transcript in {folder}: {e}")

        self.finished.emit(transcription)
        if output_file:
            self.logger.info(f"Transcription saved to: {output_file}")
            self.open_text_file(output_file)
            self.file_saved.emit(output_file)

    def open_text_file(self, file_path):
        """Open text file in default editor"""
        try:
            if os.name == 'nt':  # Windows
                os.startfile(file_path)
            elif os.name == 'posix':  # macOS, Linux
                if os.uname().sysname == 'Darwin':  # macOS
                    subprocess.Popen(['open', file_path])
                else:  # Linux
                    subprocess.Popen(['xdg-open', file_path])

            self.logger.info(f"Opened transcription file: {file_path}")
        except Exception as e:
            self.logger.error(f"Failed to open transcription file: {e}")


class VisualizationWorker(QThread):
    """Worker thread for generating visualizations"""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, analyzer, file_path, viz_type, channel, duration):
        super().__init__()
        self.analyzer = analyzer
        self.file_path = file_path
        self.viz_type = viz_type
        self.channel = channel
        # Never process more than MAX_VIZ_SECONDS, even with "use whole signal"
        self.duration = MAX_VIZ_SECONDS if duration == -1 else min(duration, MAX_VIZ_SECONDS)
        self.logger = get_module_logger("VisualizationWorker")
        self._cancelled = False

    def cancel(self):
        """Discard the result when it arrives."""
        self._cancelled = True

    def run(self):
        """Generate the visualization"""
        self.logger.info(
            f"Generating {self.viz_type} for {self.file_path}, channel {self.channel}")

        try:

            # For Double Waveform, we need a special handling since it requires both channels
            if self.viz_type == "Double Waveform":
                viz_buffer = self.analyzer.generate_double_waveform(
                    self.file_path, self.duration)
                if self._cancelled:
                    return
                if viz_buffer:
                    self.finished.emit((viz_buffer, self.viz_type))
                else:
                    self.error.emit(
                        f"Failed to generate {self.viz_type}. This visualization requires stereo audio (2 channels).")
                return

            # Load audio data
            y, sr, _, _ = self.analyzer.load_audio(
                self.file_path, self.duration, self.channel)
            if y is None:
                self.error.emit(f"Failed to load audio for {self.viz_type}")
                return

            # Generate visualization based on type
            viz_buffer = None
            if self.viz_type == "Waveform":
                viz_buffer = self.analyzer.generate_waveform(y, sr)
            elif self.viz_type == "Spectrogram":
                viz_buffer = self.analyzer.generate_spectrogram(
                    y, sr, high_quality=True)
            elif self.viz_type == "Mel-Spectrogram":
                viz_buffer = self.analyzer.generate_mel_spectrogram(y, sr)
            elif self.viz_type == "Chromagram":
                viz_buffer = self.analyzer.generate_chromagram(y, sr)

            if self._cancelled:
                return
            if viz_buffer:
                self.finished.emit((viz_buffer, self.viz_type))
            else:
                self.error.emit(f"Failed to generate {self.viz_type}")

        except Exception as e:
            self.logger.error(f"Error generating visualization: {e}")
            self.logger.error(traceback.format_exc())
            self.error.emit(f"Error: {str(e)}")


class AudioTooltipWorker(QThread):
    """Worker thread for audio file processing"""

    finished = pyqtSignal(object)
    progress = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, analyzer, file_path, channel=0, force_refresh=False):
        super().__init__()
        self.analyzer = analyzer
        self.file_path = file_path
        self.channel = channel
        self.force_refresh = force_refresh
        self.logger = get_module_logger("AudioTooltipWorker")
        self._cancelled = False

    def cancel(self):
        """Signal the worker to stop at the next checkpoint."""
        self._cancelled = True

    def run(self):
        """Process audio file"""
        self.logger.info(
            f"Starting worker for {self.file_path}, channel {self.channel}, force_refresh: {self.force_refresh}")

        if self._cancelled:
            return

        try:
            # Ensure analyzer is initialized
            if not self.analyzer.initialized:
                self.progress.emit("Initializing analyzer...")
                self.analyzer.initialize()

            if self._cancelled:
                return

            # Process file
            self.progress.emit(
                f"Loading audio data (channel {self.channel+1})...")
            result = self.analyzer.process_audio_file(
                self.file_path, self.channel, force_refresh=self.force_refresh)

            if self._cancelled:
                return

            if result:
                self.logger.info(
                    f"Processing completed successfully for channel {self.channel}")
                self.finished.emit(result)
            else:
                self.logger.error(
                    f"Failed to process audio file (result is None) for channel {self.channel}")
                self.error.emit(
                    f"Failed to process audio file for channel {self.channel+1}")

        except Exception as e:
            self.logger.error(f"Error in worker: {e}")
            self.logger.error(traceback.format_exc())
            self.error.emit(f"Error: {str(e)}")


class AudioTooltipApp(QWidget):
    """Enhanced main application with improved architecture and error handling"""

    # Signals
    showTooltipSignal = pyqtSignal(object)
    showProgressSignal = pyqtSignal(str)
    hideProgressSignal = pyqtSignal()
    file_detected_signal = pyqtSignal(str)
    show_drop_window_signal = pyqtSignal()
    notify_signal = pyqtSignal(str)  # tray balloon text, emitted from any thread

    def __init__(self, startup_mode=False):
        super().__init__()
        self.setWindowTitle("Audio Tooltip")
        self.startup_mode = startup_mode

        # Initialize settings first (needed to check logging preference)
        self.settings = QSettings("AudioTooltip", "EnhancedPreferences")
        self.first_run = not self.settings.contains("start_with_windows")
        self.load_default_settings()

        # Setup logging based on user preference (disabled by default)
        logging_enabled = self._setting_bool("enable_logging", False)
        self.logger = setup_logging(enabled=logging_enabled)
        
        self.module_logger = get_module_logger("AudioTooltipApp")
        if logging_enabled:
            self.module_logger.info(f"Starting application. Qt version: {QT_VERSION_STR}")
            self.module_logger.info("Logging enabled by user preference")

        # Initialize components
        self.tooltip = EnhancedTooltip(settings=self.settings)
        self.audio_analyzer = AudioAnalyzer(self.settings)
        self.audio_playback = AudioPlayback(loader=self.audio_analyzer.load_audio)
        self.workers = []
        self.viz_workers = []
        self.transcription_workers = []
        self._active_worker = None  # worker the progress dialog's Cancel applies to
        self._quick_menu = None

        # Connect components
        self.audio_analyzer.initialize()
        self.tooltip.audio_player = self.audio_playback
        self.tooltip.on_settings_requested = self.show_settings
        self.tooltip.on_channel_changed = self.on_channel_changed
        self.tooltip.on_visualization_requested = self.on_visualization_requested
        self.tooltip.on_transcription_requested = self.on_transcription_requested
        self.tooltip.on_refresh_requested = self.refresh_analysis

        # Initialize recent files
        self.recent_files = load_recent_files(self.settings)

        # Connect signals
        self.showTooltipSignal.connect(self.show_tooltip_slot)
        self.showProgressSignal.connect(self.show_progress_dialog)
        self.hideProgressSignal.connect(self.hide_progress_dialog)
        self.file_detected_signal.connect(self.analyze_file)
        self.show_drop_window_signal.connect(self.show_drop_window_slot)
        self.notify_signal.connect(self.show_tray_message)

        # Initialize detection state before setup_hotkeys so on_hotkey()
        # never races against an uninitialized lock or flag.
        self.detection_active = False
        self._detection_lock = threading.Lock()

        # Setup system tray
        self.setup_tray()
        self.setup_hotkeys()

        # Start tracking thread if available
        self.running = True
        if WINDOWS_API_AVAILABLE or KEYBOARD_AVAILABLE:
            self.tracking_thread = threading.Thread(target=self.track_input)
            self.tracking_thread.daemon = True
            self.tracking_thread.start()
        else:
            self.module_logger.warning(
                "Input tracking unavailable - missing dependencies")

        # Periodic cleanup timer
        self.cleanup_timer = QTimer(self)
        self.cleanup_timer.timeout.connect(self.perform_cleanup)
        self.cleanup_timer.start(60000)  # Run every minute

        # Import librosa in the background so the first analysis is not slowed down
        QTimer.singleShot(3000, lambda: threading.Thread(
            target=self.audio_analyzer.warm_up, daemon=True).start())

        self.module_logger.info("Application initialized")

    def show_tray_message(self, message):
        """Show a tray balloon (main thread only; use notify_signal from other threads)."""
        self.tray_icon.showMessage("Audio Tooltip", message, QSystemTrayIcon.Information, 3000)

    def _emit_hide_progress(self, _result=None):
        """Relay slot: discards worker result and emits hideProgressSignal."""
        self.hideProgressSignal.emit()

    def refresh_analysis(self, file_path, channel):
        """Force a refresh of the audio analysis"""
        self.module_logger.info(
            f"Forcing refresh of {file_path}, channel {channel}")

        # Call analyze_file with force_refresh=True
        self.analyze_file(file_path, channel, force_refresh=True)

    def show_drop_window(self):
        """Trigger showing the drop target window via signal (thread-safe)"""
        self.module_logger.info("Drop window hotkey pressed - emitting signal to show drop window")
        self.show_drop_window_signal.emit()

    def show_drop_window_slot(self):
        """Show the drop target window (runs in main thread)"""
        self.module_logger.info("Showing drop window in main thread")
        try:
            if not hasattr(self, 'drop_window') or self.drop_window is None:
                self.module_logger.info("Creating new drop window")
                self.drop_window = DropTargetWindow()
                self.drop_window.file_dropped.connect(self.analyze_file)

            self.module_logger.info("Showing drop window")
            self.drop_window.show()
            self.module_logger.info(f"Drop window visible: {self.drop_window.isVisible()}")
            self.drop_window.raise_()
            self.module_logger.info("Drop window raised")
            self.drop_window.activateWindow()
            self.module_logger.info(f"Drop window activated - active: {self.drop_window.isActiveWindow()}")
            
            # Try to force it to be visible and on top
            self.drop_window.setWindowState(self.drop_window.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
            self.drop_window.setWindowFlags(self.drop_window.windowFlags() | Qt.WindowStaysOnTopHint)
            self.drop_window.show()  # Show again after setting flags
            self.module_logger.info("Drop window forced to top")
        except Exception as e:
            self.module_logger.error(f"Error showing drop window: {e}")
            self.module_logger.error(traceback.format_exc())

    def setup_hotkeys(self):
        """Setup global hotkeys for the application"""
        try:
            if KEYBOARD_AVAILABLE:
                # Remove all previous hotkeys to avoid duplicates
                try:
                    keyboard.remove_hotkey('alt+a')
                    keyboard.remove_hotkey('alt+q')
                    keyboard.remove_hotkey('ctrl+alt+a')
                except Exception:
                    pass
            else:
                self.module_logger.warning(
                    "Keyboard module not available, hotkeys disabled")
        except Exception as e:
            self.module_logger.error(f"Failed to register hotkeys: {e}")
            self.module_logger.error(traceback.format_exc())

    def prompt_analyze_file(self):
        """Prompt user to select a file for analysis"""
        self.module_logger.info("Analyze file hotkey triggered")

        # Use QTimer to ensure this runs in the main thread
        QTimer.singleShot(0, self.open_file_dialog)

    def load_default_settings(self):
        """Load or create default settings"""

        # Input detection settings
        if not self.settings.contains("auto_close"):
            self.settings.setValue("auto_close", "true")
        if not self.settings.contains("auto_close_time"):
            self.settings.setValue("auto_close_time", "10")

        # Analysis settings
        if not self.settings.contains("preview_duration"):
            self.settings.setValue("preview_duration", "60")
        if not self.settings.contains("use_whole_signal"):
            self.settings.setValue("use_whole_signal", "true")

        # Transcription settings
        if not self.settings.contains("enable_transcription"):
            self.settings.setValue("enable_transcription", "false")
        if not self.settings.contains("azure_key"):
            self.settings.setValue("azure_key", "")
        if not self.settings.contains("azure_region"):
            self.settings.setValue("azure_region", "")

        # Feature settings
        for feature in ['spectral', 'harmonic', 'perceptual', 'mfcc']:
            key = f"feature_{feature}"
            if not self.settings.contains(key):
                self.settings.setValue(key, "true")

        # Autostart is asked on first run (see ask_first_run). Here we only keep an
        # existing registry entry pointing at the current executable with --startup.
        try:
            from utils.startup_utils import StartupManager
            StartupManager().refresh_command()
        except Exception:
            pass

    def ask_first_run(self):
        """First launch: explain usage and ask whether to start with Windows."""
        from utils.startup_utils import StartupManager
        reply = QMessageBox.question(
            None,
            "Welcome to Audio Tooltip",
            HELP_TEXT + "\n\nStart Audio Tooltip automatically when Windows starts?\n"
            "(You can change this later in Settings.)",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        enabled = reply == QMessageBox.Yes
        StartupManager().set_startup_enabled(enabled)
        self.settings.setValue("start_with_windows", enabled)

    def _setting_bool(self, key: str, default: bool = False) -> bool:
        """Read a boolean setting stored as 'true'/'false' string."""
        return self.settings.value(key, "true" if default else "false") == "true"

    def _setting_int(self, key: str, default: int = 0) -> int:
        """Read an integer setting stored as a string."""
        try:
            return int(self.settings.value(key, str(default)))
        except (ValueError, TypeError):
            return default

    def setup_tray(self):
        """Setup system tray icon and menu"""
        self.tray_icon = QSystemTrayIcon(self)

        # Load icon or create placeholder
        icon_path = os.path.join(os.path.dirname(
            os.path.abspath(__file__)), "resources/icons/app_icon.png")
        if os.path.exists(icon_path):
            self.tray_icon.setIcon(QIcon(icon_path))
        else:
            # Create placeholder icon
            icon_pixmap = QPixmap(32, 32)
            icon_pixmap.fill(QColor(65, 105, 225))  # Royal blue
            self.tray_icon.setIcon(QIcon(icon_pixmap))

        # Create tray menu
        tray_menu = QMenu()

        # App title (non-clickable)
        app_title = QAction("Audio Tooltip", self)
        app_title.setEnabled(False)
        app_title.setFont(QFont("Arial", 10, QFont.Bold))

        # Recent files submenu
        self.recent_menu = QMenu("Recent Files")
        self.update_recent_menu()

        # Actions
        analyze_action = QAction("Analyze File...", self)
        analyze_action.triggered.connect(self.open_file_dialog)

        # Dedicated action for analyzing selected file in Explorer
        analyze_selected_action = QAction(
            "Analyze Selected File in Explorer (Alt+A)", self)
        analyze_selected_action.triggered.connect(self.trigger_detection)
        analyze_selected_action.setToolTip(
            "Try to analyze the currently selected file in Explorer")

        # Add help/instructions action
        help_action = QAction("Show Instructions", self)
        help_action.triggered.connect(self.show_help_notification)

        settings_action = QAction("Settings...", self)
        settings_action.triggered.connect(self.show_settings)

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close_app)

        # Add actions to menu
        tray_menu.addAction(app_title)
        tray_menu.addSeparator()
        tray_menu.addAction(analyze_action)
        tray_menu.addAction(analyze_selected_action)  # Add the new action
        tray_menu.addMenu(self.recent_menu)
        tray_menu.addSeparator()
        tray_menu.addAction(help_action)
        tray_menu.addAction(settings_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)

        # Add "Drop Target" action
        drop_target_action = QAction("Open Drop Target Window (Alt+Shift+D)", self)
        drop_target_action.triggered.connect(self.show_drop_window)
        tray_menu.insertAction(help_action, drop_target_action)

        # Hotkey for the drop window (only if keyboard module is available)
        if KEYBOARD_AVAILABLE:
            try:
                keyboard.add_hotkey(DROP_WINDOW_HOTKEY, self.show_drop_window, suppress=False)
            except Exception as e:
                self.module_logger.warning(f"Failed to register {DROP_WINDOW_HOTKEY} hotkey: {e}")

        # Set menu and show icon
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.setToolTip("Audio Tooltip")
        self.tray_icon.show()

        # Connect activation signal
        self.tray_icon.activated.connect(self.tray_icon_clicked)

        self.module_logger.info("System tray initialized")

    def show_ready_message(self):
        """Single, short balloon after a manual launch."""
        self.tray_icon.showMessage(
            "Audio Tooltip is running",
            "Select an audio file in File Explorer and press Alt+A. "
            "Right-click this icon for more.",
            QSystemTrayIcon.Information,
            5000
        )

    def show_help_notification(self):
        """Show the help/instructions dialog"""
        QMessageBox.information(None, "Audio Tooltip - How to Use", HELP_TEXT)

    def update_recent_menu(self):
        """Update the recent files menu"""
        self.recent_menu.clear()

        for file_path in self.recent_files:
            if os.path.exists(file_path):
                action = QAction(os.path.basename(file_path), self)
                action.setData(file_path)
                action.triggered.connect(self.open_recent_file)
                self.recent_menu.addAction(action)

        if not self.recent_files:
            empty_action = QAction("No recent files", self)
            empty_action.setEnabled(False)
            self.recent_menu.addAction(empty_action)

    def tray_icon_clicked(self, reason):
        """Handle tray icon activation"""
        if reason == QSystemTrayIcon.DoubleClick:
            # Launch file dialog on double-click
            self.open_file_dialog()
        elif reason == QSystemTrayIcon.Trigger:
            # Show a custom quick menu on single click. Keep a reference, otherwise
            # Python garbage-collects the menu and it closes immediately.
            menu = QMenu()
            self._quick_menu = menu

            analyze_action = QAction("Analyze Audio File...", menu)
            analyze_action.setFont(QFont("Arial", 10, QFont.Bold))
            analyze_action.triggered.connect(self.open_file_dialog)

            menu.addAction(analyze_action)

            # Add recent files directly to this menu
            if self.recent_files:
                menu.addSeparator()
                menu.addAction("Recent Files:").setEnabled(False)

                # Show top 5
                for i, file_path in enumerate(self.recent_files[:5]):
                    if os.path.exists(file_path):
                        action = QAction(os.path.basename(file_path), menu)
                        action.setData(file_path)
                        action.triggered.connect(self.open_recent_file)
                        menu.addAction(action)

            menu.addSeparator()
            settings_action = QAction("Settings...", menu)
            settings_action.triggered.connect(self.show_settings)
            menu.addAction(settings_action)

            # Position and show the menu
            menu.popup(QCursor.pos())
        elif reason == QSystemTrayIcon.MiddleClick:
            # Direct access to open file on middle click
            self.open_file_dialog()

    def open_file_dialog(self):
        """Open file dialog to select audio file"""
        self.module_logger.info("Opening file selection dialog")

        # Create a list of file filters
        filter_list = []

        # Add specific formats first
        common_formats = ['.mp3', '.wav', '.flac', '.m4a', '.ogg']
        for ext in common_formats:
            if ext in AUDIO_EXTENSIONS:
                filter_name = ext[1:].upper()  # Remove dot and capitalize
                filter_list.append(f"{filter_name} Files (*{ext})")

        # Add comprehensive filter
        all_exts = " ".join(['*' + ext for ext in AUDIO_EXTENSIONS])
        filter_list.append(f"All Audio Files ({all_exts})")

        # Add All Files filter
        filter_list.append("All Files (*.*)")

        # Join all filters
        file_filters = ";;".join(filter_list)

        # Determine starting directory
        start_dir = ""
        if self.recent_files and os.path.exists(os.path.dirname(self.recent_files[0])):
            start_dir = os.path.dirname(self.recent_files[0])

        # Open dialog
        try:
            file_path, _ = QFileDialog.getOpenFileName(
                None,  # Use None instead of self to ensure dialog is properly modal
                "Select Audio File",
                start_dir,
                file_filters
            )

            if file_path:
                self.module_logger.info(f"File selected: {file_path}")
                self.analyze_file(file_path)
            else:
                self.module_logger.info("File selection canceled")
        except Exception as e:
            self.module_logger.error(f"Error in file dialog: {e}")
            self.module_logger.error(traceback.format_exc())
            QMessageBox.warning(
                None,
                "Error",
                f"Error opening file dialog: {str(e)}"
            )

    def open_recent_file(self):
        """Open a file from the recent files menu"""
        action = self.sender()
        if action and action.data():
            file_path = action.data()
            if os.path.exists(file_path):
                self.analyze_file(file_path)
            else:
                # Remove non-existent file
                self.module_logger.info(
                    f"Removing non-existent file from recents: {file_path}")
                if file_path in self.recent_files:
                    self.recent_files.remove(file_path)
                save_recent_files(self.settings, self.recent_files)
                self.update_recent_menu()
                # Show error message
                QMessageBox.warning(
                    None,
                    "File Not Found",
                    f"The file no longer exists:\n{file_path}"
                )

    def show_settings(self,  tab=None):
        """Show settings dialog"""
        dialog = SettingsDialog(self, self.settings)

        # If a specific tab was requested, switch to it
        if tab == "transcription":
            dialog.tab_widget.setCurrentIndex(2)  # Index of transcription tab

        if dialog.exec_() == QDialog.Accepted:
            # Apply new settings
            self.module_logger.info("Settings updated")

            # Update components with new settings
            self.audio_analyzer.settings = self.settings

            # Reinitialize components if needed
            if self._setting_bool("enable_transcription", False):
                self.audio_analyzer.initialize_speech_services()

    def close_app(self):
        """Clean up and close the application"""
        self.module_logger.info("Closing application")
        self.running = False

        # Wait for tracking thread to exit
        if hasattr(self, 'tracking_thread') and self.tracking_thread.is_alive():
            self.tracking_thread.join(timeout=1.0)

        # Stop work in progress so no worker emits into a closing UI
        for worker in self.workers + self.viz_workers + self.transcription_workers:
            if hasattr(worker, 'cancel'):
                worker.cancel()

        # Hide tooltip, stop playback and delete all preview files
        self.tooltip.hide()
        self.audio_playback.stop_playback()
        self.audio_playback.cleanup()

        # Quit application
        QApplication.quit()

    def perform_cleanup(self):
        """Periodic cleanup to prevent memory leaks"""
        self.module_logger.debug("Performing periodic cleanup")

        # Delete preview clips that are no longer playing (never the current one)
        self.audio_playback.cleanup(min_age_seconds=600)

        # Forget finished workers
        self.workers = [w for w in self.workers if w.isRunning()]
        self.viz_workers = [w for w in self.viz_workers if w.isRunning()]
        self.transcription_workers = [w for w in self.transcription_workers if w.isRunning()]

        gc.collect()

        # Force garbage collection
        collected = gc.collect()
        self.module_logger.debug(
            f"Garbage collection: {collected} objects collected")

    def show_progress_dialog(self, message):
        """Show progress dialog in main thread"""
        if not hasattr(self, 'progress_dialog') or self.progress_dialog is None:
            self.progress_dialog = ProgressDialog(
                None, "Analyzing Audio", message, cancelable=True)
            self.progress_dialog.setWindowModality(Qt.NonModal)
            self.progress_dialog.rejected.connect(self._cancel_active_worker)
        else:
            self.progress_dialog.update_message(message)

        self.progress_dialog.show()
        self.progress_dialog.raise_()

    def _cancel_active_worker(self):
        """Cancel the worker the progress dialog currently stands for."""
        worker = self._active_worker
        if worker is not None and hasattr(worker, 'cancel'):
            worker.cancel()
        self._active_worker = None
        self.progress_dialog = None
        self.tooltip.hide_loading()

    def hide_progress_dialog(self):
        """Hide progress dialog"""
        self._active_worker = None
        if hasattr(self, 'progress_dialog') and self.progress_dialog is not None:
            dialog, self.progress_dialog = self.progress_dialog, None
            dialog.accept()

    @pyqtSlot(str)
    def analyze_file(self, file_path, channel=0, force_refresh=False):
        """Process audio file with worker thread"""
        self.module_logger.info(
            f"Analyzing file: {file_path}, channel: {channel}, force_refresh: {force_refresh}")

        try:
            # Validate file path
            is_valid, error_message = validate_audio_file_path(
                file_path, self.module_logger)
            if not is_valid:
                self.module_logger.error(
                    f"Invalid audio file: {error_message}")
                QMessageBox.warning(
                    None,
                    "Invalid Audio File",
                    f"Cannot analyze this file:\n{error_message}"
                )
                return

            # A newer request supersedes any analysis still running
            for old_worker in self.workers:
                old_worker.cancel()
            self.workers = [w for w in self.workers if w.isRunning()]

            # Create worker for async processing with force_refresh parameter
            try:
                worker = AudioTooltipWorker(
                    self.audio_analyzer, file_path, channel, force_refresh)

                # Connect worker signals
                try:
                    worker.finished.connect(
                        partial(self.handle_analysis_result, file_path=file_path, channel=channel))
                    worker.progress.connect(self.showProgressSignal.emit)
                    worker.error.connect(self.handle_worker_error)
                    worker.finished.connect(
                        partial(self._cleanup_worker_on_finish, worker))  # Clean up when done
                except Exception as connect_e:
                    self.module_logger.error(
                        f"Error connecting worker signals: {connect_e}")
                    raise

                # Store worker reference
                self.workers.append(worker)
                self._active_worker = worker

                # Show progress dialog
                try:
                    self.showProgressSignal.emit(
                        f"Analyzing {os.path.basename(file_path)} (channel {channel+1})...")
                except Exception as signal_e:
                    self.module_logger.error(
                        f"Error emitting progress signal: {signal_e}")

                # Start worker
                try:
                    worker.start()
                    self.module_logger.info(
                        f"Worker started successfully for {file_path}")
                except Exception as start_e:
                    self.module_logger.error(
                        f"Error starting worker: {start_e}")
                    raise

            except Exception as worker_e:
                self.module_logger.error(
                    f"Error creating or setting up worker: {worker_e}")
                self.module_logger.error(traceback.format_exc())
                # Fall back to synchronous processing if worker fails
                self.process_file_sync(file_path, channel, force_refresh)

        except Exception as e:
            self.module_logger.error(
                f"Unhandled exception in analyze_file: {e}")
            self.module_logger.error(traceback.format_exc())
            # Show error to user
            try:
                QMessageBox.critical(
                    None,
                    "Critical Error",
                    "An unexpected error occurred. See application logs for details."
                )
            except Exception:
                pass  # If even showing the error fails, just continue

    def process_file_sync(self, file_path, channel=0, force_refresh=False):
        """Fallback synchronous file processing when worker threads fail"""
        self.module_logger.info(
            f"Using synchronous processing for {file_path}")
        try:
            # Process directly without worker
            result = self.audio_analyzer.process_audio_file(
                file_path, channel, force_refresh=force_refresh)
            if result:
                self.handle_analysis_result(result, file_path, channel)
            else:
                self.handle_worker_error(
                    f"Failed to process {os.path.basename(file_path)}")
        except Exception as e:
            self.module_logger.error(f"Error in synchronous processing: {e}")
            self.module_logger.error(traceback.format_exc())
            self.handle_worker_error(f"Error: {str(e)}")

    def cleanup_worker(self, worker):
        """Remove worker from list when finished"""
        if hasattr(self, "workers") and worker in self.workers:
            self.workers.remove(worker)

    def _cleanup_worker_on_finish(self, worker, result):
        """Slot for worker finished signal that delegates to cleanup_worker, ignoring result."""
        self.cleanup_worker(worker)

    def _cleanup_list_worker(self, worker_list, worker):
        """Remove a finished worker from its tracking list."""
        if worker in worker_list:
            worker_list.remove(worker)

    def handle_analysis_result(self, result, file_path, channel):
        """Handle successful audio analysis"""
        self.module_logger.info(
            f"Analysis complete for: {file_path}, channel {channel}")
        self.hideProgressSignal.emit()
        self.tooltip.hide_loading()

        if result:
            # Add to recent files
            self.recent_files = add_recent_file(
                self.settings, file_path, self.recent_files)
            self.update_recent_menu()

            # Unpack the result tuple with the correct number of values
            # Format: (file_path, metadata, viz_buffer, transcription, num_channels, channel, time_delay)
            if len(result) >= 7:
                file_path, metadata, viz_buffer, transcription, num_channels, channel, time_delay = result
            else:
                # Handle older format for backward compatibility
                file_path, metadata, viz_buffer, transcription, num_channels = result
                time_delay = None

            # Show tooltip with results
            final_result = (file_path, metadata, viz_buffer,
                            transcription, num_channels, channel)
            if len(result) >= 7:
                # Include time_delay in final result if available
                final_result = final_result + (time_delay,)

            self.showTooltipSignal.emit(final_result)

            # Connect channel change handler
            self.tooltip.on_channel_changed = self.on_channel_changed
        else:
            self.handle_worker_error(
                f"Failed to analyze {os.path.basename(file_path)}, channel {channel+1}")

    def on_channel_changed(self, channel):
        """Handle channel selection change in tooltip"""
        self.module_logger.info(f"Channel changed to {channel+1}")
        self.tooltip.show_loading()
        if self.tooltip.current_file:
            self.analyze_file(self.tooltip.current_file, channel)

    def on_visualization_requested(self, viz_type, channel):
        """Handle visualization run request"""
        self.module_logger.info(
            f"Visualization requested: {viz_type} for channel {channel+1}")

        # Check if a file is loaded
        if not self.tooltip.current_file:
            return

        # Get preview duration
        use_whole_signal = self._setting_bool("use_whole_signal", False)
        preview_duration = -1 if use_whole_signal else self._setting_int("preview_duration", 10)

        # Run in a worker thread
        worker = VisualizationWorker(
            self.audio_analyzer, self.tooltip.current_file, viz_type, channel, preview_duration)
        worker.finished.connect(self.update_visualization)
        worker.error.connect(self.handle_worker_error)
        worker.finished.connect(self._emit_hide_progress)
        worker.finished.connect(lambda _, w=worker: self._cleanup_list_worker(self.viz_workers, w))

        # Store worker reference
        self.viz_workers.append(worker)
        self._active_worker = worker

        # Show progress dialog
        self.showProgressSignal.emit(f"Generating {viz_type}...")

        # Start worker
        worker.start()

    def update_visualization(self, result):
        """Update visualization in tooltip"""
        if not result:
            return

        viz_buffer, viz_type = result

        # Update tooltip visualization
        if viz_buffer:
            pixmap = QPixmap()
            pixmap.loadFromData(viz_buffer.getvalue())
            self.tooltip.set_visualization(pixmap)
            self.tooltip.viz_combo_menu.setText(viz_type)
            self.tooltip._change_visualization(viz_type)  # Update description
            self.tooltip._viz_generated = True  # Mark visualization as explicitly generated

    def handle_worker_error(self, error_message):
        """Handle worker thread errors"""
        self.module_logger.error(f"Worker error: {error_message}")
        self.hideProgressSignal.emit()
        self.tooltip.hide_loading()

        # Show error message
        # Messages already say what failed (analysis, visualization or transcription)
        QMessageBox.warning(None, "Audio Tooltip", error_message)

    def show_tooltip_slot(self, result):
        """Show tooltip with analysis results"""
        if not result:
            self.module_logger.warning("Empty result in show_tooltip_slot")
            return

        try:
            # Unpack result with format handling
            if len(result) >= 7:  # New format with time_delay
                file_path, metadata, viz_buffer, transcription, num_channels, channel, time_delay = result
            elif len(result) == 6:  # Format with channel but no time_delay
                file_path, metadata, viz_buffer, transcription, num_channels, channel = result
                time_delay = None
            else:  # Oldest format
                file_path, metadata, viz_buffer, transcription, num_channels = result
                channel, time_delay = 0, None

            # Size and place the tooltip on the screen where the mouse is,
            # unless it is already open (keep the user's position). Done before
            # filling it so images are scaled to the final size.
            if not self.tooltip.isVisible():
                screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
                screen_rect = screen.availableGeometry()
                self.tooltip.fit_to_screen(screen_rect)
                x = screen_rect.x() + screen_rect.width() - self.tooltip.width() - 20
                y = screen_rect.y() + 20
                self.tooltip.move(max(screen_rect.x(), x), max(screen_rect.y(), y))

            # Update tooltip content with time_delay if available
            if time_delay is not None:
                self.tooltip.update_content(
                    file_path,
                    metadata,
                    viz_buffer,
                    transcription,
                    num_channels,
                    channel,
                    time_delay
                )
            else:
                self.tooltip.update_content(
                    file_path,
                    metadata,
                    viz_buffer,
                    transcription,
                    num_channels,
                    channel
                )


            # Show with animation
            self.tooltip.show_with_fade()

            # Reset auto-hide timer
            self.tooltip.reset_auto_hide_timer()

        except Exception as e:
            self.module_logger.error(f"Error in show_tooltip_slot: {e}")
            self.module_logger.error(traceback.format_exc())

    def on_transcription_requested(self, file_path, channel, language=None, transcription_channel=-1):
        """Handle transcription request from tooltip"""
        self.module_logger.info(
            f"Transcription requested for {file_path}, UI channel {channel}, " +
            f"transcription channel {transcription_channel}, language: {language or 'auto'}")

        # Run in a worker thread
        worker = TranscriptionWorker(
            self.audio_analyzer, file_path, channel, language, transcription_channel)
        worker.finished.connect(self.update_transcription)
        worker.error.connect(self.handle_worker_error)
        worker.finished.connect(self._emit_hide_progress)
        worker.file_saved.connect(
            self.show_file_saved_notification)
        worker.file_saved.connect(self.set_transcript_file_path)
        worker.finished.connect(lambda _, w=worker: self._cleanup_list_worker(self.transcription_workers, w))

        # Store worker reference
        self.transcription_workers.append(worker)
        self._active_worker = worker

        # Show progress dialog
        self.showProgressSignal.emit("Transcribing audio...")

        # Start worker
        worker.start()

    def show_file_saved_notification(self, file_path):
        """Show notification that transcription file was saved"""
        self.tray_icon.showMessage(
            "Transcription Saved",
            f"Transcription saved and opened in text editor:\n{os.path.basename(file_path)}",
            QSystemTrayIcon.Information,
            5000
        )

    def update_transcription(self, transcription):
        """Update transcription in tooltip"""
        if not transcription:
            return

        # Update tooltip transcription
        self.tooltip.transcript_text.setText(transcription)

        # Enable the View Transcript button
        self.tooltip.view_transcript_button.setEnabled(True)

    def set_transcript_file_path(self, file_path):
        """Set the path to the saved transcript file"""
        self.tooltip.transcript_file_path = file_path
        self.tooltip.view_transcript_button.setEnabled(True)

    def _start_detection(self, source):
        """Run Explorer selection detection in a background thread (one at a time)."""
        with self._detection_lock:
            if self.detection_active:
                return
            self.detection_active = True
        try:
            threading.Thread(target=self.check_file_under_cursor,
                             args=(source,), daemon=True).start()
        except Exception as e:
            self.module_logger.error(f"Error starting detection thread: {e}")
            with self._detection_lock:
                self.detection_active = False

    @staticmethod
    def _window_class(hwnd):
        try:
            return win32gui.GetClassName(hwnd)
        except Exception:
            return ""

    def _selected_audio_file(self, shell_window):
        """First selected audio file of an Explorer window, or None."""
        try:
            selected = shell_window.Document.SelectedItems()
            for j in range(selected.Count):
                path = selected.Item(j).Path
                if is_audio_file(path) and os.path.isfile(path):
                    return path
        except Exception as e:
            self.module_logger.debug(f"Cannot read Explorer selection: {e}")
        return None

    def check_file_under_cursor(self, source="hotkey"):
        """Find the audio file selected in File Explorer and analyze it.

        source:
            "middle": middle click. Only acts when the click is inside the
                      foreground Explorer window, and stays silent otherwise.
            "hotkey": Alt+A. Only when File Explorer is the foreground
                      window; shows a tray message if no audio file is selected.
            "menu":   tray menu. Explorer windows from top to bottom; shows a
                      tray message when nothing is selected.
        """
        if not WINDOWS_API_AVAILABLE:
            self.module_logger.error("Cannot detect files: Windows API unavailable")
            with self._detection_lock:
                self.detection_active = False
            return False

        com_initialized = False
        try:
            pythoncom.CoInitialize()
            com_initialized = True

            foreground = win32gui.GetForegroundWindow()
            foreground_is_explorer = self._window_class(foreground) in EXPLORER_WINDOW_CLASSES

            # Alt+A also reaches other apps: only react when Explorer is in front
            if source == "hotkey" and not foreground_is_explorer:
                return False

            if source == "middle":
                if not foreground_is_explorer:
                    return False
                under_cursor = win32gui.WindowFromPoint(win32api.GetCursorPos())
                if ctypes.windll.user32.GetAncestor(under_cursor, GA_ROOT) != foreground:
                    return False

            # Shell windows grouped by top-level window (Windows 11: one entry per tab)
            shell_windows = Dispatch("Shell.Application").Windows()
            by_hwnd = {}
            for i in range(shell_windows.Count):
                try:
                    window = shell_windows.Item(i)
                    if window is not None:
                        by_hwnd.setdefault(int(window.HWND), []).append(window)
                except Exception:
                    pass

            candidates = [foreground] if foreground_is_explorer else []
            if source == "menu":
                z_order = []

                def collect(hwnd, acc):
                    if self._window_class(hwnd) in EXPLORER_WINDOW_CLASSES and hwnd != foreground:
                        acc.append(hwnd)
                    return True

                win32gui.EnumWindows(collect, z_order)
                candidates += z_order

            for hwnd in candidates:
                for window in by_hwnd.get(hwnd, []):
                    file_path = self._selected_audio_file(window)
                    if file_path:
                        self.module_logger.info(f"Audio file detected ({source}): {file_path}")
                        self.file_detected_signal.emit(file_path)
                        return True

            if source != "middle":
                self.notify_signal.emit(
                    "No audio file selected. Select an audio file in File Explorer, then press Alt+A.")
            return False

        except Exception as e:
            self.module_logger.error(f"Error in audio file detection: {e}")
            self.module_logger.error(traceback.format_exc())
            return False
        finally:
            with self._detection_lock:
                self.detection_active = False
            if com_initialized:
                pythoncom.CoUninitialize()

    def track_input(self):
        # Require at least one input facility: Windows API (mouse) or keyboard hooks
        if not WINDOWS_API_AVAILABLE and not KEYBOARD_AVAILABLE:
            self.module_logger.error("Cannot track input: missing dependencies")
            return

        self.module_logger.info("Input tracking thread started")

        if KEYBOARD_AVAILABLE:
            try:
                try:
                    keyboard.remove_hotkey('alt+a')
                except Exception:
                    pass
                keyboard.add_hotkey(
                    'alt+a', lambda: self._start_detection("hotkey"), suppress=False)
                self.module_logger.info("Hotkey registered successfully")
            except Exception as reg_e:
                self.module_logger.error(f"Failed to register hotkey: {reg_e}")

        # Poll the middle mouse button; react only to clicks while File Explorer
        # is the foreground window (browsers use middle click for new tabs).
        middle_button_prev = False
        while self.running:
            try:
                if WINDOWS_API_AVAILABLE:
                    mouse_down = (win32api.GetAsyncKeyState(0x04) & 0x8000) != 0  # VK_MBUTTON
                    if (mouse_down and not middle_button_prev and
                            self._window_class(win32gui.GetForegroundWindow()) in EXPLORER_WINDOW_CLASSES):
                        self._start_detection("middle")
                    middle_button_prev = mouse_down
            except Exception as e:
                self.module_logger.debug(f"Mouse polling error: {e}")
            time.sleep(0.05)

        self.module_logger.info("Input tracking thread terminated")

    def trigger_detection(self):
        """Trigger audio file detection from tray menu."""
        self.module_logger.info("Tray menu detection triggered")
        self._start_detection("menu")


def acquire_single_instance():
    """Return a mutex handle if this is the only running instance, else None."""
    try:
        import win32event
        import winerror
        handle = win32event.CreateMutex(None, False, "AudioTooltip_SingleInstance")
        if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
            return None
        return handle
    except Exception:
        return True  # Cannot check: let the app start


def main(app=None, splash=None, args=None):
    """Main application entry point"""

    # --startup is passed by the Windows autostart entry: no splash, no messages
    startup_mode = bool(args and (args.startup or args.minimized))

    try:
        # If app wasn't provided, create it (for backward compatibility)
        if app is None:
            app = QApplication(sys.argv)
            app.setQuitOnLastWindowClosed(False)
            app.setApplicationName("Audio Tooltip")
            app.setOrganizationName("MCDE - FHL 2025")

        if splash:
            splash.showMessage("Starting...",
                               Qt.AlignBottom | Qt.AlignCenter, QColor(255, 255, 255))
            app.processEvents()

        tooltip_app = AudioTooltipApp(startup_mode=startup_mode)

        if splash:
            splash.finish(None)

        if tooltip_app.first_run:
            QTimer.singleShot(0, tooltip_app.ask_first_run)
        elif not startup_mode:
            tooltip_app.show_ready_message()

        # Start the event loop
        return app.exec_()
    except Exception as e:
        logging.getLogger("AudioTooltipApp").critical(f"Error starting application: {e}", exc_info=True)
        if splash:
            splash.finish(None)
        return 1


if __name__ == '__main__':
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='AudioTooltip - Audio Analysis Tool')
    parser.add_argument('--startup', action='store_true',
                        help='Start silently in the system tray (used by Windows startup)')
    parser.add_argument('--minimized', action='store_true',
                        help='Start silently in the system tray')
    args = parser.parse_args()
    startup_mode = args.startup or args.minimized

    # High-DPI: scale the UI with the Windows display scaling (must precede QApplication)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    # Create application first
    app = QApplication(sys.argv)

    app.setQuitOnLastWindowClosed(False)  # Keep running when windows close
    app.setApplicationName("Audio Tooltip")
    app.setOrganizationName("MCDE - FHL 2025")

    instance_lock = acquire_single_instance()
    if instance_lock is None:
        if pyi_splash is not None:
            pyi_splash.close()
        if not startup_mode:
            QMessageBox.information(
                None, "Audio Tooltip",
                "Audio Tooltip is already running.\n\n"
                "Look for its icon in the system tray (hidden icons).")
        sys.exit(0)

    splash = None
    if not startup_mode:
        splash_pixmap = QPixmap(500, 300)
        splash_pixmap.fill(QColor(50, 50, 80))  # Dark blue background

        # Draw content on the pixmap
        painter = QPainter(splash_pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        # Title
        title_font = QFont("Arial", 24, QFont.Bold)
        painter.setFont(title_font)
        painter.setPen(QColor(255, 255, 255))  # White text
        painter.drawText(20, 50, "Audio Tooltip")

        # Version
        version_font = QFont("Arial", 12)
        painter.setFont(version_font)
        painter.setPen(QColor(200, 200, 200))  # Light gray
        painter.drawText(20, 80, "v3.0.5 - Audio Analysis Tool")

        # Loading message
        loading_font = QFont("Arial", 14)
        painter.setFont(loading_font)
        painter.setPen(QColor(100, 150, 255))  # Light blue
        painter.drawText(20, 220, "Loading components...")

        # Progress bar visual
        painter.setPen(QColor(100, 150, 255))
        painter.drawRect(20, 240, 460, 20)
        painter.fillRect(22, 242, 456, 16, QColor(100, 150, 255))

        painter.end()

        splash = QSplashScreen(splash_pixmap)
        splash.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.SplashScreen)
        splash.show()
        app.processEvents()

    # Close the PyInstaller native splash now that the Qt splash is visible
    if pyi_splash is not None:
        pyi_splash.close()

    sys.exit(main(app, splash, args))
