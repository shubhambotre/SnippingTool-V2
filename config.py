import os
import json

CONFIG_FILE_NAME = ".custom_snipping_tool_config.json"

DEFAULT_SETTINGS = {
    "last_tool": "pencil",
    "last_color": "#00E5FF",
    "last_thickness": 3,
    "last_fill_mode": "hollow",
    "last_font_size": 14,
    "last_font_family": "Arial",
    "default_save_path": os.path.join(os.path.expanduser("~"), "Pictures"),
    "naming_pattern": "Capture_{datetime}",
    "default_format": "PNG",
    "default_capture_mode": "free",
    "fixed_width": 800,
    "fixed_height": 600,
    "theme": "light",
    "confirm_before_delete": True
}

class AppConfig:
    def __init__(self):
        self.config_path = os.path.join(os.path.expanduser("~"), CONFIG_FILE_NAME)
        self.settings = DEFAULT_SETTINGS.copy()
        self.load()

    def load(self):
        """Load settings from the user's config file if it exists."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded_data = json.load(f)
                    # Update settings with loaded data, keeping defaults for missing keys
                    for key, val in loaded_data.items():
                        if key in self.settings:
                            self.settings[key] = val
            except Exception as e:
                print(f"Error loading configuration: {e}")
                self.save()
        
        # Ensure default save directory exists
        save_path = self.settings.get("default_save_path")
        if save_path and not os.path.exists(save_path):
            try:
                os.makedirs(save_path, exist_ok=True)
            except Exception:
                # Fall back to user's home directory if unable to create Pictures
                self.settings["default_save_path"] = os.path.expanduser("~")

    def save(self):
        """Save settings to the config file."""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=4)
        except Exception as e:
            print(f"Error saving configuration: {e}")

    def get(self, key):
        return self.settings.get(key)

    def set(self, key, value):
        if key in self.settings:
            self.settings[key] = value
            self.save()
