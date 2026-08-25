"""OKF (Open Knowledge Format) Pydantic v2 Data Models."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


class OKFType(StrEnum):
    """Functional classification of OKF knowledge."""

    CONCEPT = "concept"
    RULE = "rule"
    ENTITY = "entity"
    PROCEDURE = "procedure"
    PREFERENCE = "preference"


class OKFImportance(StrEnum):
    """Importance and dynamic slicing priority level."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class OKFSource(StrEnum):
    """Knowledge origin and extraction source."""

    MANUAL = "manual"
    AUTO_EXTRACTED = "auto_extracted"
    SYSTEM = "system"


class OKFRelations(BaseModel):
    """Graph relations with other OKF documents."""

    model_config = ConfigDict(extra="forbid")

    depends_on: list[str] = Field(default_factory=list, description="Prerequisite document IDs")
    related_to: list[str] = Field(default_factory=list, description="Related document IDs")

    @field_validator("depends_on", "related_to", mode="before")
    @classmethod
    def normalize_string_list(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, (list, set, tuple)):
            seen: set[str] = set()
            result: list[str] = []
            for item in v:
                cleaned = str(item).strip()
                if cleaned and cleaned not in seen:
                    seen.add(cleaned)
                    result.append(cleaned)
            return result
        if isinstance(v, str):
            items = [item.strip() for item in v.split(",") if item.strip()]
            return list(dict.fromkeys(items))
        return []


class OKFMetadata(BaseModel):
    """Structured YAML Frontmatter metadata for OKF documents."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    okf_version: str = Field(default="1.0", description="OKF Specification version")
    id: str = Field(..., min_length=1, max_length=128, description="Unique slug ID")
    type: OKFType = Field(..., description="Knowledge type")
    title: str = Field(..., min_length=1, max_length=256, description="Document title")
    category: str | None = Field(default=None, max_length=64, description="High-level category")
    tags: list[str] = Field(default_factory=list, description="Keyword tags")
    importance: OKFImportance = Field(default=OKFImportance.MEDIUM, description="Importance level")
    source: OKFSource = Field(default=OKFSource.MANUAL, description="Creation source")
    relations: OKFRelations = Field(default_factory=OKFRelations, description="Relation graph")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Creation timestamp"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Last updated timestamp"
    )

    @field_validator("id")
    @classmethod
    def validate_id_slug(cls, v: str) -> str:
        clean_id = v.strip()
        if not ID_PATTERN.match(clean_id):
            raise ValueError(
                f"Invalid OKF document ID '{clean_id}'. Must match pattern '^[a-zA-Z0-9_-]{{1,128}}$'"
            )
        return clean_id

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        clean_title = v.strip()
        if not clean_title:
            raise ValueError("Title must not be empty or whitespace only.")
        if len(clean_title) > 256:
            raise ValueError("Title length must not exceed 256 characters.")
        return clean_title

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, (list, set, tuple)):
            seen: set[str] = set()
            result: list[str] = []
            for item in v:
                tag = str(item).strip().lower()
                if tag and tag not in seen:
                    seen.add(tag)
                    result.append(tag)
            return result
        if isinstance(v, str):
            tags = [t.strip().lower() for t in v.split(",") if t.strip()]
            return list(dict.fromkeys(tags))
        return []

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def ensure_utc_datetime(cls, v: Any) -> datetime:
        if v is None:
            return datetime.now(UTC)
        if isinstance(v, datetime):
            if v.tzinfo is None:
                return v.replace(tzinfo=UTC)
            return v.astimezone(UTC)
        if isinstance(v, date):
            return datetime(v.year, v.month, v.day, tzinfo=UTC)
        if isinstance(v, str):
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        raise ValueError(f"Cannot parse datetime value: {v!r}")


# Alias for backward and test specification compatibility
OKFFrontmatter = OKFMetadata


class OKFDocument(BaseModel):
    """Complete 2-layer OKF Document containing Metadata and Markdown Content."""

    model_config = ConfigDict(extra="forbid")

    metadata: OKFMetadata = Field(..., description="Structured metadata")
    content: str = Field(default="", description="Markdown body content")
    file_path: str | None = Field(default=None, description="Relative or absolute file path")
    raw_hash: str | None = Field(default=None, description="SHA-256 checksum of raw content")

    @model_validator(mode="before")
    @classmethod
    def reconcile_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Support 'frontmatter' as alias for 'metadata'
            if "metadata" not in data and "frontmatter" in data:
                data["metadata"] = data.pop("frontmatter")
            # Support 'body' as alias for 'content'
            if "content" not in data and "body" in data:
                data["content"] = data.pop("body")
        return data

    @property
    def frontmatter(self) -> OKFMetadata:
        """Alias for metadata."""
        return self.metadata

    @property
    def body(self) -> str:
        """Alias for content."""
        return self.content

    @property
    def id(self) -> str:
        return self.metadata.id

    @property
    def title(self) -> str:
        return self.metadata.title

    @property
    def type(self) -> OKFType:
        return self.metadata.type

    @property
    def importance(self) -> OKFImportance:
        return self.metadata.importance

    @property
    def tags(self) -> list[str]:
        return self.metadata.tags

    @property
    def category(self) -> str | None:
        return self.metadata.category
