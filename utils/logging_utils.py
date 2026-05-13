"""
Logging Utilities Module
-----------------------
Provides centralized logging configuration with rotation and custom formatting.
"""

import os
import sys
import logging
import logging.handlers
from typing import Optional, Dict


def setup_logging(
    log_dir: Optional[str] = None,
    log_level: int = logging.INFO,
    max_size: int = 5 * 1024 * 1024,  # 5MB
    backup_count: int = 5,
    console_output: bool = True,
    module_levels: Optional[Dict[str, int]] = None,
    enabled: bool = True
) -> logging.Logger:
    """
    Configure application logging with rotating file handler and optional console output.

    Args:
        log_dir: Directory for log files (uses ~/AppData/AudioTooltip_Logs on Windows, 
                 ~/.local/share/AudioTooltip_Logs on Linux/Mac if None)
        log_level: Root logger level
        enabled: If False, sets up minimal logging (WARNING level, no file output)
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

    # Set up root logger
    root_logger = logging.getLogger()
    
    # Clear existing handlers
    root_logger.handlers = []
    
    # If logging is disabled, set up minimal logging
    if not enabled:
        root_logger.setLevel(logging.WARNING)  # Only show warnings and errors
        # Add null handler to prevent logging messages
        root_logger.addHandler(logging.NullHandler())
        return root_logger

    # Create log directory if it doesn't exist
    os.makedirs(log_dir, exist_ok=True)
    
    root_logger.setLevel(log_level)

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
