"""
File Utilities Module
--------------------
Handles file operations, audio file detection, and recent files management.
"""

import os
import json
import logging
from pathlib import Path
from typing import List, Set, Dict, Optional, Union, Any

# Define logger
logger = logging.getLogger("FileUtils")

# Common audio file extensions
AUDIO_EXTENSIONS: Set[str] = {
    '.mp3', '.wav', '.flac', '.m4a', '.ogg', '.wma',
    '.aac', '.aiff', '.mp4', '.ape', '.opus', '.wv'
}


def is_audio_file(file_path: str) -> bool:
    """
    Check if a file is an audio file based on extension.

    Args:
        file_path: Path to file

    Returns:
        bool: True if file has audio extension
    """
    if not file_path:
        return False

    extension = Path(file_path).suffix.lower()
    return extension in AUDIO_EXTENSIONS


def get_files_in_directory(directory: str, audio_only: bool = True) -> List[str]:
    """
    Get list of files in directory, optionally filtering for audio files.

    Args:
        directory: Directory path
        audio_only: Whether to include only audio files

    Returns:
        List of file paths
    """
    if not os.path.exists(directory) or not os.path.isdir(directory):
        logger.error(f"Invalid directory: {directory}")
        return []

    try:
        files = []
        for item in os.listdir(directory):
            full_path = os.path.join(directory, item)
            if os.path.isfile(full_path):
                if not audio_only or is_audio_file(full_path):
                    files.append(full_path)
        return files
    except Exception as e:
        logger.error(f"Error listing directory {directory}: {e}")
        return []


def save_recent_files(settings: Any, recent_files: List[str], max_count: int = 10) -> bool:
    """
    Save recent files list to settings.

    Args:
        settings: QSettings or similar settings object
        recent_files: List of recent file paths
        max_count: Maximum number of files to keep

    Returns:
        bool: True if successful
    """
    try:
        # Filter to files that exist and respect max count
        valid_files = [
            f for f in recent_files if os.path.exists(f)][:max_count]

        # Save to settings
        if hasattr(settings, 'setValue'):
            settings.setValue("recent_files", json.dumps(valid_files))
            logger.debug(f"Saved {len(valid_files)} recent files")
            return True
        else:
            logger.warning("Invalid settings object")
            return False
    except Exception as e:
        logger.error(f"Error saving recent files: {e}")
        return False


def load_recent_files(settings: Any) -> List[str]:
    """
    Load recent files from settings.

    Args:
        settings: QSettings or similar settings object

    Returns:
        List of recent file paths
    """
    try:
        if hasattr(settings, 'value'):
            recent_files_str = settings.value("recent_files", "")
            if recent_files_str:
                files = json.loads(recent_files_str)
                # Filter to files that still exist
                valid_files = [f for f in files if os.path.exists(f)]
                logger.debug(f"Loaded {len(valid_files)} recent files")
                return valid_files
        return []
    except Exception as e:
        logger.error(f"Error loading recent files: {e}")
        return []


def add_recent_file(settings: Any, file_path: str, recent_files: Optional[List[str]] = None) -> List[str]:
    """
    Add file to recent files list.

    Args:
        settings: QSettings or similar settings object
        file_path: Path to add
        recent_files: Existing recent files list (if None, will be loaded)

    Returns:
        Updated recent files list
    """
    if not os.path.exists(file_path):
        logger.warning(f"Cannot add non-existent file to recents: {file_path}")
        return recent_files or []

    try:
        # Load existing list if not provided
        if recent_files is None:
            recent_files = load_recent_files(settings)

        # Remove if already exists
        if file_path in recent_files:
            recent_files.remove(file_path)

        # Add to beginning
        recent_files.insert(0, file_path)

        # Save updated list
        save_recent_files(settings, recent_files)

        return recent_files
    except Exception as e:
        logger.error(f"Error adding recent file: {e}")
        return recent_files or []


def get_default_audio_directory() -> str:
    """
    Get default directory for audio files based on operating system.

    Returns:
        Path to default music directory
    """
    home = str(Path.home())

    # Check OS-specific music directories
    if os.name == 'nt':  # Windows
        music_dir = os.path.join(home, 'Music')
        if not os.path.exists(music_dir):
            music_dir = os.path.join(home, 'Documents', 'Music')
    elif os.name == 'posix':  # macOS, Linux
        if os.path.exists(os.path.join(home, 'Music')):  # macOS
            music_dir = os.path.join(home, 'Music')
        else:  # Linux
            music_dir = os.path.join(home, 'Music')
            if not os.path.exists(music_dir):
                music_dir = home
    else:
        music_dir = home

    # Fall back to home directory if music dir doesn't exist
    if not os.path.exists(music_dir):
        music_dir = home

    return music_dir


def format_file_size(size_bytes: int) -> str:
    """
    Format file size in human-readable format.

    Args:
        size_bytes: Size in bytes

    Returns:
        Formatted size string
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def validate_audio_file_path(file_path, logger):
    """
    Validate an audio file path with thorough checks.

    Args:
        file_path: Path to validate
        logger: Logger to use for messages

    Returns:
        tuple: (is_valid, message) - validation result and error message if any
    """
    # Basic validation
    if not file_path:
        return False, "Empty file path"

    # Normalize path
    try:
        file_path = os.path.normpath(file_path)
    except:
        return False, "Unable to normalize path"

    # Check if file exists
    if not os.path.exists(file_path):
        return False, f"File does not exist: {file_path}"

    # Check if it's a file (not a directory)
    if not os.path.isfile(file_path):
        return False, f"Not a file: {file_path}"

    # Check file size
    try:
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            return False, f"File is empty: {file_path}"
        logger.debug(f"File size: {file_size/1024:.1f} KB")
    except Exception as e:
        return False, f"Error checking file size: {str(e)}"

    # Check file extension
    file_ext = os.path.splitext(file_path.lower())[1]
    if file_ext not in AUDIO_EXTENSIONS:
        return False, f"Not an audio file: {file_ext}"

    # Check file permissions
    try:
        with open(file_path, 'rb') as f:
            # Just check if we can read the first few bytes
            f.read(10)
    except Exception as e:
        return False, f"Unable to read file: {str(e)}"

    # All checks passed
    return True, ""
