"""OKF (Open Knowledge Format) Parser Engine."""

from __future__ import annotations

import hashlib
import re
from typing import Any

import pydantic
import yaml

from tars.core.okf.errors import (
    OKFInvalidFrontmatterError,
    OKFMissingFieldError,
    OKFParseError,
    OKFParserError,
    OKFValidationError,
    OKFVersionError,
)
from tars.core.okf.models import OKFDocument, OKFMetadata

FRONTMATTER_DELIMITER_PATTERN = re.compile(r"^---\s*$")


def _extract_frontmatter_and_body(raw_text: str) -> tuple[str, str]:
    """Split raw markdown text into YAML frontmatter string and body string.

    Raises:
        OKFParseError: If frontmatter delimiters are missing, unclosed, or invalid.
    """
    if not isinstance(raw_text, str):
        raise OKFParseError("Raw text input must be a valid string.")

    cleaned_text = raw_text.lstrip("\ufeff")
    lines = cleaned_text.splitlines(keepends=True)

    # Find opening delimiter
    start_idx: int | None = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if FRONTMATTER_DELIMITER_PATTERN.match(stripped):
            start_idx = i
            break
        raise OKFInvalidFrontmatterError(
            "Missing opening frontmatter delimiter '---'. Document must begin with frontmatter."
        )

    if start_idx is None:
        raise OKFInvalidFrontmatterError(
            "Empty document or missing opening frontmatter delimiter '---'."
        )

    # Find closing delimiter
    end_idx: int | None = None
    for i in range(start_idx + 1, len(lines)):
        stripped = lines[i].strip()
        if FRONTMATTER_DELIMITER_PATTERN.match(stripped):
            end_idx = i
            break

    if end_idx is None:
        raise OKFInvalidFrontmatterError(
            "Unclosed frontmatter delimiter. Expected closing '---' not found."
        )

    frontmatter_yaml = "".join(lines[start_idx + 1 : end_idx])
    body = "".join(lines[end_idx + 1 :])

    # Strip single leading newline from body for clean presentation
    if body.startswith("\r\n"):
        body = body[2:]
    elif body.startswith("\n"):
        body = body[1:]

    return frontmatter_yaml, body


def parse_okf_text(raw_text: str, file_path: str | None = None) -> OKFDocument:
    """Parse raw OKF markdown string into a validated OKFDocument instance.

    Args:
        raw_text: Full raw content of an OKF markdown file.
        file_path: Optional storage or file path for metadata indexing.

    Returns:
        Validated OKFDocument instance.

    Raises:
        OKFParseError: If frontmatter delimiters are invalid or missing.
        OKFInvalidFrontmatterError: If YAML syntax is invalid or not a dictionary.
        OKFValidationError: If metadata fails Pydantic schema validation.
    """
    frontmatter_yaml, body = _extract_frontmatter_and_body(raw_text)

    try:
        data = yaml.safe_load(frontmatter_yaml)
    except yaml.YAMLError as exc:
        raise OKFInvalidFrontmatterError(f"Malformed YAML frontmatter: {exc}") from exc

    if not isinstance(data, dict):
        raise OKFInvalidFrontmatterError(
            f"Frontmatter must parse into a YAML dictionary/mapping, got {type(data).__name__}"
        )

    # Check for missing mandatory fields explicitly for specialized exception
    missing_fields = [
        field for field in ("id", "type", "title") if field not in data or data[field] is None
    ]
    if missing_fields:
        raise OKFMissingFieldError(
            f"Missing required OKF frontmatter field(s): {', '.join(missing_fields)}"
        )

    try:
        metadata = OKFMetadata(**data)
    except pydantic.ValidationError as exc:
        raw_errors: list[dict[str, Any]] = exc.errors()  # type: ignore[assignment]
        raise OKFValidationError(
            f"OKF document metadata validation failed: {exc}",
            errors=raw_errors,
        ) from exc

    raw_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

    return OKFDocument(
        metadata=metadata,
        content=body,
        file_path=file_path,
        raw_hash=raw_hash,
    )


__all__ = [
    "OKFInvalidFrontmatterError",
    "OKFMissingFieldError",
    "OKFParseError",
    "OKFParserError",
    "OKFValidationError",
    "OKFVersionError",
    "parse_okf_text",
]
