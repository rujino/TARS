"""OKF (Open Knowledge Format) Serializer Engine."""

from __future__ import annotations

from datetime import UTC
from typing import Any

import yaml

from tars.core.okf.errors import OKFSerializationError
from tars.core.okf.models import OKFDocument


def serialize_okf_document(doc: OKFDocument) -> str:
    """Serialize an OKFDocument instance into a canonical YAML Frontmatter + Markdown string.

    Args:
        doc: OKFDocument to serialize.

    Returns:
        Standard UTF-8 encoded markdown string.

    Raises:
        OKFSerializationError: If serialization fails.
    """
    try:
        meta = doc.metadata

        # Format datetimes consistently in UTC ISO 8601
        created_at_str = (
            meta.created_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            if meta.created_at.tzinfo
            else meta.created_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        updated_at_str = (
            meta.updated_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            if meta.updated_at.tzinfo
            else meta.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        )

        frontmatter_dict: dict[str, Any] = {
            "okf_version": meta.okf_version,
            "id": meta.id,
            "type": meta.type.value if hasattr(meta.type, "value") else str(meta.type),
            "title": meta.title,
        }

        if meta.category is not None:
            frontmatter_dict["category"] = meta.category

        frontmatter_dict["tags"] = list(meta.tags)
        frontmatter_dict["importance"] = (
            meta.importance.value if hasattr(meta.importance, "value") else str(meta.importance)
        )
        frontmatter_dict["source"] = (
            meta.source.value if hasattr(meta.source, "value") else str(meta.source)
        )

        frontmatter_dict["relations"] = {
            "depends_on": list(meta.relations.depends_on),
            "related_to": list(meta.relations.related_to),
        }

        frontmatter_dict["created_at"] = created_at_str
        frontmatter_dict["updated_at"] = updated_at_str

        yaml_content = yaml.safe_dump(
            frontmatter_dict,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )

        body = doc.content
        if body:
            return f"---\n{yaml_content}---\n\n{body}"
        return f"---\n{yaml_content}---\n"

    except Exception as exc:
        raise OKFSerializationError(f"Failed to serialize OKFDocument '{doc.id}': {exc}") from exc


__all__ = ["serialize_okf_document"]
