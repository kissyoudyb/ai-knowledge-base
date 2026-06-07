#!/usr/bin/env python3
"""Validate knowledge entry JSON files."""

import json
import re
import sys
from pathlib import Path


REQUIRED_FIELDS: dict[str, type] = {
    "id": str,
    "title": str,
    "source_url": str,
    "summary": str,
    "tags": list,
    "status": str,
}

VALID_STATUSES = {"draft", "review", "published", "archived"}
ID_PATTERN = re.compile(r"^[a-z_]+-\d{8}-[a-f0-9]{12}$")
URL_PATTERN = re.compile(r"^https?://")
VALID_AUDIENCES = {"beginner", "intermediate", "advanced"}

STATUS_EMOJI = {
    "error": "✗",
    "warning": "⚠",
    "info": "ℹ",
}


def _fmt(level: str, msg: str) -> str:
    return f"  {STATUS_EMOJI.get(level, '?')} {msg}"


def validate_file(filepath: Path) -> list[str]:
    """Validate a single JSON file and return list of error messages."""
    errors: list[str] = []

    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception as exc:
        return [f"  {STATUS_EMOJI['error']} Cannot read file: {exc}"]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return [f"  {STATUS_EMOJI['error']} Invalid JSON: {exc}"]

    if not isinstance(data, dict):
        return [f"  {STATUS_EMOJI['error']} Root must be a JSON object"]

    # Required fields: existence + type
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in data:
            errors.append(_fmt("error", f"Missing required field: '{field}'"))
            continue
        if not isinstance(data[field], expected_type):
            errors.append(
                _fmt(
                    "error",
                    f"'{field}' must be {expected_type.__name__}, "
                    f"got {type(data[field]).__name__}",
                )
            )

    # Return early if required fields missing (avoid cascade errors)
    required_keys = set(REQUIRED_FIELDS)
    if not required_keys.issubset(data.keys()):
        return errors

    # ID format
    id_val: str = data["id"]
    if not ID_PATTERN.match(id_val):
        errors.append(
            _fmt(
                "error",
                f"'id' should match {{source}}-{{YYYYMMDD}}-{{hash}} "
                f"(e.g. github_trending-20260607-0abcb8d6878d), got '{id_val}'",
            )
        )

    # Status
    status: str = data["status"]
    if status not in VALID_STATUSES:
        valid_str = ", ".join(sorted(VALID_STATUSES))
        errors.append(
            _fmt(
                "error",
                f"'status' must be one of {{{valid_str}}}, got '{status}'",
            )
        )

    # URL format
    url: str = data["source_url"]
    if not URL_PATTERN.match(url):
        errors.append(
            _fmt("error", f"'source_url' must start with https?://, got '{url}'")
        )

    # Summary length
    summary: str = data["summary"]
    if len(summary) < 20:
        errors.append(
            _fmt(
                "error",
                f"'summary' must be at least 20 characters "
                f"(got {len(summary)})",
            )
        )

    # Tags count
    tags: list = data["tags"]
    if len(tags) < 1:
        errors.append(_fmt("error", "'tags' must have at least 1 tag"))
    for i, tag in enumerate(tags):
        if not isinstance(tag, str):
            errors.append(
                _fmt(
                    "error",
                    f"'tags[{i}]' must be a string, got {type(tag).__name__}",
                )
            )

    # Optional: score
    if "score" in data:
        score = data["score"]
        if not isinstance(score, (int, float)) or not (1 <= score <= 10):
            errors.append(
                _fmt(
                    "error",
                    f"'score' must be a number between 1 and 10 (inclusive), "
                    f"got {score!r}",
                )
            )

    # Optional: audience
    if "audience" in data:
        audience = data["audience"]
        if audience not in VALID_AUDIENCES:
            valid_aud = ", ".join(sorted(VALID_AUDIENCES))
            errors.append(
                _fmt(
                    "error",
                    f"'audience' must be one of {{{valid_aud}}}, "
                    f"got '{audience}'",
                )
            )

    return errors


def expand_globs(args: list[str]) -> list[Path]:
    """Expand command-line arguments, supporting glob patterns."""
    paths: list[Path] = []
    for arg in args:
        p = Path(arg)
        if "*" in arg or "?" in arg:
            paths.extend(sorted(p.parent.glob(p.name)))
        else:
            paths.append(p)
    return paths


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print("Usage: python hooks/validate_json.py <json_file> [json_file2 ...]")
        sys.exit(1)

    files = expand_globs(args)
    if not files:
        print("error: No files matched the given patterns")
        sys.exit(1)

    total_files = len(files)
    total_errors = 0
    failed_files = 0
    passed_files = 0

    for filepath in files:
        if not filepath.exists():
            print(f"\n{filepath}")
            print(f"  {STATUS_EMOJI['error']} File not found")
            failed_files += 1
            total_errors += 1
            continue

        errors = validate_file(filepath)
        if errors:
            print(f"\n{filepath}")
            for err in errors:
                print(err)
            failed_files += 1
            total_errors += len(errors)
        else:
            passed_files += 1

    print()
    print(f"Summary: {total_files} file(s), "
          f"{passed_files} passed, "
          f"{failed_files} failed, "
          f"{total_errors} error(s)")

    sys.exit(1 if failed_files else 0)


if __name__ == "__main__":
    main()
