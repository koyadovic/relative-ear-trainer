from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
import re

from .config_loader import ConfigError, load_yaml_file


_MAJOR_SCALE_SEMITONES = {
    1: 0,
    2: 2,
    3: 4,
    4: 5,
    5: 7,
    6: 9,
    7: 11,
}
_DEGREE_RE = re.compile(r"^([b#]*)(\d+)$")


@dataclass(frozen=True)
class MusicDefinition:
    name: str
    semitones: tuple[int, ...]
    formula: tuple[str, ...]


def load_interval_definitions(path: Path) -> tuple[MusicDefinition, ...]:
    data = load_yaml_file(path)
    section = data.get("intervals", data)
    definitions: list[MusicDefinition] = []

    for name, value in _iter_definition_entries(section):
        tokens = _coerce_formula_tokens(value, default=name)
        semitones = tuple(degree_to_semitones(token) for token in tokens)
        if not semitones:
            raise ConfigError(f"Interval {name!r} has an empty formula")

        interval = semitones[0] if len(semitones) == 1 else semitones[-1] - semitones[0]
        if interval < 0:
            raise ConfigError(f"Interval {name!r} must resolve to a non-negative distance")
        definitions.append(MusicDefinition(name=name, semitones=(interval,), formula=tokens))

    if not definitions:
        raise ConfigError(f"No interval definitions found in {path}")
    return tuple(definitions)


def load_harmony_definitions(path: Path) -> tuple[MusicDefinition, ...]:
    data = load_yaml_file(path)
    section = data.get("harmonies", data)
    definitions: list[MusicDefinition] = []

    for name, value in _iter_definition_entries(section):
        tokens = _coerce_formula_tokens(value, default=None)
        semitones = _dedupe_preserving_order(degree_to_semitones(token) for token in tokens)
        if not semitones:
            raise ConfigError(f"Harmony {name!r} has an empty formula")
        if semitones[0] != 0:
            semitones = (0, *semitones)
            tokens = ("1", *tokens)
        definitions.append(MusicDefinition(name=name, semitones=semitones, formula=tokens))

    if not definitions:
        raise ConfigError(f"No harmony definitions found in {path}")
    return tuple(definitions)


def degree_to_semitones(token: Any) -> int:
    normalized = _normalize_degree_token(token)
    match = _DEGREE_RE.match(normalized)
    if not match:
        raise ConfigError(f"Invalid degree token {token!r}")

    accidental_text, degree_text = match.groups()
    degree = int(degree_text)
    if degree < 1:
        raise ConfigError(f"Degree must be >= 1: {token!r}")

    octave, scale_index = divmod(degree - 1, 7)
    simple_degree = scale_index + 1
    semitone = _MAJOR_SCALE_SEMITONES[simple_degree] + (12 * octave)
    semitone += accidental_text.count("#")
    semitone -= accidental_text.count("b")
    return semitone


def _normalize_degree_token(token: Any) -> str:
    value = str(token).strip()
    value = value.replace("♭", "b").replace("♯", "#")
    value = value.replace(" ", "")

    lowered = value.lower()
    if lowered in {"r", "root", "tonic", "tonica", "tónica", "unison", "unisono", "unísono"}:
        return "1"
    if lowered.startswith("+") and lowered[1:].isdigit():
        return "#" + lowered[1:]
    return value


def _iter_definition_entries(section: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(section, dict):
        for name, value in section.items():
            yield str(name), value
        return

    if isinstance(section, list):
        for index, item in enumerate(section, start=1):
            if not isinstance(item, dict) or "name" not in item:
                raise ConfigError(f"List definition #{index} must be a mapping with a name")
            value = item.get("formula", item.get("notes", item.get("interval")))
            yield str(item["name"]), value
        return

    raise ConfigError("Definitions must be a mapping or a list of named mappings")


def _coerce_formula_tokens(value: Any, default: str | None) -> tuple[str, ...]:
    if value is None:
        if default is None:
            return ()
        value = default

    if isinstance(value, dict):
        value = value.get("formula", value.get("notes", value.get("interval")))

    if isinstance(value, (list, tuple)):
        tokens = [str(item).strip() for item in value]
    else:
        text = str(value).strip()
        if "," in text:
            tokens = [part.strip() for part in text.split(",")]
        else:
            tokens = [text]

    return tuple(token for token in tokens if token)


def _dedupe_preserving_order(values: Iterable[int]) -> tuple[int, ...]:
    seen: set[int] = set()
    result: list[int] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)

