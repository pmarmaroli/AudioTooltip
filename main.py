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
from core.audio_analyzer import AudioAnalyzer
import os
import sys
import winreg
import time
import threading
import gc
import traceback
import keyboard

# Import PyQt components
from PyQt5.QtGui import QIcon, QPixmap, QFont, QColor, QCursor, QPainter
from PyQt5.QtCore import (Qt, QSettings, QTimer, QThread, pyqtSignal, QMetaObject,
                          Q_ARG, QPoint, QSize, QT_VERSION_STR, pyqtSlot, QRect)
from PyQt5.QtWidgets import (QApplication, QWidget, QSystemTrayIcon, QMenu, QAction,
                             QMessageBox, QFileDialog, QDialog, QVBoxLayout, QLabel, QPushButton, QSplashScreen, QProgressBar)
import signal

signal.signal(signal.SIGINT, signal.SIG_DFL)  # Allows CTRL+C to terminate


# Windows integration - with graceful fallbacks
try:
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False

try:
    import win32api
    import win32con
    import win32gui
    from win32com.client import Dispatch
    import pythoncom
    WINDOWS_API_AVAILABLE = True
except ImportError:
    WINDOWS_API_AVAILABLE = False


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

    def run(self):
        """Transcribe the audio file"""
        self.logger.info(
            f"Starting transcription for {self.file_path}, language: {self.language or 'auto'}, " +
            f"transcription channel: {self.transcription_channel}")

        try:
            # Transcribe with specified language and channel
            transcription = self.analyzer.transcribe_audio(
                self.file_path, self.language, self.transcription_channel)

            if transcription:
                # Create a text file for the transcription
                base_name = os.path.splitext(
                    os.path.basename(self.file_path))[0]
                output_dir = os.path.dirname(self.file_path)
                timestamp = time.strftime("%Y%m%d_%H%M%S")

                # Include language and channel info in filename
                lang_code = self.language or "auto"
                channel_info = f"ch{self.transcription_channel}" if self.transcription_channel >= 0 else "mono"

                output_file = os.path.join(
                    output_dir, f"{base_name}_{channel_info}_{lang_code}_{timestamp}_transcript.txt")

                # Save transcription to file
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(transcription)

                self.logger.info(f"Transcription saved to: {output_file}")

                # Open the file in the default text editor
                self.open_text_file(output_file)

                # Emit signals
                self.finished.emit(transcription)
                self.file_saved.emit(output_file)
            else:
                self.error.emit("No speech detected or transcription failed")

        except Exception as e:
            self.logger.error(f"Error in transcription: {e}")
            self.logger.error(traceback.format_exc())
            self.error.emit(f"Error: {str(e)}")

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
        self.duration = duration
        self.logger = get_module_logger("VisualizationWorker")

    def run(self):
        """Generate the visualization"""
        self.logger.info(
            f"Generating {self.viz_type} for {self.file_path}, channel {self.channel}")

        try:

            # For Double Waveform, we need a special handling since it requires both channels
            if self.viz_type == "Double Waveform":
                viz_buffer = self.analyzer.generate_double_waveform(
                    self.file_path)
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

    def run(self):
        """Process audio file"""
        self.logger.info(
            f"Starting worker for {self.file_path}, channel {self.channel}, force_refresh: {self.force_refresh}")

        try:
            # Ensure analyzer is initialized
            if not self.analyzer.initialized:
                self.progress.emit("Initializing analyzer...")
                self.analyzer.initialize()

            # Process file
            self.progress.emit(
                f"Loading audio data (channel {self.channel+1})...")
            result = self.analyzer.process_audio_file(
                self.file_path, self.channel, force_refresh=self.force_refresh)

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


