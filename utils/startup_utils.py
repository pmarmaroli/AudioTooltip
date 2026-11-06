"""
Windows startup management utilities for AudioTooltip.
Handles adding/removing the application from Windows startup registry.
"""

import winreg
import os
import sys
import logging
from pathlib import Path


class StartupManager:
    """Manages Windows startup registration for the application"""
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.app_name = "AudioTooltip"
        # Registry key for startup programs
        self.registry_key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
        
    def get_executable_path(self):
        """Get the path to the current executable or script"""
        if getattr(sys, 'frozen', False):
            # Running as compiled executable
            return sys.executable
        else:
            # Running as Python script - get the main.py path
            return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'main.py'))
    
    def is_startup_enabled(self):
        """Check if the application is set to start with Windows"""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.registry_key, 0, winreg.KEY_READ) as key:
                try:
                    value, _ = winreg.QueryValueEx(key, self.app_name)
                    # Check if the value matches our current executable path
                    expected_path = self.get_startup_command()
                    return value == expected_path
                except FileNotFoundError:
                    return False
        except Exception as e:
            self.logger.error(f"Error checking startup status: {e}")
            return False
    
    def get_startup_command(self):
        """Get the command to use for startup registration"""
        exe_path = self.get_executable_path()
        
        # --startup: start silently in the tray (no splash, no messages)
        if getattr(sys, 'frozen', False):
            return f'"{exe_path}" --startup'
        else:
            # For Python script, need to include Python interpreter
            python_exe = sys.executable
            return f'"{python_exe}" "{exe_path}" --startup'
    
    def refresh_command(self):
        """If an autostart entry for the packaged exe exists but differs from the
        current command (older version, moved folder), rewrite it. Never
        creates one, and never touches it when running from source (that would
        point the user's autostart at a development interpreter)."""
        if not getattr(sys, 'frozen', False):
            return False
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.registry_key, 0, winreg.KEY_READ) as key:
                value, _ = winreg.QueryValueEx(key, self.app_name)
        except FileNotFoundError:
            return False
        except Exception as e:
            self.logger.error(f"Error reading startup entry: {e}")
            return False
        if "audiotooltip.exe" in value.lower() and value != self.get_startup_command():
            return self.enable_startup()
        return True

    def enable_startup(self):
        """Add the application to Windows startup"""
        try:
            startup_command = self.get_startup_command()
            
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.registry_key, 0, 
                              winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, self.app_name, 0, winreg.REG_SZ, startup_command)
            
            self.logger.info(f"Successfully enabled startup: {startup_command}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to enable startup: {e}")
            return False
    
    def disable_startup(self):
        """Remove the application from Windows startup"""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.registry_key, 0, 
                              winreg.KEY_SET_VALUE) as key:
                try:
                    winreg.DeleteValue(key, self.app_name)
                    self.logger.info("Successfully disabled startup")
                    return True
                except FileNotFoundError:
                    # Already not in startup
                    self.logger.info("Startup entry not found (already disabled)")
                    return True
                    
        except Exception as e:
            self.logger.error(f"Failed to disable startup: {e}")
            return False
    
    def set_startup_enabled(self, enabled):
        """Enable or disable startup based on boolean parameter"""
        if enabled:
            return self.enable_startup()
        else:
            return self.disable_startup()
    
    def get_startup_info(self):
        """Get detailed information about current startup configuration"""
        info = {
            'enabled': self.is_startup_enabled(),
            'executable_path': self.get_executable_path(),
            'startup_command': self.get_startup_command(),
            'is_frozen': getattr(sys, 'frozen', False)
        }
        
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.registry_key, 0, winreg.KEY_READ) as key:
                try:
                    current_value, _ = winreg.QueryValueEx(key, self.app_name)
                    info['current_registry_value'] = current_value
                except FileNotFoundError:
                    info['current_registry_value'] = None
        except Exception as e:
            self.logger.error(f"Error reading registry: {e}")
            info['current_registry_value'] = f"Error: {e}"
            
        return info


def test_startup_manager():
    """Test function to verify startup manager functionality"""
    manager = StartupManager()
    
    print("Startup Manager Test")
    print("=" * 30)
    
    info = manager.get_startup_info()
    for key, value in info.items():
        print(f"{key}: {value}")
    
    print(f"\nStartup currently enabled: {manager.is_startup_enabled()}")


if __name__ == "__main__":
    # Test the startup manager
    test_startup_manager()