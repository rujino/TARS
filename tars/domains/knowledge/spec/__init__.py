"""OKF (Open Knowledge Format) Specification Package."""

from __future__ import annotations

from tars.domains.knowledge.spec.errors import (
    OKFDocumentAlreadyExistsError,
    OKFError,
    OKFInvalidFrontmatterError,
    OKFMissingFieldError,
    OKFNotFoundError,
    OKFParseError,
    OKFSerializationError,
    OKFStorageError,
    OKFValidationError,
    OKFVersionError,
)
from tars.domains.knowledge.spec.models import (
    ID_PATTERN,
    OKFDocument,
    OKFImportance,
    OKFMetadata,
    OKFRelations,
    OKFSource,
    OKFType,
)
from tars.domains.knowledge.spec.parser import parse_okf_text
from tars.domains.knowledge.spec.serializer import serialize_okf_document
from tars.domains.knowledge.spec.validator import (
    validate_okf_document,
    validate_okf_semantic_relations,
)

__all__ = [
    # Models & Enums
    "ID_PATTERN",
    "OKFType",
    "OKFImportance",
    "OKFSource",
    "OKFRelations",
    "OKFMetadata",
    "OKFDocument",
    # Functions
    "parse_okf_text",
    "serialize_okf_document",
    "validate_okf_document",
    "validate_okf_semantic_relations",
    # Exceptions
    "OKFError",
    "OKFParseError",
    "OKFInvalidFrontmatterError",
    "OKFValidationError",
    "OKFMissingFieldError",
    "OKFSerializationError",
    "OKFVersionError",
    "OKFStorageError",
    "OKFNotFoundError",
    "OKFDocumentAlreadyExistsError",
]
