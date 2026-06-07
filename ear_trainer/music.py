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


@dataclass(frozen=True)
class ProgressionChord:
    token: str
    degree: str
    degree_semitones: int
    harmony: MusicDefinition


@dataclass(frozen=True)
class ProgressionDefinition:
    name: str
    mode: str
    chords: tuple[ProgressionChord, ...]


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


def load_progression_definitions(
    path: Path,
    harmony_definitions: tuple[MusicDefinition, ...],
) -> tuple[ProgressionDefinition, ...]:
    data = load_yaml_file(path)
    section = data.get("progressions", data)
    harmonies_by_name = {definition.name: definition for definition in harmony_definitions}
    definitions: list[ProgressionDefinition] = []
    seen_names: dict[str, tuple[str, tuple[str, ...]]] = {}

    for name, value in _iter_progression_entries(section):
        mode, tokens = _coerce_progression_tokens(value)
        if name is None:
            name = _progression_name_from_tokens(tokens)

        signature = (mode, tokens)
        existing_signature = seen_names.get(name)
        if existing_signature == signature:
            continue
        if existing_signature is not None:
            raise ConfigError(
                f"Duplicate progression name {name!r} with a different formula. "
                "Use unique names or the list format."
            )
        seen_names[name] = signature

        chords = tuple(_parse_progression_chord(token, harmonies_by_name) for token in tokens)
        if not chords:
            raise ConfigError(f"Progression {name!r} has an empty formula")
        definitions.append(ProgressionDefinition(name=name, mode=mode, chords=chords))

    if not definitions:
        raise ConfigError(f"No progression definitions found in {path}")
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


_ROMAN_DEGREE_SEMITONES = {
    "I": 0,
    "II": 2,
    "III": 4,
    "IV": 5,
    "V": 7,
    "VI": 9,
    "VII": 11,
}
_ROMAN_DEGREES_BY_LENGTH = ("VII", "III", "VI", "IV", "II", "V", "I")


def _iter_progression_entries(section: Any) -> Iterable[tuple[str | None, Any]]:
    if isinstance(section, dict):
        for name, value in section.items():
            yield str(name), value
        return

    if isinstance(section, list):
        for index, item in enumerate(section, start=1):
            if isinstance(item, str) or isinstance(item, (list, tuple)):
                yield None, item
                continue
            if isinstance(item, dict):
                name = item.get("name")
                yield str(name) if name else None, item
                continue
            raise ConfigError(f"Progression list item #{index} has an unsupported format")
        return

    raise ConfigError("Progressions must be a mapping or a list")


def _coerce_progression_tokens(value: Any) -> tuple[str, tuple[str, ...]]:
    mode = "major"

    if isinstance(value, dict):
        mode = str(value.get("mode", mode)).strip().lower()
        chord_value = value.get("chords", value.get("progression", value.get("formula")))
    elif isinstance(value, (list, tuple)):
        values = [str(item).strip() for item in value if str(item).strip()]
        if values and values[0].lower() in {"major", "minor"}:
            mode = values[0].lower()
            values = values[1:]
        chord_value = values
    else:
        text = str(value).strip()
        chord_value = text
        for separator in ("|", ":"):
            if separator not in text:
                continue
            left, right = text.split(separator, 1)
            candidate_mode = left.strip().lower()
            if candidate_mode in {"major", "minor"}:
                mode = candidate_mode
                chord_value = right
            break

    if mode not in {"major", "minor"}:
        raise ConfigError(f"Progression mode must be major or minor, got {mode!r}")

    tokens = _coerce_formula_tokens(chord_value, default=None)
    return mode, tuple(token.rstrip(".") for token in tokens)


def _progression_name_from_tokens(tokens: tuple[str, ...]) -> str:
    return ", ".join(tokens)


def _parse_progression_chord(
    token: str,
    harmonies_by_name: dict[str, MusicDefinition],
) -> ProgressionChord:
    normalized = token.strip().replace("♭", "b").replace("♯", "#")
    if not normalized:
        raise ConfigError("Progression contains an empty chord token")

    accidental_index = 0
    while accidental_index < len(normalized) and normalized[accidental_index] in {"b", "#"}:
        accidental_index += 1

    accidental_text = normalized[:accidental_index]
    remaining = normalized[accidental_index:]
    upper_remaining = remaining.upper()

    roman_degree = None
    suffix = None
    for candidate in _ROMAN_DEGREES_BY_LENGTH:
        if upper_remaining.startswith(candidate):
            roman_degree = candidate
            suffix = remaining[len(candidate) :]
            break

    if roman_degree is None or suffix is None:
        raise ConfigError(f"Invalid progression chord token {token!r}")

    harmony_name = suffix or "Maj"
    harmony = harmonies_by_name.get(harmony_name)
    if harmony is None:
        available = ", ".join(sorted(harmonies_by_name))
        raise ConfigError(
            f"Unknown harmony {harmony_name!r} in progression chord {token!r}. "
            f"Available harmonies: {available}"
        )

    degree = accidental_text + roman_degree
    semitone = _ROMAN_DEGREE_SEMITONES[roman_degree]
    semitone += accidental_text.count("#")
    semitone -= accidental_text.count("b")

    return ProgressionChord(
        token=normalized,
        degree=degree,
        degree_semitones=semitone,
        harmony=harmony,
    )
