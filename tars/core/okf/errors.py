"""OKF (Open Knowledge Format) Custom Exception Hierarchy."""

from __future__ import annotations

from typing import Any


class OKFError(Exception):
    """Base exception for all OKF engine errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class OKFParseError(OKFError):
    """Raised when parsing raw OKF text / Markdown frontmatter fails."""

    def __init__(
        self,
        message: str,
        raw_text: str | None = None,
        line_number: int | None = None,
    ) -> None:
        super().__init__(message)
        self.raw_text = raw_text
        self.line_number = line_number


# Alias for test compatibility
OKFParserError = OKFParseError


class OKFInvalidFrontmatterError(OKFParseError):
    """Raised when YAML frontmatter syntax is malformed or not a valid dictionary mapping."""



class OKFValidationError(OKFError):
    """Raised when an OKF document fails schema validation or semantic constraint checks."""

    def __init__(
        self,
        message: str,
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.errors = errors or []


class OKFMissingFieldError(OKFValidationError):
    """Raised when a mandatory OKF frontmatter field is missing."""



class OKFSerializationError(OKFError):
    """Raised when serializing an OKF document to YAML/Markdown fails."""



class OKFVersionError(OKFValidationError):
    """Raised when an unsupported OKF specification version is encountered."""

