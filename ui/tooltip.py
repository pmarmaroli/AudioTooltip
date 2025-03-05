"""
Enhanced Tooltip Module
----------------------
Provides a customizable tooltip for displaying audio analysis results.
"""

import os
from PyQt5.QtGui import QPixmap, QFont, QIcon, QPainter, QColor, QPen, QCursor
from PyQt5.QtCore import Qt, QTimer, QSize, QPoint, QRect, QPropertyAnimation, QEasingCurve, QSettings
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTabWidget,
    QScrollArea, QFrame, QSizePolicy, QSpacerItem, QToolButton, QMenu, QGroupBox, QDialog, QMessageBox, QComboBox, QCheckBox
)


class EnhancedTooltip(QWidget):
    """
    Enhanced tooltip widget for displaying audio analysis results.

    Features:
    - Multi-tab interface for different data views
    - Animation effects
    - Audio preview controls
    - Auto-hide with configurable timer
    """

    def __init__(self, parent=None, settings=None):
        """Initialize the tooltip UI"""
        super().__init__(parent)

        # Set window properties - now using Dialog flag to enable dragging
        self.setWindowFlags(
            Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(self._get_stylesheet())

        # Store settings
        self.settings = settings

        # Initialize logger
        import logging
        self.logger = logging.getLogger("EnhancedTooltip")

        # Initialize variables
        self.auto_hide_timer = QTimer(self)
        self.auto_hide_timer.timeout.connect(self.hide_with_fade)
        self.auto_hide_seconds = 10
        self.pinned = False
        self.current_file = None
        self.animation = None
        self.audio_player = None
        self.on_settings_requested = None  # Callback for settings button
        self.current_channel = 0
        self.num_channels = 1
        self.on_channel_changed = None  # Callback for channel change
        self.on_visualization_requested = None  # Callback for visualization requests
        self.on_transcription_requested = None  # Callback for transcription requests
        self.on_refresh_requested = None  # Callback for refresh button

        # Initialize UI
        self._init_ui()

        self.setFixedSize(600, 800)

    def _init_ui(self):
        """Initialize UI components"""
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(5)

        # Title bar
        title_layout = self._create_title_bar()
        main_layout.addLayout(title_layout)

        # Tab widget
        self.tab_widget = QTabWidget(self)
        self.tab_widget.setTabPosition(QTabWidget.North)
        self.tab_widget.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Create tabs
        self.overview_tab = self._create_overview_tab()
        self.visualizations_tab = self._create_visualizations_tab()
        self.transcript_tab = self._create_transcript_tab()

        # Add tabs to widget
        self.tab_widget.addTab(self.overview_tab, "Overview")
        self.tab_widget.addTab(self.visualizations_tab, "Visualizations")
        self.tab_widget.addTab(self.transcript_tab, "Transcript")

        main_layout.addWidget(self.tab_widget)

        # Action buttons
        action_layout = self._create_action_buttons()
        main_layout.addLayout(action_layout)

    def _create_title_bar(self):
        """Create custom title bar with controls and channel selection"""
        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 5)

        # Create a grabable title bar area - more obvious to show it's draggable
        drag_handle = QLabel("≡  ")  # Three horizontal lines
        drag_handle.setToolTip("Drag to move")
        drag_handle.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #666;")
        # Change cursor to indicate draggable
        drag_handle.setCursor(Qt.SizeAllCursor)

        # Title label
        self.title_label = QLabel("Audio Analysis")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        # Make title label draggable too
        self.title_label.setCursor(Qt.SizeAllCursor)

        # Channel selector
        channel_layout = QHBoxLayout()
        channel_label = QLabel("Channel:")
        self.channel_combo = QComboBox()
        self.channel_combo.addItem("Mono/Left (1)", 0)
        self.channel_combo.currentIndexChanged.connect(
            self._on_channel_changed)
        self.channel_combo.setEnabled(False)  # Disabled by default

        channel_layout.addWidget(channel_label)
        channel_layout.addWidget(self.channel_combo)

        # Control buttons - ensure they have proper icons and are visible
        self.pin_button = QToolButton(self)
        self.pin_button.setIcon(QIcon.fromTheme(
            "pin", QIcon(":/resources/icons/pin.png")))  # Fallback to embedded resource
        self.pin_button.setToolTip("Pin tooltip (prevent auto-hide)")
        self.pin_button.setCheckable(True)
        self.pin_button.clicked.connect(self._toggle_pin)
        self.pin_button.setFixedSize(24, 24)  # Explicit size

        settings_button = QToolButton(self)
        settings_button.setIcon(QIcon.fromTheme(
            "configure", QIcon(":/resources/icons/configure.png")))
        settings_button.setToolTip("Settings")
        settings_button.clicked.connect(self._on_settings_clicked)
        settings_button.setFixedSize(24, 24)  # Explicit size

        # Explicitly set close button with standard icon
        close_button = QToolButton(self)
        close_button.setIcon(QIcon.fromTheme(
            "window-close", QIcon(":/resources/icons/close.png")))
        if close_button.icon().isNull():  # If icon loading failed, create a text button
            close_button.setText("✕")  # Use unicode X as fallback
            close_button.setStyleSheet("font-weight: bold; color: #CC0000;")

        close_button.setToolTip("Close")
        close_button.clicked.connect(self.hide_with_fade)
        close_button.setFixedSize(24, 24)  # Explicit size

        # Add to layout
        title_layout.addWidget(drag_handle)
        # Stretch factor to fill space
        title_layout.addWidget(self.title_label, 1)
        title_layout.addLayout(channel_layout)
        title_layout.addWidget(self.pin_button)
        title_layout.addWidget(settings_button)
        title_layout.addWidget(close_button)

        # We need to store the drag position for mouseMoveEvent
        self.drag_position = None

        return title_layout

    def force_hide(self):
        """Immediately hide the tooltip without fade animation"""
        # Stop any running timers
        if self.auto_hide_timer.isActive():
            self.auto_hide_timer.stop()

        # Reset pin state
        self.pin_button.setChecked(False)
        self.pinned = False

        # Hide without animation
        self.hide()

    def _refresh_analysis(self):
        """Force a refresh of the current audio analysis"""
        if not self.current_file or not hasattr(self, 'on_refresh_requested') or not self.on_refresh_requested:
            return

        # Call the refresh callback with the current file and channel
        self.on_refresh_requested(self.current_file, self.current_channel)

    def _create_action_buttons(self):
        """Create action buttons for audio preview and control"""
        action_layout = QHBoxLayout()

        # Play preview button
        self.play_button = QPushButton("Play Preview")
        self.play_button.setIcon(QIcon.fromTheme(
            "media-playback-start", QIcon.fromTheme("play")))
        self.play_button.clicked.connect(self._play_preview)

        # Add Refresh button
        refresh_button = QPushButton("Refresh Analysis")
        refresh_button.setIcon(QIcon.fromTheme(
            "view-refresh", QIcon.fromTheme("refresh")))
        refresh_button.clicked.connect(self._refresh_analysis)
        refresh_button.setToolTip("Reload analysis after file changes")

        # Open in Audacity button
        audacity_button = QPushButton("Open in Audacity")
        audacity_button.setIcon(QIcon.fromTheme(
            "audio-x-generic", QIcon.fromTheme("folder-open")))
        audacity_button.clicked.connect(self._open_in_audacity)

        # Save all button
        save_button = QPushButton("Save All")
        save_button.setIcon(QIcon.fromTheme(
            "document-save", QIcon.fromTheme("save")))
        save_button.clicked.connect(self._save_all)

        action_layout.addWidget(self.play_button)
        action_layout.addWidget(refresh_button)
        action_layout.addWidget(audacity_button)
        action_layout.addWidget(save_button)

        return action_layout

    def _open_in_audacity(self):
        """Open the audio file in Audacity"""
        if not self.current_file:
            return

        try:
            # Try to find Audacity executable
            audacity_path = None
            import subprocess

            if os.name == 'nt':  # Windows
                # Common installation paths for Audacity on Windows
                possible_paths = [
                    os.path.join(os.environ.get(
                        'ProgramFiles', r'C:\Program Files'), 'Audacity', 'Audacity.exe'),
                    os.path.join(os.environ.get(
                        'ProgramFiles(x86)', r'C:\Program Files (x86)'), 'Audacity', 'Audacity.exe'),
                    r'C:\Program Files\Audacity\Audacity.exe',
                    r'C:\Program Files (x86)\Audacity\Audacity.exe'
                ]

                for path in possible_paths:
                    if os.path.exists(path):
                        audacity_path = path
                        break

            elif os.name == 'posix':  # macOS, Linux
                if os.uname().sysname == 'Darwin':  # macOS
                    audacity_path = '/Applications/Audacity.app/Contents/MacOS/Audacity'
                else:  # Linux
                    # Try to find using which command
                    try:
                        audacity_path = subprocess.check_output(
                            ['which', 'audacity']).decode().strip()
                    except:
                        # Common Linux paths
                        possible_paths = [
                            '/usr/bin/audacity',
                            '/usr/local/bin/audacity'
                        ]
                        for path in possible_paths:
                            if os.path.exists(path):
                                audacity_path = path
                                break

            if audacity_path and os.path.exists(audacity_path):
                # Launch Audacity with the file
                if os.name == 'nt':  # Windows
                    subprocess.Popen([audacity_path, self.current_file])
                else:  # macOS, Linux
                    subprocess.Popen([audacity_path, self.current_file])
            else:
                # Fallback to system default if Audacity isn't found
                if os.name == 'nt':  # Windows
                    # This takes a single string
                    os.startfile(self.current_file)
                elif os.name == 'posix':  # macOS, Linux
                    if os.uname().sysname == 'Darwin':  # macOS
                        subprocess.Popen(['open', self.current_file])
                    else:  # Linux
                        subprocess.Popen(['xdg-open', self.current_file])

        except Exception as e:
            QMessageBox.warning(
                self,
                "Open Failed",
                f"Could not open the file in Audacity: {str(e)}\n\nMake sure Audacity is installed on your system."
            )

    def _run_visualization(self):
        """Run the currently selected visualization"""
        viz_type = self.viz_combo_menu.text()
        if hasattr(self, 'on_visualization_requested'):
            self.on_visualization_requested(viz_type, self.current_channel)

    def _expand_visualization(self):
        """Show expanded view of current visualization (at least 3x larger)"""
        if not self.viz_display.pixmap() or self.viz_display.pixmap().isNull():
            return

        # Create popup window
        popup = QDialog(self)
        popup.setWindowTitle(f"Expanded {self.viz_combo_menu.text()}")
        popup.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint)

        # Calculate size - at least 3x larger than original display
        orig_width = self.viz_display.pixmap().width()
        orig_height = self.viz_display.pixmap().height()
        # At least 3x wider, minimum 1200px
        expanded_width = max(orig_width * 3, 1200)
        # At least 3x taller, minimum 900px
        expanded_height = max(orig_height * 3, 900)

        popup.setMinimumSize(expanded_width, expanded_height)

        layout = QVBoxLayout(popup)

        # Create label with expanded image
        image_label = QLabel()
        image_label.setAlignment(Qt.AlignCenter)

        # Scale the image to at least 3x its original size, maintaining aspect ratio
        expanded_pixmap = self.viz_display.pixmap().scaled(
            expanded_width,
            expanded_height,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        image_label.setPixmap(expanded_pixmap)

        # Add a scroll area for large images
        scroll = QScrollArea()
        scroll.setWidget(image_label)
        scroll.setWidgetResizable(True)

        layout.addWidget(scroll)

        # Add close button
        button = QPushButton("Close")
        button.clicked.connect(popup.accept)
        layout.addWidget(button)

        popup.exec_()

    def _save_all(self):
        """Save all analysis results to files"""
        if not self.current_file:
            return

        # Get directory and base name
        directory = os.path.dirname(self.current_file)
        base_name = os.path.splitext(os.path.basename(self.current_file))[0]
        channel_suffix = f"_ch{self.current_channel+1}" if self.num_channels > 1 else ""

        # List of items to save
        items_saved = []

        # Save metadata and features text
        if self.metadata_label.text() and self.metadata_label.text() != "No metadata available":
            metadata_path = os.path.join(
                directory, f"{base_name}{channel_suffix}_metadata.txt")
            try:
                with open(metadata_path, 'w') as f:
                    f.write(self.metadata_label.text())
                items_saved.append(
                    f"Metadata: {os.path.basename(metadata_path)}")
            except Exception as e:
                self.logger.error(f"Error saving metadata: {e}")

        # Save transcript
        if self.transcript_text.text() and self.transcript_text.text() != "No transcription available":
            transcript_path = os.path.join(
                directory, f"{base_name}_transcript.txt")
            try:
                with open(transcript_path, 'w') as f:
                    f.write(self.transcript_text.text())
                items_saved.append(
                    f"Transcript: {os.path.basename(transcript_path)}")
            except Exception as e:
                self.logger.error(f"Error saving transcript: {e}")

        # Save waveform image
        if self.waveform_label.pixmap() and not self.waveform_label.pixmap().isNull():
            waveform_path = os.path.join(
                directory, f"{base_name}{channel_suffix}_waveform.png")
            try:
                self.waveform_label.pixmap().save(waveform_path)
                items_saved.append(
                    f"Waveform: {os.path.basename(waveform_path)}")
            except Exception as e:
                self.logger.error(f"Error saving waveform: {e}")

        # Save visualization image
        if self.viz_display.pixmap() and not self.viz_display.pixmap().isNull():
            viz_type = self.viz_combo_menu.text().lower().replace('-', '_')
            viz_path = os.path.join(
                directory, f"{base_name}{channel_suffix}_{viz_type}.png")
            try:
                self.viz_display.pixmap().save(viz_path)
                items_saved.append(
                    f"{self.viz_combo_menu.text()}: {os.path.basename(viz_path)}")
            except Exception as e:
                self.logger.error(f"Error saving visualization: {e}")

        # Show confirmation message
        if items_saved:
            QMessageBox.information(
                self,
                "Files Saved",
                f"The following files were saved in {directory}:\n\n" + "\n".join(
                    items_saved)
            )
        else:
            QMessageBox.warning(
                self,
                "Nothing to Save",
                "No content available to save."
            )

    def _create_title_bar(self):
        """Create custom title bar with controls and channel selection"""
        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(5, 5, 5, 5)  # Add more margin space

        # Drag handle with clearer styling
        drag_handle = QLabel("≡")
        drag_handle.setStyleSheet("""
            font-size: 18px; 
            font-weight: bold; 
            color: #555;
            padding: 2px 5px;
            background-color: rgba(200, 200, 200, 80);
            border-radius: 3px;
        """)
        drag_handle.setToolTip("Drag to move")
        drag_handle.setCursor(Qt.SizeAllCursor)

        # Title label
        self.title_label = QLabel("Audio Analysis")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 14px;")

        # Create an explicit text-based close button with clear styling
        close_button = QPushButton("✕")  # Using text instead of icon
        close_button.setToolTip("Close")
        close_button.clicked.connect(self.hide_with_fade)
        close_button.setFixedSize(28, 28)
        close_button.setStyleSheet("""
            QPushButton {
                font-weight: bold;
                color: #CC0000;
                background-color: rgba(200, 200, 200, 120);
                border-radius: 3px;
                padding: 3px;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: rgba(255, 200, 200, 150);
            }
        """)

        # Pin button as a text button
        self.pin_button = QPushButton("📌")  # Pin emoji
        self.pin_button.setToolTip("Pin tooltip (prevent auto-hide)")
        self.pin_button.setCheckable(True)
        self.pin_button.clicked.connect(self._toggle_pin)
        self.pin_button.setFixedSize(28, 28)
        self.pin_button.setStyleSheet("""
            QPushButton {
                font-weight: bold;
                background-color: rgba(200, 200, 200, 120);
                border-radius: 3px;
                padding: 3px;
                font-size: 14px;
            }
            QPushButton:checked {
                background-color: rgba(200, 255, 200, 150);
            }
        """)

        # Settings button as a text button
        settings_button = QPushButton("⚙")  # Gear emoji
        settings_button.setToolTip("Settings")
        settings_button.clicked.connect(self._on_settings_clicked)
        settings_button.setFixedSize(28, 28)
        settings_button.setStyleSheet("""
            QPushButton {
                font-weight: bold;
                background-color: rgba(200, 200, 200, 120);
                border-radius: 3px;
                padding: 3px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(200, 200, 255, 150);
            }
        """)

        # Add to layout with spacing
        title_layout.addWidget(drag_handle)
        title_layout.addSpacing(5)
        title_layout.addWidget(self.title_label, 1)
        title_layout.addSpacing(5)
        title_layout.addWidget(self.pin_button)
        title_layout.addWidget(settings_button)
        title_layout.addWidget(close_button)

        # Store drag position
        self.drag_position = None

        return title_layout

    def _on_channel_changed(self, index):
        """Handle channel selection change"""
        new_channel = self.channel_combo.currentData()
        if new_channel is None:
            self.logger.warning(
                "Channel selection returned None, defaulting to channel 0")
            new_channel = 0

        if new_channel != self.current_channel and self.on_channel_changed:
            self.current_channel = new_channel
            self.on_channel_changed(new_channel)

    def update_channels(self, num_channels, current_channel=0):
        """Update channel selector based on available channels"""
        if num_channels <= 1:
            self.channel_combo.setEnabled(False)
            self.channel_combo.clear()
            self.channel_combo.addItem("Mono/Left (1)", 0)
            self.current_channel = 0
            self.num_channels = 1
            return

        # Save current state
        was_blocked = self.channel_combo.blockSignals(True)

        # Update combobox
        self.channel_combo.clear()
        for i in range(num_channels):
            channel_name = "Left" if i == 0 else "Right" if i == 1 else f"Channel {i+1}"
            self.channel_combo.addItem(f"{channel_name} ({i+1})", i)

        # Set current channel
        index = self.channel_combo.findData(current_channel)
        if index >= 0:
            self.channel_combo.setCurrentIndex(index)

        # Update state
        self.current_channel = current_channel
        self.num_channels = num_channels
        self.channel_combo.setEnabled(True)

        # Restore signal blocking state
        self.channel_combo.blockSignals(was_blocked)

    # In ui/tooltip.py, update the _create_overview_tab method
    def _create_overview_tab(self):
        """Create the overview tab with basic file info, channel selector, and waveform"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)  # Minimal margins
        layout.setSpacing(0)  # Remove spacing between elements

        # Channel selector - moved from title bar to here
        channel_selector = QFrame()
        channel_selector.setFrameShape(QFrame.StyledPanel)
        channel_selector.setStyleSheet(
            "background-color: rgba(230, 230, 250, 200);")
        channel_layout = QHBoxLayout(channel_selector)
        channel_layout.setContentsMargins(10, 8, 10, 8)

        channel_label = QLabel("Channel:")
        channel_label.setStyleSheet("font-weight: bold;")

        self.channel_combo = QComboBox()
        self.channel_combo.addItem("Mono/Left (1)", 0)
        self.channel_combo.currentIndexChanged.connect(
            self._on_channel_changed)
        self.channel_combo.setEnabled(False)  # Disabled by default

        channel_layout.addWidget(channel_label)
        channel_layout.addWidget(self.channel_combo)
        channel_layout.addStretch(1)  # Push selector to the left

        # File info frame
        info_frame = QFrame()
        info_frame.setFrameShape(QFrame.StyledPanel)
        info_frame.setStyleSheet("background-color: rgba(240, 240, 240, 200);")
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(10, 10, 10, 10)
        info_layout.setSpacing(5)

        self.file_name_label = QLabel("File: ")
        self.file_name_label.setWordWrap(True)
        self.file_name_label.setStyleSheet("font-weight: bold;")

        self.metadata_label = QLabel("Loading metadata...")
        self.metadata_label.setWordWrap(True)
        self.metadata_label.setStyleSheet("color: #333; font-size: 10pt;")
        self.metadata_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        # Force a reasonable minimum height for the metadata section
        # Ensure it has space for all metadata
        self.metadata_label.setMinimumHeight(200)

        info_layout.addWidget(self.file_name_label)
        info_layout.addWidget(self.metadata_label)

        # Waveform container - remove padding
        waveform_container = QFrame()
        waveform_container.setStyleSheet(
            "background-color: rgba(220, 220, 220, 150);")
        waveform_container.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding)

        waveform_layout = QVBoxLayout(waveform_container)
        waveform_layout.setContentsMargins(0, 0, 0, 0)  # Remove all margins
        waveform_layout.setSpacing(0)  # Remove spacing

        self.waveform_label = QLabel()
        self.waveform_label.setAlignment(Qt.AlignCenter)
        self.waveform_label.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding)

        waveform_layout.addWidget(self.waveform_label)

        # Add elements to the main layout
        # Channel selector at the top with no stretch
        layout.addWidget(channel_selector, 0)
        layout.addWidget(info_frame, 4)        # Info frame with good stretch
        # Waveform with slightly more stretch
        layout.addWidget(waveform_container, 5)

        return widget

    def _create_visualizations_tab(self):
        """Create visualizations tab with spectrogram and other views"""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)

        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Visualization selector with Run button
        viz_selector = QHBoxLayout()
        viz_label = QLabel("View:")

        self.viz_combo_menu = QToolButton()
        self.viz_combo_menu.setText("Spectrogram")
        self.viz_combo_menu.setPopupMode(QToolButton.InstantPopup)
        self.viz_combo_menu.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.viz_combo_menu.setArrowType(Qt.DownArrow)

        menu = QMenu(self.viz_combo_menu)
        # Add Waveform as the first option
        for viz_type in ["Waveform", "Double Waveform", "Spectrogram", "Mel-Spectrogram", "Chromagram"]:
            action = menu.addAction(viz_type)
            action.triggered.connect(
                lambda checked, vt=viz_type: self._change_visualization(vt))

        self.viz_combo_menu.setMenu(menu)

        # Run button
        self.viz_run_button = QPushButton("Run")
        self.viz_run_button.setIcon(QIcon.fromTheme(
            "system-run", QIcon.fromTheme("media-playback-start")))
        self.viz_run_button.clicked.connect(self._run_visualization)

        # Expand view button
        self.viz_expand_button = QPushButton("Expand")
        self.viz_expand_button.setIcon(QIcon.fromTheme(
            "zoom-fit-best", QIcon.fromTheme("zoom-in")))
        self.viz_expand_button.clicked.connect(self._expand_visualization)

        viz_selector.addWidget(viz_label)
        viz_selector.addWidget(self.viz_combo_menu)
        viz_selector.addWidget(self.viz_run_button)
        viz_selector.addWidget(self.viz_expand_button)
        viz_selector.addStretch(1)

        # Visualization display
        self.viz_display = QLabel()
        self.viz_display.setAlignment(Qt.AlignCenter)
        self.viz_display.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.viz_display.setMinimumHeight(250)
        self.viz_display.setStyleSheet(
            "background-color: rgba(220, 220, 220, 150);")

        # Description label
        self.viz_description = QLabel()
        self.viz_description.setWordWrap(True)
        self.viz_description.setStyleSheet("font-style: italic; color: #555;")

        # Preview info label
        self.viz_preview_info = QLabel()
        self.viz_preview_info.setWordWrap(True)
        self.viz_preview_info.setStyleSheet(
            "font-style: italic; color: #555; margin-top: 5px;")
        self.viz_preview_info.setText(
            "Visualization shows only preview duration. Set preview options in Settings.")

        # Add components to layout
        layout.addLayout(viz_selector)
        layout.addWidget(self.viz_display)
        layout.addWidget(self.viz_description)
        layout.addWidget(self.viz_preview_info)

        scroll_area.setWidget(widget)
        return scroll_area

    def _create_transcript_tab(self):
        """Create transcript tab for speech-to-text results"""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)

        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Add button bar at the top
        button_layout = QVBoxLayout()

        # Run transcription button
        self.run_transcribe_button = QPushButton("Run Transcription")
        self.run_transcribe_button.setIcon(QIcon.fromTheme(
            "system-run", QIcon.fromTheme("media-playback-start")))
        self.run_transcribe_button.clicked.connect(self._run_transcription)

        # Choose language dropdown
        language_layout = QHBoxLayout()
        language_label = QLabel("Language:")
        self.language_combo = QComboBox()

        # Add channel selector dropdown
        channel_layout = QHBoxLayout()
        channel_label = QLabel("Channel:")
        self.transcription_channel_combo = QComboBox()

        button_layout.addWidget(self.run_transcribe_button)
        button_layout.addLayout(language_layout)
        button_layout.addLayout(channel_layout)
        button_layout.addStretch()

        # Create a scrollable text display for the transcript
        self.transcript_text = QLabel(
            "Transcription is not available.\n\n"
            "To enable transcription:\n"
            "1. Open Settings\n"
            "2. Go to Transcription tab\n"
            "3. Enable transcription and configure Azure credentials")
        self.transcript_text.setWordWrap(True)
        self.transcript_text.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.transcript_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.transcript_text.setStyleSheet("color: #666; font-style: italic;")

        # Add a "View in Text Editor" button
        self.view_transcript_button = QPushButton(
            "View Full Transcript in Text Editor")
        self.view_transcript_button.setIcon(QIcon.fromTheme(
            "document-open", QIcon.fromTheme("text-editor")))
        self.view_transcript_button.clicked.connect(self._open_transcript_file)
        self.view_transcript_button.setEnabled(False)  # Initially disabled

        # Add settings button
        improve_button = QPushButton("Transcription Settings...")
        improve_button.setIcon(QIcon.fromTheme(
            "edit", QIcon.fromTheme("accessories-text-editor")))
        improve_button.clicked.connect(self._show_transcription_settings)

        layout.addLayout(button_layout)
        layout.addWidget(self.transcript_text)
        layout.addWidget(self.view_transcript_button)
        layout.addWidget(improve_button)
        layout.addStretch(1)

        scroll_area.setWidget(widget)
        return scroll_area

    # Add method to open transcript file
    def _open_transcript_file(self):
        """Open the transcription file in default text editor"""
        if hasattr(self, 'transcript_file_path') and os.path.exists(self.transcript_file_path):
            try:
                if os.name == 'nt':  # Windows
                    os.startfile(self.transcript_file_path)
                elif os.name == 'posix':  # macOS, Linux
                    if os.uname().sysname == 'Darwin':  # macOS
                        subprocess.Popen(['open', self.transcript_file_path])
                    else:  # Linux
                        subprocess.Popen(
                            ['xdg-open', self.transcript_file_path])
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Error",
                    f"Could not open transcript file: {str(e)}"
                )
        else:
            QMessageBox.information(
                self,
                "No Transcript File",
                "No transcript file has been saved yet. Run transcription first."
            )

    def _run_transcription(self):
        """Run speech-to-text transcription on the current file"""
        if not self.current_file or not hasattr(self, 'on_transcription_requested'):
            return

        # Get selected language
        language = self.language_combo.currentData()

        # Get selected channel
        selected_channel = self.transcription_channel_combo.currentData()

        # If "Current Channel" is selected, use the current channel
        if selected_channel == -2:
            selected_channel = self.current_channel

        # Notify the main application to run transcription
        if hasattr(self, 'on_transcription_requested'):
            self.on_transcription_requested(
                self.current_file, self.current_channel, language, selected_channel)

    def update_transcription_channels(self, num_channels):
        """Update the channel selector dropdown based on the number of channels"""
        # Save current selection
        current_selection = self.transcription_channel_combo.currentData()

        # Clear channel-specific options (keep Mono Mix and Current Channel)
        while self.transcription_channel_combo.count() > 2:
            self.transcription_channel_combo.removeItem(2)

        # Add individual channels
        for i in range(num_channels):
            channel_name = "Left" if i == 0 else "Right" if i == 1 else f"Channel {i+1}"
            self.transcription_channel_combo.addItem(f"{channel_name}", i)

        # Try to restore previous selection if it's still valid
        if current_selection is not None:
            index = self.transcription_channel_combo.findData(
                current_selection)
            if index >= 0:
                self.transcription_channel_combo.setCurrentIndex(index)

    def update_channel_delay(self, delay_ms=None):
        """Display channel delay with consistent visibility and matching font style"""
        # Create the delay label if it doesn't exist
        if not hasattr(self, 'delay_label'):
            self.delay_label = QLabel()
            # Find the info frame in the overview tab
            info_frame = None
            for i in range(self.overview_tab.layout().count()):
                widget = self.overview_tab.layout().itemAt(i).widget()
                if isinstance(widget, QFrame) and widget.styleSheet().find("background-color: rgba(240, 240, 240, 200)") >= 0:
                    info_frame = widget
                    break

            if info_frame and info_frame.layout():
                # Add the delay label to the info frame's layout
                info_frame.layout().addWidget(self.delay_label)

        # Base style that matches the metadata label (font-size: 10pt)
        base_style = """
            font-size: 10pt;
            padding: 2px 5px;
            border-radius: 3px;
            margin-top: 8px;
        """

        # Always show the label with appropriate text and style
        if self.num_channels > 1:
            if delay_ms is not None and abs(delay_ms) > 0.01:
                direction = "right→left" if delay_ms > 0 else "left→right"
                self.delay_label.setText(
                    f"Time Delay: {abs(delay_ms):.2f} ms ({direction})")
                self.delay_label.setStyleSheet(f"""
                    color: #006600;
                    font-weight: bold;
                    {base_style}
                """)
            else:
                self.delay_label.setText("Time Delay: not detected")
                self.delay_label.setStyleSheet(f"""
                    color: #666666;
                    font-style: italic;
                    {base_style}
                """)
        else:
            self.delay_label.setText("Time Delay: N/A (mono audio)")
            self.delay_label.setStyleSheet(f"""
                color: #666666;
                font-style: italic;
                {base_style}
            """)

        # Ensure it's visible
        self.delay_label.setVisible(True)

    def update_content(self, file_path, metadata, viz_buffer, transcription, num_channels=1, current_channel=0, delay_ms=None):
        """Update the tooltip content with analysis results."""
        self.current_file = file_path

        # Update channels
        self.update_channels(num_channels, current_channel)

        # Update transcription channels dropdown
        self.update_transcription_channels(num_channels)

        # Update title and file name
        file_name = os.path.basename(file_path)
        self.title_label.setText(f"Audio Analysis: {file_name}")
        self.file_name_label.setText(f"File: {file_path}")

        # Update metadata
        if metadata:
            self.metadata_label.setText(metadata)
        else:
            self.metadata_label.setText("No metadata available")

        # Update waveform on overview tab
        if viz_buffer:
            pixmap = QPixmap()
            pixmap.loadFromData(viz_buffer.getvalue())

            # Calculate available width and scale appropriately
            available_width = self.waveform_label.width()
            scaled_pixmap = pixmap.scaledToWidth(
                available_width,
                Qt.SmoothTransformation
            )

            # Set the pixmap and center it
            self.waveform_label.setPixmap(scaled_pixmap)
            self.waveform_label.setAlignment(Qt.AlignCenter)
        else:
            self.waveform_label.setText("No waveform available")

        # Update transcript
        self.tab_widget.setTabEnabled(3, True)  # Enable transcript tab

        # Update preview info with settings
        if self.settings:
            use_whole_signal = self.settings.value(
                "use_whole_signal", "false") == "true"
            preview_duration = "entire signal" if use_whole_signal else f"{self.settings.value('preview_duration', '10')} seconds"
        else:
            # Fallback if settings not available
            preview_duration = "10 seconds"

        preview_info = f"Analysis is based on first {preview_duration} of channel {current_channel+1}/{num_channels}"
        self.viz_preview_info.setText(preview_info)

        self.update_channel_delay(delay_ms)

    def _toggle_pin(self, checked):
        """Toggle pinned state"""
        self.pinned = checked
        if checked:
            if self.auto_hide_timer.isActive():
                self.auto_hide_timer.stop()
        else:
            self.reset_auto_hide_timer()

    def reset_auto_hide_timer(self):
        """Reset the auto-hide timer"""
        if self.pinned:
            return

        if self.auto_hide_timer.isActive():
            self.auto_hide_timer.stop()

        self.auto_hide_timer.start(self.auto_hide_seconds * 1000)

    def show_with_fade(self):
        """Show the tooltip with fade-in animation"""
        # Stop any existing animation
        if self.animation:
            self.animation.stop()

        # Create opacity animation
        self.setWindowOpacity(0.0)
        self.show()

        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(300)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.InOutQuad)
        self.animation.start()

        # Start auto-hide timer
        self.reset_auto_hide_timer()

    def hide_with_fade(self):
        """Hide the tooltip with fade-out animation"""
        # Stop existing animations or timers
        if self.animation:
            self.animation.stop()

        if self.auto_hide_timer.isActive():
            self.auto_hide_timer.stop()

        # Create fade-out animation
        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(300)
        self.animation.setStartValue(self.windowOpacity())
        self.animation.setEndValue(0.0)
        self.animation.setEasingCurve(QEasingCurve.InOutQuad)
        self.animation.finished.connect(self.hide)
        self.animation.start()

    def _play_preview(self):
        """Play audio preview"""
        if not self.current_file or not self.audio_player:
            return

        # Create and play preview clip
        preview_path = self.audio_player.create_temp_clip(self.current_file)
        if preview_path:
            self.audio_player.play_audio(preview_path)

        # Reset timer when preview is played
        self.reset_auto_hide_timer()

    def _open_in_player(self):
        """Open the full audio file in default player"""
        if not self.current_file or not self.audio_player:
            return

        self.audio_player.play_audio(self.current_file)

    def _on_settings_clicked(self):
        """Handle settings button click"""
        if self.on_settings_requested:
            self.on_settings_requested()

    def _change_visualization(self, viz_type):
        """Change the current visualization type"""
        self.viz_combo_menu.setText(viz_type)

        # Update description based on visualization type
        descriptions = {
            "Waveform": "Shows amplitude changes over time. Useful for visualizing volume, silences, and transients.",
            "Double Waveform": "Displays stereo channels on a single graph. Left channel (red) shown in positive values, right channel (blue) in negative values. Only available for stereo files.",
            "Spectrogram": "Shows how frequency content changes over time. Brighter colors indicate higher energy.",
            "Mel-Spectrogram": "Similar to spectrogram but uses the Mel scale which better matches human hearing.",
            "Chromagram": "Displays harmonic content by pitch class, helpful for key detection.",
        }

        self.viz_description.setText(descriptions.get(viz_type, ""))

    def _show_transcription_settings(self):
        """Show transcription settings"""
        if self.on_settings_requested:
            self.on_settings_requested("transcription")

    def _get_stylesheet(self):
        """Get the stylesheet for the tooltip"""
        return """
        EnhancedTooltip {
            background-color: rgba(245, 245, 245, 235);
            border: 1px solid rgba(200, 200, 200, 220);
            border-radius: 10px;
        }
        QTabWidget::pane {
            border: 1px solid #ccc;
            border-radius: 4px;
            background-color: rgba(255, 255, 255, 180);
        }
        QTabBar::tab {
            padding: 6px 12px;
            background-color: rgba(230, 230, 230, 200);
            border: 1px solid #ccc;
            border-bottom: none;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
            margin-right: 2px;
        }
        QTabBar::tab:selected {
            background-color: rgba(255, 255, 255, 220);
            border-bottom: 1px solid white;
        }
        QPushButton {
            padding: 6px;
            border-radius: 4px;
            background-color: rgba(240, 240, 240, 220);
            border: 1px solid #ccc;
        }
        QPushButton:hover {
            background-color: rgba(230, 230, 230, 250);
        }
        QToolButton {
            border-radius: 4px;
            padding: 3px;
            background-color: transparent;
        }
        QToolButton:hover {
            background-color: rgba(200, 200, 200, 100);
        }
        QGroupBox {
            border: 1px solid #ccc;
            border-radius: 6px;
            margin-top: 6px;
            padding-top: 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px;
        }
        QComboBox {
            border: 1px solid #ccc;
            border-radius: 3px;
            padding: 1px 18px 1px 3px;
            min-width: 6em;
        }
        QComboBox::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 15px;
            border-left-width: 1px;
            border-left-color: #ccc;
            border-left-style: solid;
            border-top-right-radius: 3px;
            border-bottom-right-radius: 3px;
        }
        """

    def mousePressEvent(self, event):
        """Handle mouse press for dragging"""
        if event.button() == Qt.LeftButton:
            # Enable drag if clicking in the title bar area
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Handle mouse move for dragging"""
        if event.buttons() & Qt.LeftButton and self.drag_position is not None:
            self.move(event.globalPos() - self.drag_position)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Handle mouse release after dragging"""
        self.drag_position = None
        super().mouseReleaseEvent(event)

    # Override events

    def resizeEvent(self, event):
        """Handle resize event to update visualizations while maintaining aspect ratio"""
        super().resizeEvent(event)

        # Resize waveform to fit width while preserving aspect ratio
        if hasattr(self, 'waveform_label') and self.waveform_label.pixmap() and not self.waveform_label.pixmap().isNull():
            original_pixmap = self.waveform_label.pixmap()

            # Get available width
            available_width = self.waveform_label.width()

            # Scale to width while preserving aspect ratio
            scaled_pixmap = original_pixmap.scaledToWidth(
                available_width,
                Qt.SmoothTransformation
            )

            # Center the scaled pixmap
            self.waveform_label.setPixmap(scaled_pixmap)
            self.waveform_label.setAlignment(Qt.AlignCenter)

    def enterEvent(self, event):
        """Handle mouse enter event"""
        super().enterEvent(event)

        # Stop auto-hide timer when mouse enters
        if self.auto_hide_timer.isActive():
            self.auto_hide_timer.stop()

    def leaveEvent(self, event):
        """Handle mouse leave event"""
        super().leaveEvent(event)

        # Restart auto-hide timer when mouse leaves
        self.reset_auto_hide_timer()
