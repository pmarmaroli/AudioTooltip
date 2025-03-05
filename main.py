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

    def __init__(self, analyzer, file_path, channel=0):
        super().__init__()
        self.analyzer = analyzer
        self.file_path = file_path
        self.channel = channel
        self.logger = get_module_logger("AudioTooltipWorker")

    def run(self):
        """Process audio file"""
        self.logger.info(
            f"Starting worker for {self.file_path}, channel {self.channel}")

        try:
            # Ensure analyzer is initialized
            if not self.analyzer.initialized:
                self.progress.emit("Initializing analyzer...")
                self.analyzer.initialize()

            # Process file
            self.progress.emit(
                f"Loading audio data (channel {self.channel+1})...")
            result = self.analyzer.process_audio_file(
                self.file_path, self.channel)

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
    def analyze_file(self, file_path, channel=0):
        """Process audio file with worker thread"""
        self.module_logger.info(
            f"Analyzing file: {file_path}, channel: {channel}")

        # Validate file path
        is_valid, error_message = validate_audio_file_path(
            file_path, self.module_logger)
        if not is_valid:
            self.module_logger.error(f"Invalid audio file: {error_message}")
            QMessageBox.warning(
                None,
                "Invalid Audio File",
                f"Cannot analyze this file:\n{error_message}"
            )
            return

        # Ensure we keep track of workers
        if not hasattr(self, "workers"):
            self.workers = []  # Store all workers to prevent garbage collection

        # Create worker for async processing
        worker = AudioTooltipWorker(self.audio_analyzer, file_path, channel)

        # Connect worker signals
        worker.finished.connect(
            lambda result: self.handle_analysis_result(result, file_path, channel))
        worker.progress.connect(lambda msg: self.showProgressSignal.emit(msg))
        worker.error.connect(self.handle_worker_error)
        worker.finished.connect(
            lambda: self.cleanup_worker(worker))  # Clean up when done

        # Store worker reference
        self.workers.append(worker)

        # Show progress dialog
        self.showProgressSignal.emit(
            f"Analyzing {os.path.basename(file_path)} (channel {channel+1})...")

        # Start worker
        worker.start()

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

            file_path, metadata, viz_buffer, transcription, num_channels = result

            # Complete result
            final_result = (file_path, metadata, viz_buffer,
                            transcription, num_channels, channel)

            # Show tooltip with results
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
            # Unpack result - now with channel information
            if len(result) == 6:  # New format with channel info
                file_path, metadata, viz_buffer, transcription, num_channels, channel = result
            else:  # Old format compatibility
                file_path, metadata, viz_buffer, transcription = result
                num_channels, channel = 1, 0

            # Update tooltip content
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
        """Check if there's an audio file under the cursor"""
        self.module_logger.info("Checking for audio file under cursor")

        try:
            # Initialize COM for this thread
            pythoncom.CoInitializeEx(0)

            # Get cursor position
            cursor_pos = win32api.GetCursorPos()
            self.module_logger.info(f"Cursor position: {cursor_pos}")

            # Try to get the Explorer window containing the cursor
            explorer_window = None
            explorer_path = None

            shell = Dispatch("Shell.Application")
            windows = shell.Windows()

            # First try: check all Explorer windows and see if cursor is inside
            for i in range(windows.Count):
                try:
                    window = windows.Item(i)
                    if window is None:
                        continue

                    try:
                        hwnd = window.HWND
                        rect = win32gui.GetWindowRect(hwnd)

                        # Check if cursor is inside this window
                        if (rect[0] <= cursor_pos[0] <= rect[2] and
                                rect[1] <= cursor_pos[1] <= rect[3]):
                            explorer_window = window
                            try:
                                explorer_path = window.Document.Folder.Self.Path
                                self.module_logger.info(
                                    f"Found Explorer window at {explorer_path}")
                                break
                            except:
                                pass
                    except:
                        pass
                except:
                    continue

            # Second try: look at selected items in all windows
            if explorer_window:
                try:
                    # Try to get selected items
                    selected_items = explorer_window.Document.SelectedItems()

                    if selected_items and selected_items.Count > 0:
                        for i in range(selected_items.Count):
                            item = selected_items.Item(i)
                            file_path = item.Path

                            if is_audio_file(file_path) and os.path.exists(file_path):
                                self.module_logger.info(
                                    f"Audio file selected: {file_path}")

                                QMetaObject.invokeMethod(
                                    self,
                                    "analyze_file",
                                    Qt.QueuedConnection,
                                    Q_ARG(str, file_path)
                                )
                                return True

                    # No selected items or no audio files, try current folder
                    if explorer_path:
                        # Get all files in the current folder
                        folder_items = explorer_window.Document.Folder.Items()

                        # Get client area coordinates
                        client_pos = win32gui.ScreenToClient(
                            explorer_window.HWND, cursor_pos)

                        # This is a simplified approach since we can't directly get item at position
                        # We'll analyze all audio files in the folder
                        audio_files = []

                        for i in range(folder_items.Count):
                            item = folder_items.Item(i)
                            file_path = item.Path

                            if is_audio_file(file_path) and os.path.exists(file_path):
                                audio_files.append(file_path)

                        if audio_files:
                            # Show dialog to select which audio file
                            if len(audio_files) == 1:
                                file_path = audio_files[0]
                                self.module_logger.info(
                                    f"Single audio file in folder: {file_path}")

                                QMetaObject.invokeMethod(
                                    self,
                                    "analyze_file",
                                    Qt.QueuedConnection,
                                    Q_ARG(str, file_path),
                                    Q_ARG(int, 0)
                                )
                                return True
                            else:
                                # In a real implementation, you might want to show a selection dialog
                                # For now, we'll just take the first audio file
                                file_path = audio_files[0]
                                self.module_logger.info(
                                    f"Selected first audio file from folder: {file_path}")

                                QMetaObject.invokeMethod(
                                    self,
                                    "analyze_file",
                                    Qt.QueuedConnection,
                                    Q_ARG(str, file_path),
                                    Q_ARG(int, 0)
                                )
                                return True
                except Exception as e:
                    self.module_logger.error(
                        f"Error getting items from Explorer: {e}")

            # Last resort - try clipboard for file path
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
                return True

            # Nothing worked, notify user
            self.tray_icon.showMessage(
                "Audio Tooltip",
                "Couldn't identify an audio file under cursor. Try selecting an audio file first.",
                QSystemTrayIcon.Information,
                3000
            )
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
            except:
                pass

    def track_input(self):
        if not WINDOWS_API_AVAILABLE or not KEYBOARD_AVAILABLE:
            self.module_logger.error(
                "Cannot track input: missing dependencies")
            return

        self.module_logger.info("Input tracking thread started")

        def on_hotkey():
            # Only trigger when Alt+A is pressed
            if not self.detection_active:
                self.detection_active = True
                self.check_file_under_cursor()

        # Register Alt+A hotkey
        try:
            keyboard.remove_hotkey('alt+a')
        except:
            pass
        keyboard.add_hotkey('alt+a', on_hotkey, suppress=False)

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
        """Detect selected audio file in Explorer"""
        if not WINDOWS_API_AVAILABLE:
            self.module_logger.error(
                "Cannot detect files: Windows API unavailable")
            self.detection_active = False
            return

        self.module_logger.info("Starting audio file detection")

        try:
            # Initialize COM for this thread
            pythoncom.CoInitializeEx(0)

            # Alternative approach using GetForegroundWindow and cursor position
            try:
                import win32gui
                import win32api

                # Get cursor position
                cursor_pos = win32api.GetCursorPos()
                self.module_logger.info(f"Cursor position: {cursor_pos}")

                # Get foreground window
                foreground_window = win32gui.GetForegroundWindow()
                window_title = win32gui.GetWindowText(foreground_window)
                self.module_logger.info(f"Foreground window: {window_title}")

                # Check if we're in File Explorer
                if "File Explorer" in window_title or "Explorer" in window_title:
                    # If we're in Explorer, try the normal approach
                    self.module_logger.info(
                        "In File Explorer window, trying normal detection...")
                else:
                    # Try direct file method based on current position
                    self.module_logger.info(
                        "Not in Explorer window, checking for audio file under cursor...")
                    # Check if there's an audio file at the current position
                    # This would require platform-specific implementations
            except Exception as cursor_e:
                self.module_logger.warning(
                    f"Error with position-based detection: {cursor_e}")

            # Now try the Shell API approach
            shell = None
            try:
                shell = Dispatch("Shell.Application")
                windows = shell.Windows()

                self.module_logger.debug(
                    f"Found {windows.Count} Explorer windows")

                # Flag to track if an audio file was found
                found_file = False

                # Improved window detection
                active_window_found = False

                # Check each Explorer window
                for i in range(windows.Count):
                    try:
                        window = windows.Item(i)

                        # Skip if not Explorer
                        if window is None:
                            continue

                        try:
                            window_path = window.Document.Folder.Self.Path
                            window_title = window.Document.Title
                            self.module_logger.info(
                                f"Window {i}: Title={window_title}, Path={window_path}")
                        except:
                            self.module_logger.debug(
                                f"Window {i}: Could not get details")
                            continue

                        # Check if this window has the focus - may not be reliable
                        try:
                            if window.Visible and window.Document.FocusedItem is not None:
                                self.module_logger.info(
                                    f"Window {i} appears to have focus")
                                active_window_found = True
                        except:
                            pass

                        # Try to get selected items - be extra careful with error handling
                        try:
                            selected = window.Document.SelectedItems()
                            if selected is None:
                                self.module_logger.debug(
                                    f"Window {i}: No selected items object")
                                continue

                            if selected.Count == 0:
                                self.module_logger.debug(
                                    f"Window {i}: No items selected")
                                continue

                            self.module_logger.info(
                                f"Window {i}: Found {selected.Count} selected items")

                            # Check each selected item
                            for j in range(selected.Count):
                                try:
                                    item = selected.Item(j)

                                    # Get full path with error handling
                                    try:
                                        current_file = item.Path
                                        self.module_logger.info(
                                            f"Selected file: {current_file}")

                                        # Extra validation
                                        if not current_file or not isinstance(current_file, str):
                                            self.module_logger.warning(
                                                f"Invalid file path: {current_file}")
                                            continue

                                        # Verify file exists
                                        if not os.path.exists(current_file):
                                            self.module_logger.warning(
                                                f"File does not exist: {current_file}")
                                            continue

                                    except Exception as path_e:
                                        self.module_logger.error(
                                            f"Error getting path for item {j}: {path_e}")
                                        continue

                                    # Explicit check for audio file
                                    file_ext = os.path.splitext(
                                        current_file.lower())[1]
                                    if file_ext in AUDIO_EXTENSIONS:
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
                                    else:
                                        self.module_logger.info(
                                            f"Selected file is not an audio file: {file_ext}")

                                except Exception as item_e:
                                    self.module_logger.error(
                                        f"Error processing item {j}: {item_e}")
                                    self.module_logger.error(
                                        traceback.format_exc())

                            if found_file:
                                break

                        except Exception as select_e:
                            self.module_logger.error(
                                f"Error accessing selected items in window {i}: {select_e}")
                            self.module_logger.error(traceback.format_exc())

                    except Exception as window_e:
                        self.module_logger.error(
                            f"Error processing window {i}: {window_e}")
                        self.module_logger.error(traceback.format_exc())

                # Try fallback to focused item if no selection found
                if not found_file and active_window_found:
                    self.module_logger.info(
                        "No selected items found, trying focused item")
                    for i in range(windows.Count):
                        try:
                            window = windows.Item(i)
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
                    self.module_logger.info("Trying clipboard for file path")
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
                        "No audio files found in selection")
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
    # If app wasn't provided, create it (for backward compatibility)
    if app is None:
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        app.setApplicationName("Audio Tooltip")
        app.setOrganizationName("MCDE - FHL 2025")

    # Update splash message if splash exists
    if splash:
        splash.showMessage("Initializing components...",
                           Qt.AlignBottom | Qt.AlignCenter, Qt.black)
        app.processEvents()

    # Create main app
    tooltip_app = AudioTooltipApp()

    # Close splash if it exists
    if splash:
        splash.finish(None)

    # Rest of your main function code...

    # Start the event loop
    return app.exec_()


