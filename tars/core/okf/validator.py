"""OKF (Open Knowledge Format) Semantic Validator Engine."""

from __future__ import annotations

from typing import Any

import pydantic

from tars.core.okf.errors import OKFValidationError, OKFVersionError
from tars.core.okf.models import ID_PATTERN, OKFDocument, OKFMetadata

SUPPORTED_MAJOR_VERSIONS = {"1", "1.0"}


def validate_okf_document(doc: OKFDocument | dict[str, Any], raise_on_error: bool = False) -> bool:
    """Validate schema and semantic rules of an OKF document.

    Args:
        doc: OKFDocument instance or raw metadata dict to validate.
        raise_on_error: If True, raises OKFValidationError on failure; otherwise returns False.

    Returns:
        True if document passes all validation checks, False otherwise.

    Raises:
        OKFValidationError: If raise_on_error is True and validation fails.
        OKFVersionError: If specification version is incompatible.
    """
    errors: list[str] = []

    try:
        if isinstance(doc, dict):
            metadata = OKFMetadata(**doc)
        else:
            metadata = doc.metadata
    except pydantic.ValidationError as exc:
        if raise_on_error:
            raise OKFValidationError(
                f"OKF schema validation failed: {exc}",
                errors=exc.errors(),  # type: ignore[arg-type]
            ) from exc
        return False

    # 1. Version Compatibility Check
    version_major = metadata.okf_version.split(".")[0]
    if (
        version_major not in SUPPORTED_MAJOR_VERSIONS
        and metadata.okf_version not in SUPPORTED_MAJOR_VERSIONS
    ):
        msg = f"Unsupported OKF version '{metadata.okf_version}'. Supported versions: {SUPPORTED_MAJOR_VERSIONS}"
        if raise_on_error:
            raise OKFVersionError(msg)
        return False

    # 2. Self-Reference in Relations Check
    if metadata.id in metadata.relations.depends_on:
        errors.append(f"Document '{metadata.id}' cannot depend on itself in depends_on.")
    if metadata.id in metadata.relations.related_to:
        errors.append(f"Document '{metadata.id}' cannot relate to itself in related_to.")

    # 3. Relation IDs format check
    for dep_id in metadata.relations.depends_on:
        if not ID_PATTERN.match(dep_id):
            errors.append(f"Invalid dependency ID format '{dep_id}' in depends_on.")
    for rel_id in metadata.relations.related_to:
        if not ID_PATTERN.match(rel_id):
            errors.append(f"Invalid relation ID format '{rel_id}' in related_to.")

    # 4. Timestamp Sanity Check
    if metadata.created_at > metadata.updated_at:
        errors.append(
            f"created_at ({metadata.created_at}) cannot be later than updated_at ({metadata.updated_at})."
        )

    if errors:
        if raise_on_error:
            raise OKFValidationError(
                f"OKF semantic validation failed: {'; '.join(errors)}",
                errors=[{"msg": err} for err in errors],
            )
        return False

    return True


def validate_okf_semantic_relations(docs: list[OKFDocument], raise_on_error: bool = False) -> bool:
    """Validate inter-document graph relations across a collection of OKF documents.

    Checks for:
    - Circular dependencies in `depends_on` (A -> B -> A)
    """
    doc_map = {doc.id: doc for doc in docs}
    visited: set[str] = set()
    visiting: set[str] = set()

    def has_cycle(node_id: str) -> bool:
        visiting.add(node_id)
        doc = doc_map.get(node_id)
        if doc:
            for dep in doc.metadata.relations.depends_on:
                if dep in visiting:
                    return True
                if dep not in visited and dep in doc_map:
                    if has_cycle(dep):
                        return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False

    for doc in docs:
        if doc.id not in visited:
            if has_cycle(doc.id):
                if raise_on_error:
                    raise OKFValidationError(
                        f"Circular dependency detected involving document '{doc.id}'."
                    )
                return False

    return True


__all__ = ["validate_okf_document", "validate_okf_semantic_relations"]
