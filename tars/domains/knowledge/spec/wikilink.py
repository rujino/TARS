"""OKF 2.0 Obsidian-Compatible Wiki-Link Parser & Formatter."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

# Matches [[target_id]] or [[target_id|Display Label]]
WIKILINK_PATTERN = re.compile(r"\[\[([^\]\|]+)(?:\|([^\]]+))?\]\]")


class WikiLink(BaseModel):
    """Represents an Obsidian-style [[target_id|label]] link extracted from markdown."""

    model_config = ConfigDict(frozen=True)

    target_id: str = Field(..., description="Target document slug ID")
    label: str | None = Field(default=None, description="Optional custom display text")
    raw: str = Field(default="", description="Original matched raw string")

    def __str__(self) -> str:
        if self.label:
            return f"[[{self.target_id}|{self.label}]]"
        return f"[[{self.target_id}]]"


def extract_wikilinks(text: str) -> list[WikiLink]:
    """Extract all [[wiki-link]] instances from markdown text.

    Args:
        text: Markdown content to scan.

    Returns:
        List of unique WikiLink objects preserving document order.
    """
    if not text:
        return []

    seen: set[tuple[str, str | None]] = set()
    links: list[WikiLink] = []

    for match in WIKILINK_PATTERN.finditer(text):
        target = match.group(1).strip()
        raw_label = match.group(2)
        label = raw_label.strip() if raw_label is not None else None

        if not target:
            continue

        key = (target, label)
        if key not in seen:
            seen.add(key)
            links.append(
                WikiLink(
                    target_id=target,
                    label=label,
                    raw=match.group(0),
                )
            )

    return links


def extract_target_ids(text: str) -> list[str]:
    """Extract unique target document IDs from all wikilinks in text."""
    links = extract_wikilinks(text)
    return list(dict.fromkeys(link.target_id for link in links))


def format_wikilink(target_id: str, label: str | None = None) -> str:
    """Format a target_id and optional label into standard [[wiki-link]] syntax."""
    clean_target = target_id.strip()
    if label and label.strip():
        return f"[[{clean_target}|{label.strip()}]]"
    return f"[[{clean_target}]]"


def replace_wikilink_target(text: str, old_id: str, new_id: str) -> str:
    """Replace occurrences of old target ID with new target ID in wikilinks while preserving labels."""
    if not text or not old_id or not new_id:
        return text

    def _replace_match(m: re.Match[str]) -> str:
        current_target = m.group(1).strip()
        label = m.group(2)
        if current_target == old_id:
            if label is not None:
                return f"[[{new_id}|{label.strip()}]]"
            return f"[[{new_id}]]"
        return m.group(0)

    return WIKILINK_PATTERN.sub(_replace_match, text)


__all__ = [
    "WIKILINK_PATTERN",
    "WikiLink",
    "extract_target_ids",
    "extract_wikilinks",
    "format_wikilink",
    "replace_wikilink_target",
]
