"""Local Filesystem OKF Storage Adapter."""

from __future__ import annotations

from pathlib import Path

from tars.domains.knowledge.spec.errors import (
    OKFDocumentAlreadyExistsError,
    OKFNotFoundError,
    OKFStorageError,
)
from tars.domains.knowledge.spec.models import OKFDocument, OKFMetadata
from tars.domains.knowledge.spec.parser import parse_okf_text
from tars.domains.knowledge.spec.serializer import serialize_okf_document
from tars.domains.knowledge.storage.backends.base import OKFStorageBase


class LocalFileStorage(OKFStorageBase):
    """Local disk storage adapter for development and unit testing."""

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir).resolve()

    def _resolve_path(self, user_id: str, relative_path: str) -> Path:
        clean_path = relative_path.lstrip("/")
        user_root = (self.base_dir / "users" / user_id).resolve()
        target = (user_root / clean_path).resolve()
        # Security: Prevent Directory Traversal outside user root
        try:
            target.relative_to(user_root)
        except ValueError as exc:
            raise OKFStorageError(
                f"Path traversal detected: '{relative_path}'", path=str(target)
            ) from exc
        return target

    async def initialize(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def exists(self, user_id: str, relative_path: str) -> bool:
        return self._resolve_path(user_id, relative_path).is_file()

    async def read_document(self, user_id: str, relative_path: str) -> OKFDocument:
        path = self._resolve_path(user_id, relative_path)
        if not path.is_file():
            raise OKFNotFoundError(f"Document not found: '{relative_path}'", path=str(path))
        text = path.read_text(encoding="utf-8")
        doc = parse_okf_text(text)
        doc.file_path = relative_path
        return doc

    async def write_document(
        self,
        user_id: str,
        relative_path: str,
        document: OKFDocument,
        overwrite: bool = True,
    ) -> str:
        path = self._resolve_path(user_id, relative_path)
        if not overwrite and path.exists():
            raise OKFDocumentAlreadyExistsError(
                f"Document already exists: '{relative_path}'", path=str(path)
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = serialize_okf_document(document)
        path.write_text(serialized, encoding="utf-8")
        document.file_path = relative_path
        return str(path)

    async def delete_document(self, user_id: str, relative_path: str) -> bool:
        path = self._resolve_path(user_id, relative_path)
        if not path.is_file():
            return False
        path.unlink()
        return True

    async def list_documents(
        self, user_id: str, category_dir: str | None = None
    ) -> list[OKFMetadata]:
        target_dir = self.base_dir / "users" / user_id
        if category_dir:
            target_dir = target_dir / category_dir.lstrip("/")
        if not target_dir.is_dir():
            return []

        results: list[OKFMetadata] = []
        for file in sorted(target_dir.glob("*.md")):
            if file.name == "index.md":
                continue
            try:
                doc = parse_okf_text(file.read_text(encoding="utf-8"))
                results.append(doc.metadata)
            except Exception:
                continue
        return results

    async def generate_index(self, user_id: str, category_dir: str | None = None) -> str:
        docs = await self.list_documents(user_id, category_dir)
        heading = f"# Knowledge Index: {category_dir or 'Root'}\n\n"
        items = [f"* [{m.title}]({m.id}.md) - {m.description or m.title}" for m in docs]
        content = heading + "\n".join(items) + "\n"
        index_rel = f"{category_dir}/index.md" if category_dir else "index.md"
        index_path = self._resolve_path(user_id, index_rel)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(content, encoding="utf-8")
        return content
