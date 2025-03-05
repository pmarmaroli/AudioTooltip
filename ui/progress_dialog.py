"""
Progress Dialog Module
---------------------
Provides a user-friendly progress dialog for long-running operations.
"""

from PyQt5.QtGui import QFont, QMovie, QPixmap
from PyQt5.QtCore import Qt, QSize, QTimer
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QSizePolicy
)


class ProgressDialog(QDialog):
    """
    Enhanced progress dialog with animated indicators.

    Features:
    - Animated loading indicator
    - Customizable messages
    - Optional cancel button
    - Automatic timeout option
    """

    def __init__(self, parent=None, title="Processing", message="Please wait...",
                 cancelable=False, auto_close=False, timeout=30000):
        """
        Initialize progress dialog.

        Args:
            parent: Parent widget
            title: Dialog title
            message: Initial progress message
            cancelable: Whether to show cancel button
            auto_close: Whether to auto-close after timeout
            timeout: Auto-close timeout in milliseconds
        """
        super().__init__(parent)

        # Set window properties
        self.setWindowTitle(title)
        self.setMinimumWidth(400)
        self.setWindowFlags(self.windowFlags() & ~
                            Qt.WindowContextHelpButtonHint)

        # Store configuration
        self.cancelable = cancelable
        self.auto_close = auto_close
        self.timeout = timeout

        # Initialize UI
        self._init_ui(message)

        # Set up auto-close if enabled
        if auto_close:
            self.close_timer = QTimer(self)
            self.close_timer.timeout.connect(self.accept)
            self.close_timer.start(timeout)

    def _init_ui(self, message):
        """Initialize dialog UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # Create spinner animation
        try:
            # Try to load spinner animation if available
            self.spinner = QMovie(":/resources/spinner.gif")
            if self.spinner.isValid():
                self.spinner.setScaledSize(QSize(32, 32))
                spinner_label = QLabel()
                spinner_label.setMovie(self.spinner)
                self.spinner.start()
                header_layout = QHBoxLayout()
                header_layout.addWidget(spinner_label)
                header_layout.addStretch(1)
                main_layout.addLayout(header_layout)
        except:
            # Fallback to simple layout without spinner
            pass

        # Message label
        self.message_label = QLabel(message)
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setWordWrap(True)
        self.message_label.setFont(QFont("Arial", 11))
        main_layout.addWidget(self.message_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMinimumHeight(10)
        main_layout.addWidget(self.progress_bar)

        # Cancel button (if cancelable)
        if self.cancelable:
            button_layout = QHBoxLayout()
            button_layout.addStretch(1)

            self.cancel_button = QPushButton("Cancel")
            self.cancel_button.clicked.connect(self.reject)
            button_layout.addWidget(self.cancel_button)

            main_layout.addLayout(button_layout)

    def update_message(self, message):
        """
        Update the progress message.

        Args:
            message: New message text
        """
        self.message_label.setText(message)

        # Reset auto-close timer if enabled
        if self.auto_close and hasattr(self, 'close_timer'):
            self.close_timer.stop()
            self.close_timer.start(self.timeout)

    def set_progress(self, value, maximum=100):
        """
        Set determinate progress value.

        Args:
            value: Current progress value
            maximum: Maximum progress value
        """
        # Switch to determinate mode if needed
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, maximum)
            self.progress_bar.setTextVisible(True)

        self.progress_bar.setMaximum(maximum)
        self.progress_bar.setValue(value)

    def reset_to_indeterminate(self):
        """Reset progress bar to indeterminate mode"""
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)

    def show_error(self, error_message):
        """
        Show error message and convert to closable dialog.

        Args:
            error_message: Error message to display
        """
        self.message_label.setText(f"Error: {error_message}")
        self.message_label.setStyleSheet("color: #cc0000;")

        # Stop animation if running
        if hasattr(self, 'spinner') and self.spinner.isValid():
            self.spinner.stop()

        # Stop progress animation
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        # Make dialog closable
        if not self.cancelable:
            button_layout = QHBoxLayout()
            button_layout.addStretch(1)

            close_button = QPushButton("Close")
            close_button.clicked.connect(self.reject)
            button_layout.addWidget(close_button)

            self.layout().addLayout(button_layout)
            self.cancelable = True

        # Stop auto-close timer if running
        if hasattr(self, 'close_timer') and self.close_timer.isActive():
            self.close_timer.stop()

    def closeEvent(self, event):
        """Handle close event"""
        # Stop animation if running
        if hasattr(self, 'spinner') and self.spinner.isValid():
            self.spinner.stop()

        # Stop timer if running
        if hasattr(self, 'close_timer') and self.close_timer.isActive():
            self.close_timer.stop()

        super().closeEvent(event)