if __name__ == '__main__':
    # Create application first
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Keep running when windows close
    app.setApplicationName("Audio Tooltip")
    app.setOrganizationName("MCDE - FHL 2025")

    # Create and show splash screen BEFORE any other initialization
    splash_pixmap = QPixmap(400, 250)
    splash_pixmap.fill(QColor(245, 245, 245))

    # Draw text on the pixmap
    painter = QPainter(splash_pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)

    # Try to load and draw the logo
    icon_path = os.path.join(os.path.dirname(
        os.path.abspath(__file__)), "resources/icons/app_icon.png")
    if os.path.exists(icon_path):
        logo = QPixmap(icon_path)
        # Scale logo to reasonable size if needed
        if not logo.isNull():
            scaled_logo = logo.scaled(
                64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            # Draw logo centered horizontally, above the title
            painter.drawPixmap(
                (400 - scaled_logo.width()) // 2, 20, scaled_logo)

        # Draw title
        title_font = QFont("Arial", 16, QFont.Bold)
        painter.setFont(title_font)
        painter.setPen(QColor(60, 60, 60))
        painter.drawText(QRect(0, 95, 400, 40),
                         Qt.AlignCenter, "Audio Tooltip")

        # Draw version number
        version = "v1.0.2"  # You can change this to your desired version number
        version_font = QFont("Arial", 9)
        painter.setFont(version_font)
        painter.setPen(QColor(120, 120, 120))
        painter.drawText(QRect(0, 130, 400, 20), Qt.AlignCenter, version)

        # Draw loading text
        info_font = QFont("Arial", 10)
        painter.setFont(info_font)
        painter.setPen(QColor(100, 100, 100))
        painter.drawText(QRect(0, 170, 400, 30),
                         Qt.AlignCenter, "Loading application...")

        # Draw a fixed progress bar
        painter.setPen(QColor(200, 200, 200))
        painter.setBrush(QColor(200, 200, 200))
        painter.drawRoundedRect(50, 200, 300, 14, 7, 7)

        painter.setPen(QColor(75, 130, 195))
        painter.setBrush(QColor(75, 130, 195))
        painter.drawRoundedRect(50, 200, 150, 14, 7, 7)
        painter.end()

        # Create splash screen using the painted pixmap
        splash = QSplashScreen(splash_pixmap)
        splash.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)

        # Show splash and process events to make it visible immediately
        splash.show()
        app.processEvents()

    # Now continue with the main function
    sys.exit(main(app, splash))
