from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    yaml = None


class ConfigError(ValueError):
    pass


def load_yaml_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        data = yaml.safe_load(text) or {}
    else:
        data = _minimal_yaml_load(text)

    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a YAML mapping")
    return data


def _minimal_yaml_load(text: str) -> dict[str, Any]:
    """Parse the small YAML subset used by the bundled config files.

    This fallback intentionally supports mappings plus inline lists/strings.
    Install PyYAML if you want full YAML syntax.
    """
    data: dict[str, Any] = {}
    current_section: str | None = None

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = _strip_inline_comment(raw_line).rstrip()
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        key, value = _split_key_value(stripped, line_number)

        if indent == 0:
            if value is None:
                data[key] = {}
                current_section = key
            else:
                data[key] = _parse_scalar(value)
                current_section = None
            continue

        if current_section is None or not isinstance(data.get(current_section), dict):
            raise ConfigError(f"Unexpected indented line {line_number}: {raw_line}")
        data[current_section][key] = _parse_scalar(value)

    return data


def _strip_inline_comment(line: str) -> str:
    in_single = False
    in_double = False
    escaped = False

    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == "#" and not in_single and not in_double:
            if index == 0 or line[index - 1].isspace():
                return line[:index]
    return line


def _split_key_value(line: str, line_number: int) -> tuple[str, str | None]:
    in_single = False
    in_double = False
    escaped = False

    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == ":" and not in_single and not in_double:
            key = _unquote(line[:index].strip())
            value = line[index + 1 :].strip()
            return key, value or None

    raise ConfigError(f"Expected key/value mapping at line {line_number}: {line}")


def _parse_scalar(value: str | None) -> Any:
    if value is None:
        return None

    value = value.strip()
    if not value:
        return None
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part) for part in _split_csv(inner)]
    return _unquote(value)


def _split_csv(value: str) -> list[str]:
    parts: list[str] = []
    start = 0
    in_single = False
    in_double = False
    escaped = False

    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == "," and not in_single and not in_double:
            parts.append(value[start:index].strip())
            start = index + 1

    parts.append(value[start:].strip())
    return parts


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value

