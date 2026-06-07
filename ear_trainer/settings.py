from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import os
import tempfile


SETTINGS_ENV_VAR = "EAR_TRAINER_SETTINGS"
APP_CONFIG_DIR = "relative-ear-trainer"
SETTINGS_FILENAME = "settings.json"


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_settings_path()
        self._data = self._load()

    def selected_names(self, section: str, available_names: list[str]) -> set[str] | None:
        raw_selected = self._data.get(section, {}).get("selected")
        if raw_selected is None:
            return None
        if not isinstance(raw_selected, list):
            return None

        available = set(available_names)
        selected = {str(name) for name in raw_selected if str(name) in available}
        if raw_selected and not selected:
            return None
        return selected

    def save_selected_names(self, section: str, selected_names: list[str]) -> None:
        section_data = self._data.setdefault(section, {})
        if not isinstance(section_data, dict):
            section_data = {}
            self._data[section] = section_data

        section_data["selected"] = selected_names
        self._save()

    def _load(self) -> dict[str, Any]:
        try:
            with self.path.open("r", encoding="utf-8") as settings_file:
                data = json.load(settings_file)
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError):
            return {}

        if not isinstance(data, dict):
            return {}
        return data

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._data, indent=2, sort_keys=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            delete=False,
        ) as settings_file:
            settings_file.write(payload)
            settings_file.write("\n")
            temp_path = Path(settings_file.name)

        temp_path.replace(self.path)


def default_settings_path() -> Path:
    configured_path = os.environ.get(SETTINGS_ENV_VAR)
    if configured_path:
        return Path(configured_path).expanduser()

    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        base_path = Path(config_home).expanduser()
    else:
        base_path = Path.home() / ".config"

    return base_path / APP_CONFIG_DIR / SETTINGS_FILENAME
