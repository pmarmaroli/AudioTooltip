"""
Logging Utilities Module
-----------------------
Provides centralized logging configuration with rotation and custom formatting.
"""

import os
import sys
import logging
import logging.handlers
import traceback
from pathlib import Path
from typing import Optional, Dict, Any, Union


def setup_logging(
    log_dir: Optional[str] = None,
    log_level: int = logging.INFO,
    max_size: int = 5 * 1024 * 1024,  # 5MB
    backup_count: int = 5,
    console_output: bool = True,
    module_levels: Optional[Dict[str, int]] = None
) -> logging.Logger:
    """
    Configure application logging with rotating file handler and optional console output.

    Args:
        log_dir: Directory for log files (uses ~/AppData/AudioTooltip_Logs on Windows, 
                 ~/.local/share/AudioTooltip_Logs on Linux/Mac if None)
        log_level: Root logger level
        max_size: Maximum log file size before rotation
        backup_count: Number of backup log files to keep
        console_output: Whether to output logs to console
        module_levels: Dict of module names to custom log levels

    Returns:
        Root logger instance
    """
    # Set up log directory
    if log_dir is None:
        if os.name == 'nt':  # Windows
            base_dir = os.path.expanduser("~\\AppData\\Local")
        else:  # Linux/Mac
            base_dir = os.path.expanduser("~/.local/share")

        log_dir = os.path.join(base_dir, "AudioTooltip_Logs")

    # Create log directory if it doesn't exist
    os.makedirs(log_dir, exist_ok=True)

    # Set up root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Clear existing handlers
    root_logger.handlers = []

    # Configure log file path
    log_file = os.path.join(log_dir, "audio_tooltip.log")

    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Set up rotating file handler
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=max_size,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Add console handler if requested
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # Set custom levels for specific modules
    if module_levels:
        for module, level in module_levels.items():
            logging.getLogger(module).setLevel(level)

    # Log startup info
    root_logger.info("=" * 60)
    root_logger.info("Logging initialized")
    root_logger.info(f"Log file: {log_file}")
    root_logger.info(f"Log level: {logging.getLevelName(log_level)}")

    # Set up exception hook to log uncaught exceptions
    def exception_hook(exctype, value, tb):
        """Log uncaught exceptions"""
        root_logger.critical("Uncaught exception:",
                             exc_info=(exctype, value, tb))
        # Call the default excepthook
        sys.__excepthook__(exctype, value, tb)

    sys.excepthook = exception_hook

    return root_logger


def get_module_logger(
    module_name: str,
    level: Optional[int] = None
) -> logging.Logger:
    """
    Get a logger for a specific module with optional custom level.

    Args:
        module_name: Name for the logger
        level: Optional log level (uses parent level if None)

    Returns:
        Logger instance
    """
    logger = logging.getLogger(module_name)
    if level is not None:
        logger.setLevel(level)
    return logger


class LoggingContext:
    """
    Context manager for temporarily changing log level.

    Example:
        with LoggingContext('mymodule', logging.DEBUG):
            # Code here runs with DEBUG level
        # Original level is restored
    """

    def __init__(self, logger_name: str, level: int):
        """
        Initialize context with logger name and temporary level.

        Args:
            logger_name: Name of the logger to modify
            level: Temporary log level to apply
        """
        self.logger = logging.getLogger(logger_name)
        self.level = level
        self.old_level = self.logger.level

    def __enter__(self):
        """Set temporary log level"""
        self.logger.setLevel(self.level)
        return self.logger

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Restore original log level"""
        self.logger.setLevel(self.old_level)


def log_and_reraise(logger: logging.Logger, exception: Exception, message: str = "An error occurred"):
    """
    Log an exception with context and re-raise it.

    Args:
        logger: Logger to use
        exception: Exception to log
        message: Message to log with exception

    Raises:
        The original exception
    """
    logger.error(f"{message}: {str(exception)}")
    logger.error(traceback.format_exc())
    raise exception


def get_log_files(log_dir: Optional[str] = None) -> Dict[str, str]:
    """
    Get dictionary of available log files with their modification times.

    Args:
        log_dir: Directory containing log files (uses default if None)

    Returns:
        Dict mapping filenames to last modified timestamps
    """
    if log_dir is None:
        if os.name == 'nt':  # Windows
            base_dir = os.path.expanduser("~\\AppData\\Local")
        else:  # Linux/Mac
            base_dir = os.path.expanduser("~/.local/share")

        log_dir = os.path.join(base_dir, "AudioTooltip_Logs")

    if not os.path.exists(log_dir):
        return {}

    log_files = {}
    for filename in os.listdir(log_dir):
        if filename.endswith('.log'):
            filepath = os.path.join(log_dir, filename)
            if os.path.isfile(filepath):
                mod_time = os.path.getmtime(filepath)
                timestamp = logging.Formatter().formatTime(
                    logging.LogRecord('', 0, '', 0, '', None,
                                      None, None, None),
                    '%Y-%m-%d %H:%M:%S'
                )
                log_files[filename] = timestamp

    return log_files
