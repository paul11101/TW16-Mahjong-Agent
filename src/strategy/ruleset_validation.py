from collections.abc import Mapping
import json
from pathlib import Path

from src.rules.rule import RULESET_VERSION


def validate_ruleset_version(
    version: object,
    *,
    field_name: str = "ruleset_version",
) -> str:
    if not isinstance(version, str) or not version.strip():
        raise ValueError(f"{field_name} is required")
    if version != RULESET_VERSION:
        raise ValueError(
            f"{field_name} mismatch: expected {RULESET_VERSION}, found {version}"
        )
    return version


def validate_record_ruleset_version(record: Mapping[str, object]) -> str:
    """Validate the current and legacy serialized field names."""
    if not isinstance(record, Mapping):
        raise ValueError("record must be a JSON object")

    version = record.get("ruleset_version")
    legacy_version = record.get("rule_version")
    if version is None and legacy_version is None:
        raise ValueError("ruleset_version is required")
    if version is not None and legacy_version is not None and version != legacy_version:
        raise ValueError("rule_version and ruleset_version do not match")
    return validate_ruleset_version(
        version if version is not None else legacy_version
    )


def validate_ruleset_file(path: str | Path) -> int:
    """Scan every JSONL record and fail with its line number on version errors."""
    validated = 0
    with Path(path).open("rb") as stream:
        for line_number, line in enumerate(stream, start=1):
            try:
                record = json.loads(line.decode("utf-8"))
                validate_record_ruleset_version(record)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
                raise ValueError(f"line {line_number}: {error}") from error
            validated += 1
    if validated == 0:
        raise ValueError("dataset is empty")
    return validated
