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
        return self.selected_values(section, "selected", available_names)

    def selected_values(
        self,
        section: str,
        key: str,
        available_values: list[str],
    ) -> set[str] | None:
        raw_selected = self._section_data(section).get(key)
        if raw_selected is None:
            return None
        if not isinstance(raw_selected, list):
            return None

        available = set(available_values)
        selected = {str(name) for name in raw_selected if str(name) in available}
        if raw_selected and not selected:
            return None
        return selected

    def option(
        self,
        section: str,
        key: str,
        available_values: list[str],
        default: str,
    ) -> str:
        raw_value = self._section_data(section).get(key)
        if isinstance(raw_value, str) and raw_value in set(available_values):
            return raw_value
        return default

    def save_selected_names(self, section: str, selected_names: list[str]) -> None:
        self.save_section(section, {"selected": selected_names})

    def save_section(self, section: str, values: dict[str, Any]) -> None:
        section_data = self._ensure_section_data(section)
        section_data.update(values)
        self._save()

    def stats(self, section: str) -> dict[str, dict[str, int]]:
        raw_stats = self._section_data(section).get("stats", {})
        if not isinstance(raw_stats, dict):
            return {}
        return _normalize_stats(raw_stats)

    def save_stats(self, section: str, stats: dict[str, dict[str, int]]) -> None:
        section_data = self._ensure_section_data(section)
        section_data["stats"] = _normalize_stats(stats)
        self._save()

    def reset_stats(self, section: str) -> None:
        section_data = self._ensure_section_data(section)
        section_data["stats"] = {}
        self._save()

    def audible_pitches(
        self,
        backend_key: str,
        instrument_name: str,
        program: int,
        low_note: int,
        high_note: int,
    ) -> set[int] | None:
        raw_cache = self._section_data("midi").get("audible_pitches", {})
        if not isinstance(raw_cache, dict):
            return None
        raw_backend_cache = raw_cache.get(backend_key, {})
        if not isinstance(raw_backend_cache, dict):
            return None
        raw_entry = raw_backend_cache.get(instrument_name)
        if not isinstance(raw_entry, dict):
            return None
        if raw_entry.get("program") != program:
            return None
        if raw_entry.get("range") != [low_note, high_note]:
            return None

        raw_pitches = raw_entry.get("pitches")
        if not isinstance(raw_pitches, list):
            return None
        return {
            pitch
            for pitch in (_coerce_midi_note(raw_pitch) for raw_pitch in raw_pitches)
            if pitch is not None and low_note <= pitch <= high_note
        }

    def save_audible_pitches(
        self,
        backend_key: str,
        instrument_name: str,
        program: int,
        low_note: int,
        high_note: int,
        pitches: set[int],
    ) -> None:
        midi_data = self._ensure_section_data("midi")
        raw_cache = midi_data.setdefault("audible_pitches", {})
        if not isinstance(raw_cache, dict):
            raw_cache = {}
            midi_data["audible_pitches"] = raw_cache
        raw_backend_cache = raw_cache.setdefault(backend_key, {})
        if not isinstance(raw_backend_cache, dict):
            raw_backend_cache = {}
            raw_cache[backend_key] = raw_backend_cache

        raw_backend_cache[instrument_name] = {
            "program": program,
            "range": [low_note, high_note],
            "pitches": sorted(pitches),
        }
        self._save()

    def _section_data(self, section: str) -> dict[str, Any]:
        section_data = self._data.get(section, {})
        if not isinstance(section_data, dict):
            return {}
        return section_data

    def _ensure_section_data(self, section: str) -> dict[str, Any]:
        section_data = self._data.setdefault(section, {})
        if not isinstance(section_data, dict):
            section_data = {}
            self._data[section] = section_data
        return section_data

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


def _coerce_non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _coerce_midi_note(value: Any) -> int | None:
    try:
        note = int(value)
    except (TypeError, ValueError):
        return None
    if 0 <= note <= 127:
        return note
    return None


def _normalize_stats(raw_stats: dict[str, Any]) -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = {}
    for name, raw_value in raw_stats.items():
        if not isinstance(raw_value, dict):
            continue
        attempts = _coerce_non_negative_int(raw_value.get("attempts"))
        correct = min(_coerce_non_negative_int(raw_value.get("correct")), attempts)
        stats[str(name)] = {"correct": correct, "attempts": attempts}
    return stats
