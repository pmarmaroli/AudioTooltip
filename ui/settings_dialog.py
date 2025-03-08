"""
Settings Dialog Module
---------------------
Provides a dialog for configuring application settings.
"""

from PyQt5.QtCore import Qt, QSettings
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QFormLayout,
    QLabel, QLineEdit, QCheckBox, QSpinBox, QDoubleSpinBox, QComboBox,
    QPushButton, QGroupBox, QDialogButtonBox, QFileDialog, QMessageBox
)

import azure.cognitiveservices.speech as speechsdk
import tempfile
import os
import wave
import sys
import winreg


class SettingsDialog(QDialog):
    """
    Settings dialog with multiple configuration categories.

    Features:
    - Multiple tabs for different setting groups
    - Input validation
    - Settings persistence
    """

    def __init__(self, parent=None, settings=None):
        """
        Initialize settings dialog.

        Args:
            parent: Parent widget
            settings: QSettings instance for storing preferences
        """
        super().__init__(parent)

        self.setWindowTitle("Settings")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)

        self.settings = settings or QSettings(
            "AudioTooltip", "EnhancedPreferences")

        self._init_ui()
        self._load_settings()

    def _init_ui(self):
        """Initialize dialog UI"""
        main_layout = QVBoxLayout(self)

        # Create tab widget
        self.tab_widget = QTabWidget(self)

        # Create tabs
        self.general_tab = self._create_general_tab()
        self.analysis_tab = self._create_analysis_tab()
        self.transcription_tab = self._create_transcription_tab()

        # Add tabs to widget
        self.tab_widget.addTab(self.general_tab, "General")
        self.tab_widget.addTab(self.analysis_tab, "Analysis")
        self.tab_widget.addTab(self.transcription_tab, "Transcription")

        main_layout.addWidget(self.tab_widget)

        # Add standard dialog buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply,
            Qt.Horizontal, self
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        button_box.button(QDialogButtonBox.Apply).clicked.connect(
            self._apply_settings)

        main_layout.addWidget(button_box)

    def _toggle_startup(self, state):
        """Toggle startup with Windows"""
        try:
            if state == Qt.Checked:
                self._enable_startup()
            else:
                self._disable_startup()
        except Exception as e:
            QMessageBox.warning(
                self,
                "Startup Setting Error",
                f"Could not change startup setting: {str(e)}"
            )

    def _enable_startup(self):
        """Add application to Windows startup"""
        try:
            # Get path to the executable
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
                winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, "AudioTooltip", 0,
                              winreg.REG_SZ, executable_path)
            winreg.CloseKey(key)
        except Exception as e:
            raise Exception(f"Failed to add to startup: {str(e)}")

    def _disable_startup(self):
        """Remove application from Windows startup"""
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE
            )
            try:
                winreg.DeleteValue(key, "AudioTooltip")
            except FileNotFoundError:
                # Key doesn't exist, which is fine
                pass
            winreg.CloseKey(key)
        except Exception as e:
            raise Exception(f"Failed to remove from startup: {str(e)}")

    def _create_general_tab(self):
        """Create general settings tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Interface group
        interface_group = QGroupBox("Interface")
        interface_layout = QFormLayout(interface_group)

        self.auto_close_check = QCheckBox("Automatically close tooltip")
        self.auto_close_check.setChecked(True)

        self.auto_close_time_spin = QSpinBox()
        self.auto_close_time_spin.setRange(1, 60)
        self.auto_close_time_spin.setValue(10)
        self.auto_close_time_spin.setSuffix(" seconds")

        # Add startup option
        self.startup_check = QCheckBox(
            "Start AudioTooltip when Windows starts")
        self.startup_check.setChecked(True)
        self.startup_check.stateChanged.connect(self._toggle_startup)

        interface_layout.addRow("", self.auto_close_check)
        interface_layout.addRow("Auto-close after:", self.auto_close_time_spin)
        interface_layout.addRow("", self.startup_check)

        # Add to layout
        layout.addWidget(interface_group)
        layout.addStretch(1)

        return tab

    def _create_analysis_tab(self):
        """Create analysis settings tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Audio loading group
        loading_group = QGroupBox("Audio Loading")
        loading_layout = QFormLayout(loading_group)

        self.preview_duration_spin = QSpinBox()
        self.preview_duration_spin.setRange(5, 3600)  # 5 seconds to 60 minutes
        self.preview_duration_spin.setValue(10)
        self.preview_duration_spin.setSuffix(" seconds")

        self.whole_signal_check = QCheckBox("Use whole signal duration")
        self.whole_signal_check.setChecked(True)
        self.whole_signal_check.stateChanged.connect(
            self._toggle_preview_duration)

        loading_layout.addRow("Preview duration:", self.preview_duration_spin)
        loading_layout.addRow("", self.whole_signal_check)

        # Add to layout
        layout.addWidget(loading_group)
        layout.addStretch(1)

        return tab

    def _toggle_preview_duration(self, state):
        """Enable/disable preview duration based on whole signal checkbox"""
        self.preview_duration_spin.setEnabled(state != Qt.Checked)

        self.settings.setValue(
            "use_whole_signal", "true" if state == Qt.Checked else "false")

    def _create_transcription_tab(self):
        """Create transcription settings tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Master enable
        self.enable_transcription_check = QCheckBox(
            "Enable speech transcription")
        self.enable_transcription_check.setChecked(False)
        self.enable_transcription_check.stateChanged.connect(
            self._toggle_transcription_options)

        layout.addWidget(self.enable_transcription_check)

        # Transcription Duration group - ADD THIS NEW GROUP
        duration_group = QGroupBox("Transcription Duration")
        duration_layout = QFormLayout(duration_group)

        self.transcription_duration_combo = QComboBox()
        self.transcription_duration_combo.addItem(
            "Same as preview duration", "preview")
        self.transcription_duration_combo.addItem("Maximum (60 seconds)", "60")
        self.transcription_duration_combo.addItem(
            "Entire file (may be slow for large files)", "full")

        duration_layout.addRow("Duration to transcribe:",
                               self.transcription_duration_combo)

        # Azure credentials group
        azure_group = QGroupBox("Azure Speech Services")
        azure_layout = QFormLayout(azure_group)

        self.azure_key_edit = QLineEdit()
        self.azure_key_edit.setEchoMode(QLineEdit.Password)
        self.azure_key_edit.setPlaceholderText(
            "Enter your Azure subscription key")

        self.azure_region_combo = QComboBox()
        for region in [
            "eastus", "eastus2", "westus", "westus2", "centralus",
            "northeurope", "westeurope", "southeastasia", "eastasia"
        ]:
            self.azure_region_combo.addItem(region)

        self.language_combo = QComboBox()
        languages = [
            ("Auto-detect", ""),
            ("English (US)", "en-US"),
            ("English (UK)", "en-GB"),
            ("Spanish", "es-ES"),
            ("French", "fr-FR"),
            ("German", "de-DE"),
            ("Italian", "it-IT"),
            ("Japanese", "ja-JP"),
            ("Chinese", "zh-CN"),
        ]
        for label, code in languages:
            self.language_combo.addItem(label, code)

        azure_layout.addRow("Subscription Key:", self.azure_key_edit)
        azure_layout.addRow("Region:", self.azure_region_combo)
        azure_layout.addRow("Language:", self.language_combo)

        # Test button
        test_layout = QHBoxLayout()
        test_button = QPushButton("Test Connection")
        test_button.clicked.connect(self._test_azure_connection)
        test_layout.addStretch(1)
        test_layout.addWidget(test_button)

        azure_layout.addRow("", test_layout)

        # Add to layout
        layout.addWidget(duration_group)
        layout.addWidget(azure_group)

        # Help text
        help_label = QLabel(
            "Speech transcription requires an Azure Speech Services subscription.\n"
            "Visit <a href='https://azure.microsoft.com/services/cognitive-services/speech-services/'>Azure Portal</a> "
            "to create a free account."
        )
        help_label.setOpenExternalLinks(True)
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #555; margin-top: 10px;")

        layout.addWidget(help_label)
        layout.addStretch(1)

        # Initially disable if transcription not enabled
        self._toggle_transcription_options(Qt.Unchecked)

        return tab

    def _toggle_feature_options(self, state):
        """Enable/disable feature options based on master switch"""
        enabled = state == Qt.Checked
        for checkbox in self.feature_checks.values():
            checkbox.setEnabled(enabled)

    def _toggle_transcription_options(self, state):
        """Enable/disable transcription options based on master switch"""
        enabled = state == Qt.Checked
        self.azure_key_edit.setEnabled(enabled)
        self.azure_region_combo.setEnabled(enabled)
        self.language_combo.setEnabled(enabled)

    def _test_azure_connection(self):
        """Test Azure Speech Services connection"""
        if not self.azure_key_edit.text() or self.azure_region_combo.currentText() == "":
            QMessageBox.warning(
                self,
                "Missing Credentials",
                "Please enter your Azure Speech Services key and select a region."
            )
            return

        try:

            # Create a temporary dummy wav file for testing
            temp_wav_path = None
            try:
                # Use NamedTemporaryFile with delete=False to avoid access issues
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_wav:
                    temp_wav_path = temp_wav.name
                    # Create a minimal 1-second silent WAV file
                    with wave.open(temp_wav_path, 'wb') as wav_file:
                        wav_file.setnchannels(1)
                        wav_file.setsampwidth(2)
                        wav_file.setframerate(16000)
                        # 1 second of silence
                        wav_file.writeframes(b'\x00' * 16000)

                # Configure speech configuration for testing
                speech_config = speechsdk.SpeechConfig(
                    subscription=self.azure_key_edit.text(),
                    region=self.azure_region_combo.currentText()
                )

                # Set a minimal test configuration
                speech_config.speech_recognition_language = "en-US"

                # Create audio config with the temporary file
                audio_config = speechsdk.AudioConfig(filename=temp_wav_path)

                # Create speech recognizer
                speech_recognizer = speechsdk.SpeechRecognizer(
                    speech_config=speech_config,
                    audio_config=audio_config
                )

                # Use a timeout to prevent hanging
                from threading import Event, Thread

                connection_successful = Event()
                connection_error = Event()

                def test_connection():
                    try:
                        # Attempt recognition
                        result = speech_recognizer.recognize_once()

                        # Check result status
                        if result.reason == speechsdk.ResultReason.NoMatch:
                            # This is expected for a silent file
                            connection_successful.set()
                        elif result.reason == speechsdk.ResultReason.Canceled:
                            # Connection or configuration error
                            cancellation = result.cancellation_details
                            connection_error.error = f"Cancellation reason: {cancellation.reason}"
                            connection_error.set()
                        else:
                            # Unexpected success scenario
                            connection_successful.set()

                    except Exception as e:
                        # Store the error for display
                        connection_error.error = str(e)
                        connection_error.set()

                # Run connection test in a separate thread
                test_thread = Thread(target=test_connection)
                test_thread.start()
                test_thread.join(timeout=10)  # 10-second timeout

                # Check connection results
                if connection_successful.is_set():
                    QMessageBox.information(
                        self,
                        "Connection Test",
                        "Connection to Azure Speech Services successful!\n"
                        "Your credentials are valid and functional."
                    )
                elif connection_error.is_set():
                    QMessageBox.warning(
                        self,
                        "Connection Failed",
                        f"Unable to connect to Azure Speech Services:\n{connection_error.error}"
                    )
                else:
                    QMessageBox.warning(
                        self,
                        "Connection Timeout",
                        "Connection test timed out. Please check your network and credentials."
                    )

            except Exception as config_e:
                QMessageBox.warning(
                    self,
                    "Configuration Error",
                    f"Error configuring Azure Speech Services:\n{str(config_e)}"
                )
            finally:
                # Ensure temporary file is removed if it exists
                if temp_wav_path and os.path.exists(temp_wav_path):
                    try:
                        os.unlink(temp_wav_path)
                    except Exception as cleanup_e:
                        print(f"Could not remove temporary file: {cleanup_e}")

        except ImportError:
            QMessageBox.critical(
                self,
                "SDK Error",
                "Azure Speech SDK is not installed. Please install azure-cognitiveservices-speech."
            )
        except Exception as e:
            QMessageBox.warning(
                self,
                "Connection Test Error",
                f"An unexpected error occurred:\n{str(e)}"
            )

    def _load_settings(self):
        """Load settings from QSettings"""
        # General settings
        self.auto_close_check.setChecked(
            self.settings.value("auto_close", "true") == "true")
        self.auto_close_time_spin.setValue(
            int(self.settings.value("auto_close_time", "4")))

        # Analysis settings
        self.preview_duration_spin.setValue(
            int(self.settings.value("preview_duration", "10")))
        whole_signal = self.settings.value(
            "use_whole_signal", "true") == "true"
        self.whole_signal_check.setChecked(whole_signal)
        self.preview_duration_spin.setEnabled(not whole_signal)

        # Transcription settings
        self.enable_transcription_check.setChecked(
            self.settings.value("enable_transcription", "false") == "true")
        self.azure_key_edit.setText(self.settings.value("azure_key", ""))

        # Load transcription duration setting
        transcription_duration = self.settings.value(
            "transcription_duration", "preview")
        index = self.transcription_duration_combo.findData(
            transcription_duration)
        if index >= 0:
            self.transcription_duration_combo.setCurrentIndex(index)

        # Set region if stored
        region_index = self.azure_region_combo.findText(
            self.settings.value("azure_region", "eastus"))
        if region_index >= 0:
            self.azure_region_combo.setCurrentIndex(region_index)

        # Set language if stored
        language_index = self.language_combo.findData(
            self.settings.value("transcription_language", ""))
        if language_index >= 0:
            self.language_combo.setCurrentIndex(language_index)

        # Update transcription options enabled state
        self._toggle_transcription_options(
            Qt.Checked if self.enable_transcription_check.isChecked() else Qt.Unchecked)

        # Check if app is in startup
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_READ
            )
            try:
                winreg.QueryValueEx(key, "AudioTooltip")
                self.startup_check.setChecked(True)
            except FileNotFoundError:
                self.startup_check.setChecked(False)
            winreg.CloseKey(key)
        except Exception:
            # Default to checked if we can't read registry
            self.startup_check.setChecked(True)

    def _apply_settings(self):
        """Apply current settings to QSettings"""
        # General settings
        self.settings.setValue(
            "auto_close", "true" if self.auto_close_check.isChecked() else "false")
        self.settings.setValue("auto_close_time", str(
            self.auto_close_time_spin.value()))

        # Analysis settings
        self.settings.setValue("preview_duration", str(
            self.preview_duration_spin.value()))
        self.settings.setValue(
            "use_whole_signal", "true" if self.whole_signal_check.isChecked() else "false")

        # Transcription settings
        self.settings.setValue(
            "enable_transcription", "true" if self.enable_transcription_check.isChecked() else "false")
        self.settings.setValue("transcription_duration",
                               self.transcription_duration_combo.currentData())
        self.settings.setValue("azure_key", self.azure_key_edit.text())
        self.settings.setValue(
            "azure_region", self.azure_region_combo.currentText())
        self.settings.setValue("transcription_language",
                               self.language_combo.currentData())

        self.settings.sync()

    def accept(self):
        """Handle dialog acceptance"""
        self._apply_settings()
        super().accept()