def on_channel_changed(self, channel):
    """Handle channel selection change in tooltip"""
    # Guard against None value
    if channel is None:
        self.module_logger.warning(
            "Received None for channel change, defaulting to channel 0")
        channel = 0

    self.module_logger.info(f"Channel changed to {channel+1}")

    # Re-analyze the file with new channel
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
    use_whole_signal = self.settings.value(
        "use_whole_signal", "false") == "true"
    preview_duration = - \
        1 if use_whole_signal else int(
            self.settings.value("preview_duration", "60"))

    # Show progress dialog
    self.showProgressSignal.emit(f"Generating {viz_type}...")

    # Run in a worker thread
    worker = VisualizationWorker(
        self.audio_analyzer, self.tooltip.current_file, viz_type, channel, preview_duration)
    worker.finished.connect(self.update_visualization)
    worker.error.connect(self.handle_worker_error)
    worker.finished.connect(lambda: self.hideProgressSignal.emit())

    # Store worker reference
    if not hasattr(self, "viz_workers"):
        self.viz_workers = []
    self.viz_workers.append(worker)

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
        self.tooltip.viz_display.setPixmap(pixmap.scaled(
            self.tooltip.viz_display.width(),
            self.tooltip.viz_display.height(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        ))
        self.tooltip.viz_combo_menu.setText(viz_type)
        self.tooltip._change_visualization(viz_type)


class AudioTooltipApp(QWidget):
    """Enhanced main application with improved architecture and error handling"""

    # Signals
    showTooltipSignal = pyqtSignal(object)
    showProgressSignal = pyqtSignal(str)
    hideProgressSignal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Audio Tooltip")

        # Setup logging
        self.logger = setup_logging()
        self.module_logger = get_module_logger("AudioTooltipApp")
        self.module_logger.info(
            f"Starting application. Qt version: {QT_VERSION_STR}")

        # Initialize settings
        self.settings = QSettings("AudioTooltip", "EnhancedPreferences")
        self.load_default_settings()

        # Initialize components
        self.tooltip = EnhancedTooltip(settings=self.settings)
        self.audio_analyzer = AudioAnalyzer(self.settings)
        self.audio_playback = AudioPlayback()

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

        # Setup system tray
        self.setup_tray()
        self.setup_hotkeys()

        # Start tracking thread if available
        self.running = True
        self.detection_active = False
        if WINDOWS_API_AVAILABLE and KEYBOARD_AVAILABLE:
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

        self.module_logger.info("Application initialized")

    def refresh_analysis(self, file_path, channel):
        """Force a refresh of the audio analysis"""
        self.module_logger.info(
            f"Forcing refresh of {file_path}, channel {channel}")

        # Call analyze_file with force_refresh=True
        self.analyze_file(file_path, channel, force_refresh=True)

    def show_drop_window(self):
        """Show the drop target window"""
        if not hasattr(self, 'drop_window') or self.drop_window is None:
            self.drop_window = DropTargetWindow()
            self.drop_window.file_dropped.connect(self.analyze_file)

        self.drop_window.show()
        self.drop_window.raise_()
        self.drop_window.activateWindow()

    def setup_hotkeys(self):
        """Setup global hotkeys for the application"""
        try:
            if KEYBOARD_AVAILABLE:
                # Remove all previous hotkeys to avoid duplicates
                try:
                    keyboard.remove_hotkey('alt+a')
                    keyboard.remove_hotkey('ctrl+shift+a')
                    keyboard.remove_hotkey('alt+q')
                    keyboard.remove_hotkey('ctrl+alt+a')
                except:
                    pass

                # Only add Alt+A for file hover detection
                # Note: The actual hotkey handling is in track_input method

                # self.module_logger.info(
                #     "Hotkey registered: Alt+A for quick analysis")

                # Show notification to inform user
                # QTimer.singleShot(1000, lambda: self.tray_icon.showMessage(
                #     "Hotkey Available",
                #     "Left-click an audio file and press Alt+A to analyze it",
                #     QSystemTrayIcon.Information,
                #     3000
                # ))
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

        # Set startup by default
        try:
            if getattr(sys, 'frozen', False):
                # If running as exe (PyInstaller)
                executable_path = f'"{sys.executable}"'
            else:
                # If running as script
                executable_path = f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}"'

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_READ | winreg.KEY_SET_VALUE
            )

            try:
                winreg.QueryValueEx(key, "AudioTooltip")
            except FileNotFoundError:
                # Not found, so add it (default is enabled)
                winreg.SetValueEx(key, "AudioTooltip", 0,
                                  winreg.REG_SZ, executable_path)

            winreg.CloseKey(key)
        except Exception as e:
            self.module_logger.warning(f"Could not set startup: {e}")

    # Add this to setup_tray method in AudioTooltipApp class

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
        analyze_action = QAction("Analyze File... (Ctrl+Shift+A)", self)
        analyze_action.triggered.connect(self.open_file_dialog)

        # Dedicated action for analyzing selected file in Explorer
        analyze_selected_action = QAction(
            "Analyze Selected File in Explorer", self)
        analyze_selected_action.triggered.connect(self.trigger_detection)
        analyze_selected_action.setToolTip(
            "Try to analyze the currently selected file in Explorer")

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
        tray_menu.addAction(settings_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)

        # Add "Drop Target" action
        drop_target_action = QAction("Open Drop Target Window", self)
        drop_target_action.triggered.connect(self.show_drop_window)
        tray_menu.addAction(drop_target_action)

        # Add Alt+D to show the drop window
        keyboard.add_hotkey('alt+d', self.show_drop_window, suppress=False)

        # Set menu and show icon
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

        # Connect activation signal
        self.tray_icon.activated.connect(self.tray_icon_clicked)

        # Show startup tooltip
        self.tray_icon.showMessage(
            "Audio Tooltip Ready",
            "Left-click an audio file and press Alt+A to analyze it. The very first analysis may take several minutes. Please be patient. Following ones will be faster.",
            QSystemTrayIcon.Information,
            10000
        )

        self.module_logger.info("System tray initialized")

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
            # Show a custom quick menu on single click
            menu = QMenu()

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
            if self.settings.value("enable_transcription", "false") == "true":
                self.audio_analyzer.initialize_speech_services()

    def close_app(self):
        """Clean up and close the application"""
        self.module_logger.info("Closing application")
        self.running = False

        # Wait for tracking thread to exit
        if hasattr(self, 'tracking_thread') and self.tracking_thread.is_alive():
            self.tracking_thread.join(timeout=1.0)

        # Hide tooltip and cleanup resources
        self.tooltip.hide()
        if hasattr(self.tooltip, 'audio_player'):
            self.tooltip.audio_player.cleanup()

        # Final cleanup
        self.perform_cleanup()

        # Quit application
        QApplication.quit()

    def perform_cleanup(self):
        """Periodic cleanup to prevent memory leaks"""
        self.module_logger.debug("Performing periodic cleanup")

        # Clean up audio playback temp files
        if hasattr(self, 'audio_playback'):
            self.audio_playback.cleanup()

        # Force garbage collection
        collected = gc.collect()
        self.module_logger.debug(
            f"Garbage collection: {collected} objects collected")

    def get_top_right_position(self, tooltip):
        """Calculate top-right position for the tooltip"""
        screen = QApplication.primaryScreen().geometry()
        tooltip_size = tooltip.sizeHint()
        x = screen.width() - tooltip_size.width() - 20
        y = 40
        return QPoint(x, y)

    def show_progress_dialog(self, message):
        """Show progress dialog in main thread"""
        if not hasattr(self, 'progress_dialog') or self.progress_dialog is None:
            self.progress_dialog = ProgressDialog(
                None, "Analyzing Audio", message)
            self.progress_dialog.setWindowModality(Qt.NonModal)
        else:
            self.progress_dialog.update_message(message)

        self.progress_dialog.show()
        self.progress_dialog.raise_()

    def hide_progress_dialog(self):
        """Hide progress dialog"""
        if hasattr(self, 'progress_dialog') and self.progress_dialog is not None:
            self.progress_dialog.accept()
            self.progress_dialog = None

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

            # Ensure we keep track of workers
            if not hasattr(self, "workers"):
                self.workers = []  # Store all workers to prevent garbage collection

            # Create worker for async processing with force_refresh parameter
            try:
                worker = AudioTooltipWorker(
                    self.audio_analyzer, file_path, channel, force_refresh)

                # Connect worker signals
                try:
                    worker.finished.connect(
                        lambda result: self.handle_analysis_result(result, file_path, channel))
                    worker.progress.connect(
                        lambda msg: self.showProgressSignal.emit(msg))
                    worker.error.connect(self.handle_worker_error)
                    worker.finished.connect(
                        lambda: self.cleanup_worker(worker))  # Clean up when done
                except Exception as connect_e:
                    self.module_logger.error(
                        f"Error connecting worker signals: {connect_e}")
                    raise

                # Store worker reference
                self.workers.append(worker)

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
                    f"An unexpected error occurred:\n{str(e)}\n\nSee logs for details."
                )
            except:
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

    def handle_analysis_result(self, result, file_path, channel):
        """Handle successful audio analysis"""
        self.module_logger.info(
            f"Analysis complete for: {file_path}, channel {channel}")
        self.hideProgressSignal.emit()

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

        # Re-analyze the file with new channel
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
        use_whole_signal = self.settings.value(
            "use_whole_signal", "false") == "true"
        preview_duration = - \
            1 if use_whole_signal else int(
                self.settings.value("preview_duration", "10"))

        # Show progress dialog
        self.showProgressSignal.emit(f"Generating {viz_type}...")

        # Run in a worker thread
        worker = VisualizationWorker(
            self.audio_analyzer, self.tooltip.current_file, viz_type, channel, preview_duration)
        worker.finished.connect(self.update_visualization)
        worker.error.connect(self.handle_worker_error)
        worker.finished.connect(lambda: self.hideProgressSignal.emit())

        # Store worker reference
        if not hasattr(self, "viz_workers"):
            self.viz_workers = []
        self.viz_workers.append(worker)

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
            self.tooltip.viz_display.setPixmap(pixmap.scaled(
                self.tooltip.viz_display.width(),
                self.tooltip.viz_display.height(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            ))
            self.tooltip.viz_combo_menu.setText(viz_type)
            self.tooltip._change_visualization(viz_type)  # Update description

    def handle_worker_error(self, error_message):
        """Handle worker thread errors"""
        self.module_logger.error(f"Worker error: {error_message}")
        self.hideProgressSignal.emit()

        # Show error message
        QMessageBox.warning(
            None,
            "Analysis Error",
            f"An error occurred while analyzing the audio file:\n{error_message}"
        )

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

            # Get available screen geometry
            screen_rect = QApplication.primaryScreen().availableGeometry()

            # Set a reasonable size constraint
            max_width = min(screen_rect.width() - 100, 1600)
            max_height = min(screen_rect.height() - 100, 800)

            if self.tooltip.width() > max_width or self.tooltip.height() > max_height:
                self.tooltip.resize(max_width, max_height)

            # Position safely within screen bounds
            x = min(screen_rect.width() - self.tooltip.width() -
                    50, screen_rect.x() + screen_rect.width() - 50)
            y = min(50, screen_rect.y() + screen_rect.height() -
                    self.tooltip.height() - 50)
            x = max(screen_rect.x(), x)  # Ensure not off-screen left
            y = max(screen_rect.y(), y)  # Ensure not off-screen top

            self.tooltip.move(x, y)

            # Show with animation
            self.tooltip.show_with_fade()

            # Reset auto-hide timer
            self.tooltip.reset_auto_hide_timer()

        except Exception as e:
            self.module_logger.error(f"Error in show_tooltip_slot: {e}")
            self.module_logger.error(traceback.format_exc())

    # In main.py, add methods to handle transcription requests

    def on_transcription_requested(self, file_path, channel, language=None, transcription_channel=-1):
        """Handle transcription request from tooltip"""
        self.module_logger.info(
            f"Transcription requested for {file_path}, UI channel {channel}, " +
            f"transcription channel {transcription_channel}, language: {language or 'auto'}")

        # Show progress dialog
        self.showProgressSignal.emit("Transcribing audio...")

        # Run in a worker thread
        worker = TranscriptionWorker(
            self.audio_analyzer, file_path, channel, language, transcription_channel)
        worker.finished.connect(self.update_transcription)
        worker.error.connect(self.handle_worker_error)
        worker.finished.connect(lambda: self.hideProgressSignal.emit())
        worker.file_saved.connect(
            self.show_file_saved_notification)
        worker.file_saved.connect(self.set_transcript_file_path)

        # Store worker reference
        if not hasattr(self, "transcription_workers"):
            self.transcription_workers = []
        self.transcription_workers.append(worker)

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

    def check_file_under_cursor(self):
        """Check if there's an audio file under the cursor with better window detection"""
        self.module_logger.info("Checking for audio file under cursor")

        try:
            # Initialize COM for this thread with error handling
            try:
                pythoncom.CoInitializeEx(0)
            except Exception as com_e:
                self.module_logger.warning(
                    f"COM initialization error: {com_e}")
                # Continue anyway, it might still work

            # Get cursor position with error handling
            try:
                cursor_pos = win32api.GetCursorPos()
                self.module_logger.info(f"Cursor position: {cursor_pos}")
            except Exception as cursor_e:
                self.module_logger.error(
                    f"Failed to get cursor position: {cursor_e}")
                return False

            # Get the foreground window first - this is the most reliable way to know which window has focus
            try:
                foreground_hwnd = win32gui.GetForegroundWindow()
                foreground_title = win32gui.GetWindowText(foreground_hwnd)
                self.module_logger.info(
                    f"Foreground window: {foreground_hwnd}, Title: {foreground_title}")

                # Check if it looks like Explorer
                is_explorer = "explorer" in foreground_title.lower(
                ) or "file explorer" in foreground_title.lower()
                self.module_logger.info(
                    f"Foreground window is Explorer: {is_explorer}")
            except Exception as fg_e:
                self.module_logger.warning(
                    f"Error getting foreground window: {fg_e}")
                foreground_hwnd = None
                is_explorer = False

            # Try to get the Explorer window containing the cursor
            explorer_window = None
            explorer_path = None
            found_audio_file = False

            # Wrap Shell API calls in try/except
            try:
                shell = Dispatch("Shell.Application")
                windows = shell.Windows()

                self.module_logger.info(f"Found {windows.Count} shell windows")

                # First, try the foreground window if it's Explorer
                foreground_explorer = None
                if is_explorer and foreground_hwnd:
                    for i in range(windows.Count):
                        try:
                            window = windows.Item(i)
                            if window is None:
                                continue

                            try:
                                window_hwnd = window.HWND
                                if window_hwnd == foreground_hwnd:
                                    foreground_explorer = window
                                    explorer_window = window
                                    try:
                                        explorer_path = window.Document.Folder.Self.Path
                                        self.module_logger.info(
                                            f"Found foreground Explorer window at {explorer_path}")
                                        break
                                    except Exception as path_e:
                                        self.module_logger.warning(
                                            f"Error getting folder path: {path_e}")
                            except Exception as hwnd_e:
                                self.module_logger.warning(
                                    f"Error comparing HWND: {hwnd_e}")
                        except Exception as item_e:
                            self.module_logger.warning(
                                f"Error accessing window item: {item_e}")

                # If foreground window is Explorer, prioritize it for selection checking
                if foreground_explorer:
                    try:
                        selected_items = foreground_explorer.Document.SelectedItems()
                        if selected_items and selected_items.Count > 0:
                            for i in range(selected_items.Count):
                                try:
                                    item = selected_items.Item(i)
                                    file_path = item.Path

                                    if is_audio_file(file_path) and os.path.exists(file_path):
                                        self.module_logger.info(
                                            f"Audio file selected in foreground window: {file_path}")

                                        # Safer invocation with fallback
                                        try:
                                            QMetaObject.invokeMethod(
                                                self,
                                                "analyze_file",
                                                Qt.QueuedConnection,
                                                Q_ARG(str, file_path)
                                            )
                                            found_audio_file = True
                                            return True
                                        except Exception as invoke_e:
                                            self.module_logger.error(
                                                f"Error with QMetaObject: {invoke_e}")
                                            # Use QTimer as fallback
                                            QTimer.singleShot(
                                                0, lambda fp=file_path: self.analyze_file(fp))
                                            found_audio_file = True
                                            return True
                                except Exception as item_e:
                                    self.module_logger.warning(
                                        f"Error processing selected item: {item_e}")
                    except Exception as sel_e:
                        self.module_logger.warning(
                            f"Error getting selected items from foreground: {sel_e}")

                # If we didn't find anything in the foreground window, check ALL Explorer windows
                if not found_audio_file:
                    self.module_logger.info(
                        "Checking all Explorer windows for selection")

                    # First, check windows that contain the cursor (in z-order from top to bottom)
                    windows_with_cursor = []

                    for i in range(windows.Count):
                        try:
                            window = windows.Item(i)
                            if window is None:
                                continue

                            try:
                                hwnd = window.HWND
                                rect = win32gui.GetWindowRect(hwnd)

                                # Check if cursor is inside this window
                                if (rect[0] <= cursor_pos[0] <= rect[2] and rect[1] <= cursor_pos[1] <= rect[3]):
                                    windows_with_cursor.append(window)
                                    self.module_logger.info(
                                        f"Cursor is inside window {i}")
                            except Exception as rect_e:
                                self.module_logger.warning(
                                    f"Error getting window rectangle: {rect_e}")
                        except Exception as item_e:
                            self.module_logger.warning(
                                f"Error accessing window item: {item_e}")

                    # Check windows with cursor first
                    for window in windows_with_cursor:
                        try:
                            selected_items = window.Document.SelectedItems()
                            if selected_items and selected_items.Count > 0:
                                for i in range(selected_items.Count):
                                    try:
                                        item = selected_items.Item(i)
                                        file_path = item.Path

                                        if is_audio_file(file_path) and os.path.exists(file_path):
                                            self.module_logger.info(
                                                f"Audio file selected in window under cursor: {file_path}")
                                            QTimer.singleShot(
                                                0, lambda fp=file_path: self.analyze_file(fp))
                                            found_audio_file = True
                                            return True
                                    except Exception as item_e:
                                        self.module_logger.warning(
                                            f"Error processing selected item: {item_e}")
                        except Exception as sel_e:
                            self.module_logger.warning(
                                f"Error getting selected items: {sel_e}")

                    # If still not found, check all remaining Explorer windows
                    if not found_audio_file:
                        for i in range(windows.Count):
                            try:
                                window = windows.Item(i)
                                if window is None or window in windows_with_cursor:
                                    continue

                                try:
                                    selected_items = window.Document.SelectedItems()
                                    if selected_items and selected_items.Count > 0:
                                        for j in range(selected_items.Count):
                                            try:
                                                item = selected_items.Item(j)
                                                file_path = item.Path

                                                if is_audio_file(file_path) and os.path.exists(file_path):
                                                    self.module_logger.info(
                                                        f"Audio file selected in other window: {file_path}")
                                                    QTimer.singleShot(
                                                        0, lambda fp=file_path: self.analyze_file(fp))
                                                    found_audio_file = True
                                                    return True
                                            except Exception as item_e:
                                                self.module_logger.warning(
                                                    f"Error processing selected item: {item_e}")
                                except Exception as sel_e:
                                    self.module_logger.warning(
                                        f"Error getting selected items: {sel_e}")
                            except Exception as window_e:
                                self.module_logger.warning(
                                    f"Error processing window: {window_e}")

                # Last resort - try clipboard for file path
                if not found_audio_file:
                    try:
                        clipboard = QApplication.clipboard()
                        clipboard_text = clipboard.text()

                        if clipboard_text and os.path.exists(clipboard_text) and is_audio_file(clipboard_text):
                            self.module_logger.info(
                                f"Found audio file in clipboard: {clipboard_text}")
                            QTimer.singleShot(
                                0, lambda fp=clipboard_text: self.analyze_file(fp))
                            return True
                    except Exception as clip_e:
                        self.module_logger.error(
                            f"Error checking clipboard: {clip_e}")

                # Nothing worked, notify user
                if not found_audio_file:
                    try:
                        self.tray_icon.showMessage(
                            "Audio Tooltip",
                            "Couldn't identify an audio file under cursor. Try selecting an audio file first.",
                            QSystemTrayIcon.Information,
                            3000
                        )
                    except Exception as msg_e:
                        self.module_logger.error(
                            f"Failed to show tray message: {msg_e}")

                return found_audio_file

            except Exception as shell_e:
                self.module_logger.error(f"Shell API error: {shell_e}")
                # Don't return, we'll try fallback approaches
                return False

        except Exception as e:
            self.module_logger.error(f"Error checking file under cursor: {e}")
            self.module_logger.error(traceback.format_exc())
            return False
        finally:
            # Reset detection flag
            self.detection_active = False

            # Clean up COM
            try:
                pythoncom.CoUninitialize()
            except Exception as uninit_e:
                self.module_logger.warning(
                    f"Error uninitializing COM: {uninit_e}")

    def track_input(self):
        if not WINDOWS_API_AVAILABLE or not KEYBOARD_AVAILABLE:
            self.module_logger.error(
                "Cannot track input: missing dependencies")
            return

        self.module_logger.info("Input tracking thread started")

        def on_hotkey():
            # Only trigger when Alt+A is pressed
            if not self.detection_active:
                try:
                    self.detection_active = True
                    # Use a thread to avoid blocking the main thread
                    detection_thread = threading.Thread(
                        target=self.check_file_under_cursor)
                    detection_thread.daemon = True
                    detection_thread.start()
                except Exception as e:
                    self.module_logger.error(f"Error in hotkey handler: {e}")
                    self.module_logger.error(traceback.format_exc())
                    self.detection_active = False

        # Register Alt+A hotkey with error handling
        try:
            try:
                keyboard.remove_hotkey('alt+a')
            except:
                pass
            keyboard.add_hotkey('alt+a', on_hotkey, suppress=False)
            self.module_logger.info("Hotkey registered successfully")
        except Exception as reg_e:
            self.module_logger.error(f"Failed to register hotkey: {reg_e}")

        while self.running:
            try:
                time.sleep(0.05)
            except Exception as e:
                self.module_logger.error(f"Error in input tracking: {e}")
                self.module_logger.error(traceback.format_exc())
                time.sleep(0.5)

        self.module_logger.info("Input tracking thread terminated")

    def trigger_detection(self):
        self.module_logger.info(
            "Two-finger tap detected, initiating detection")
        self.detection_active = True
        detection_thread = threading.Thread(target=self.detect_audio_file)
        detection_thread.daemon = True
        detection_thread.start()

    def detect_audio_file(self):
        """Detect selected audio file in Explorer with improved multi-window handling"""
        if not WINDOWS_API_AVAILABLE:
            self.module_logger.error(
                "Cannot detect files: Windows API unavailable")
            self.detection_active = False
            return

        self.module_logger.info("Starting audio file detection")

        try:
            # Initialize COM for this thread
            pythoncom.CoInitializeEx(0)

            # Get foreground window info first
            foreground_hwnd = None
            try:
                foreground_hwnd = win32gui.GetForegroundWindow()
                window_title = win32gui.GetWindowText(foreground_hwnd)
                self.module_logger.info(
                    f"Foreground window: {window_title}, HWND: {foreground_hwnd}")
            except Exception as fg_e:
                self.module_logger.warning(
                    f"Error getting foreground window info: {fg_e}")

            # Try to get Shell Application
            try:
                shell = Dispatch("Shell.Application")
                windows = shell.Windows()

                self.module_logger.debug(
                    f"Found {windows.Count} Explorer windows")

                # Flag to track if an audio file was found
                found_file = False

                # First, try to match foreground window with Shell window
                foreground_explorer = None

                if foreground_hwnd:
                    for i in range(windows.Count):
                        try:
                            window = windows.Item(i)
                            if window is None:
                                continue

                            try:
                                window_hwnd = window.HWND
                                if window_hwnd == foreground_hwnd:
                                    foreground_explorer = window
                                    self.module_logger.info(
                                        f"Found matching foreground Explorer window at index {i}")
                                    break
                            except Exception as hwnd_e:
                                self.module_logger.warning(
                                    f"Error comparing HWND: {hwnd_e}")
                        except Exception as win_e:
                            self.module_logger.warning(
                                f"Error accessing window item {i}: {win_e}")

                # If we found the foreground Explorer window, check it first
                if foreground_explorer:
                    try:
                        selected = foreground_explorer.Document.SelectedItems()
                        if selected and selected.Count > 0:
                            self.module_logger.info(
                                f"Found {selected.Count} selected items in foreground window")

                            # Check each selected item
                            for j in range(selected.Count):
                                try:
                                    item = selected.Item(j)
                                    current_file = item.Path

                                    # Verify file exists and is audio
                                    if os.path.exists(current_file) and is_audio_file(current_file):
                                        self.module_logger.info(
                                            f"Audio file detected in foreground: {current_file}")

                                        # Process file in main thread
                                        QMetaObject.invokeMethod(
                                            self,
                                            "analyze_file",
                                            Qt.QueuedConnection,
                                            Q_ARG(str, current_file),
                                            # Default to channel 0
                                            Q_ARG(int, 0)
                                        )
                                        found_file = True
                                        break
                                except Exception as item_e:
                                    self.module_logger.error(
                                        f"Error processing foreground item {j}: {item_e}")
                        else:
                            self.module_logger.info(
                                "No items selected in foreground window")
                    except Exception as sel_e:
                        self.module_logger.error(
                            f"Error accessing selected items in foreground window: {sel_e}")

                # If nothing found in foreground window, or no foreground Explorer window found,
                # check ALL Explorer windows (like before)
                if not found_file:
                    self.module_logger.info(
                        "Checking all Explorer windows for selected audio files")

                    # Get Z-ordered list of visible windows first
                    visible_windows = []

                    # Use win32gui to get z-order of windows
                    def enum_windows_callback(hwnd, windows_list):
                        if win32gui.IsWindowVisible(hwnd):
                            windows_list.append(hwnd)

                    window_z_order = []
                    win32gui.EnumWindows(enum_windows_callback, window_z_order)

                    # Now map shell windows to z-order if possible
                    shell_windows_by_z = []
                    for hwnd in window_z_order:
                        for i in range(windows.Count):
                            try:
                                window = windows.Item(i)
                                if window and window.HWND == hwnd:
                                    shell_windows_by_z.append(window)
                                    break
                            except:
                                pass

                    # Add any remaining shell windows that we couldn't match
                    for i in range(windows.Count):
                        try:
                            window = windows.Item(i)
                            if window and window not in shell_windows_by_z:
                                shell_windows_by_z.append(window)
                        except:
                            pass

                    # Now check each window in Z order (top to bottom)
                    for window in shell_windows_by_z:
                        try:
                            # Skip if it's the foreground window we already checked
                            if foreground_explorer and window.HWND == foreground_explorer.HWND:
                                continue

                            try:
                                window_path = window.Document.Folder.Self.Path
                                window_title = window.Document.Title
                                self.module_logger.info(
                                    f"Checking window: Title={window_title}, Path={window_path}")
                            except:
                                self.module_logger.debug(
                                    "Could not get window details")
                                continue

                            # Try to get selected items with better error handling
                            try:
                                selected = window.Document.SelectedItems()

                                if selected is None or selected.Count == 0:
                                    self.module_logger.debug(
                                        "No items selected in this window")
                                    continue

                                self.module_logger.info(
                                    f"Found {selected.Count} selected items")

                                # Check each selected item
                                for j in range(selected.Count):
                                    try:
                                        item = selected.Item(j)
                                        current_file = item.Path

                                        # Verify it's an audio file
                                        if is_audio_file(current_file) and os.path.exists(current_file):
                                            self.module_logger.info(
                                                f"Audio file detected: {current_file}")

                                            # Process file in main thread
                                            QMetaObject.invokeMethod(
                                                self,
                                                "analyze_file",
                                                Qt.QueuedConnection,
                                                Q_ARG(str, current_file),
                                                # Default to channel 0
                                                Q_ARG(int, 0)
                                            )
                                            found_file = True
                                            break
                                    except Exception as item_e:
                                        self.module_logger.error(
                                            f"Error processing item: {item_e}")

                                if found_file:
                                    break

                            except Exception as select_e:
                                self.module_logger.error(
                                    f"Error accessing selected items: {select_e}")

                        except Exception as window_e:
                            self.module_logger.error(
                                f"Error processing window: {window_e}")

                    # Try fallback to focused item if no selection found
                    if not found_file:
                        self.module_logger.info(
                            "No selected items found, trying focused items")
                        for window in shell_windows_by_z:
                            try:
                                if window.Visible:
                                    try:
                                        focused = window.Document.FocusedItem
                                        if focused:
                                            current_file = focused.Path
                                            self.module_logger.info(
                                                f"Focused file: {current_file}")

                                            if is_audio_file(current_file) and os.path.exists(current_file):
                                                self.module_logger.info(
                                                    f"Audio file detected (focused): {current_file}")

                                                QMetaObject.invokeMethod(
                                                    self,
                                                    "analyze_file",
                                                    Qt.QueuedConnection,
                                                    Q_ARG(str, current_file),
                                                    Q_ARG(int, 0)
                                                )
                                                found_file = True
                                                break
                                    except:
                                        pass
                            except:
                                pass

                    # Last resort - try clipboard
                    if not found_file:
                        self.module_logger.info(
                            "Trying clipboard for file path")
                        try:
                            clipboard = QApplication.clipboard()
                            clipboard_text = clipboard.text()

                            if clipboard_text and os.path.exists(clipboard_text) and is_audio_file(clipboard_text):
                                self.module_logger.info(
                                    f"Found audio file in clipboard: {clipboard_text}")

                                QMetaObject.invokeMethod(
                                    self,
                                    "analyze_file",
                                    Qt.QueuedConnection,
                                    Q_ARG(str, clipboard_text),
                                    Q_ARG(int, 0)
                                )
                                found_file = True
                        except Exception as clip_e:
                            self.module_logger.error(
                                f"Error checking clipboard: {clip_e}")

                    if not found_file:
                        self.module_logger.info(
                            "No audio files found in any window")
                        # Show notification to user
                        self.tray_icon.showMessage(
                            "Audio Tooltip",
                            "No audio file selected. Please select an audio file in Explorer.",
                            QSystemTrayIcon.Information,
                            3000
                        )

            except Exception as shell_e:
                self.module_logger.error(f"Error accessing Shell: {shell_e}")
                self.module_logger.error(traceback.format_exc())

        except Exception as e:
            self.module_logger.error(f"Error in audio file detection: {e}")
            self.module_logger.error(traceback.format_exc())

        finally:
            # Reset detection flag
            self.detection_active = False

            # Clean up COM
            try:
                pythoncom.CoUninitialize()
            except:
                pass

            self.module_logger.info("Audio file detection completed")


# Add to main.py (near the top of the main() function)
def main(app=None, splash=None):
    """Main application entry point"""
    print("Main function started")

    print(f"Python version: {sys.version}")
    import PyQt5
    print(f"PyQt5 version: {PyQt5.QtCore.QT_VERSION_STR}")

    try:
        # If app wasn't provided, create it (for backward compatibility)
        if app is None:
            app = QApplication(sys.argv)
            app.setQuitOnLastWindowClosed(False)
            app.setApplicationName("Audio Tooltip")
            app.setOrganizationName("MCDE - FHL 2025")
        print("App configuration checked")

        # Update splash message if splash exists
        if splash:
            print("Updating splash message")
            splash.showMessage("Initializing components...",
                               Qt.AlignBottom | Qt.AlignCenter, Qt.black)
            app.processEvents()

        # Create main app with explicit error handling
        print("About to create AudioTooltipApp")
        tooltip_app = AudioTooltipApp()
        print("AudioTooltipApp created successfully")

        # Close splash if it exists
        if splash:
            print("Finishing splash screen")
            splash.finish(None)

        # Start the event loop
        print("Starting event loop")
        return app.exec_()
    except Exception as e:
        print(f"ERROR STARTING APPLICATION: {str(e)}")
        import traceback
        traceback.print_exc()
        if splash:
            splash.finish(None)
        return 1


if __name__ == '__main__':
    print("Starting application initialization...")

    # Create application first
    app = QApplication(sys.argv)
    print("QApplication created")

    app.setQuitOnLastWindowClosed(False)  # Keep running when windows close
    app.setApplicationName("Audio Tooltip")
    app.setOrganizationName("MCDE - FHL 2025")
    print("Application configured")

    # Create and show splash screen BEFORE any other initialization
    print("Setting up splash screen...")
    splash_pixmap = QPixmap(400, 250)
    splash_pixmap.fill(QColor(245, 245, 245))
    print("Splash pixmap created")

    # Draw text on the pixmap
    print("Creating painter...")
    painter = QPainter(splash_pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    print("Painter configured")

    # Rest of the splash screen setup with print statements...
    print("About to show splash screen")
    # Create splash screen using the painted pixmap
    splash = QSplashScreen(splash_pixmap)
    print("Splash screen created")

    # More execution...
    print("About to call main()")
    sys.exit(main(app, splash))
