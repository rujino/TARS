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
    OKF2Document,
    OKF2Metadata,
    OKFDocument,
    OKFImportance,
    OKFMetadata,
    OKFRelations,
    OKFSource,
    OKFStatus,
    OKFType,
)
from tars.domains.knowledge.spec.parser import parse_okf_text
from tars.domains.knowledge.spec.serializer import serialize_okf_document
from tars.domains.knowledge.spec.validator import (
    validate_okf_document,
    validate_okf_semantic_relations,
)
from tars.domains.knowledge.spec.wikilink import (
    WIKILINK_PATTERN,
    WikiLink,
    extract_target_ids,
    extract_wikilinks,
    format_wikilink,
    replace_wikilink_target,
)

__all__ = [
    # Models & Enums
    "ID_PATTERN",
    "OKFType",
    "OKFImportance",
    "OKFSource",
    "OKFStatus",
    "OKFRelations",
    "OKFMetadata",
    "OKFDocument",
    "OKF2Metadata",
    "OKF2Document",
    "WikiLink",
    "WIKILINK_PATTERN",
    # Functions
    "extract_wikilinks",
    "extract_target_ids",
    "format_wikilink",
    "replace_wikilink_target",
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
