"""OKF (Open Knowledge Format) Engine Core Package."""

from __future__ import annotations

from tars.core.okf.errors import (
    OKFError,
    OKFInvalidFrontmatterError,
    OKFMissingFieldError,
    OKFParseError,
    OKFParserError,
    OKFSerializationError,
    OKFValidationError,
    OKFVersionError,
)
from tars.core.okf.models import (
    OKFDocument,
    OKFFrontmatter,
    OKFImportance,
    OKFMetadata,
    OKFRelations,
    OKFSource,
    OKFType,
)
from tars.core.okf.parser import parse_okf_text
from tars.core.okf.serializer import serialize_okf_document
from tars.core.okf.validator import (
    validate_okf_document,
    validate_okf_semantic_relations,
)

__all__ = [
    # Models & Enums
    "OKFType",
    "OKFImportance",
    "OKFSource",
    "OKFRelations",
    "OKFMetadata",
    "OKFFrontmatter",
    "OKFDocument",
    # Functions
    "parse_okf_text",
    "serialize_okf_document",
    "validate_okf_document",
    "validate_okf_semantic_relations",
    # Exceptions
    "OKFError",
    "OKFParseError",
    "OKFParserError",
    "OKFInvalidFrontmatterError",
    "OKFValidationError",
    "OKFMissingFieldError",
    "OKFSerializationError",
    "OKFVersionError",
]
