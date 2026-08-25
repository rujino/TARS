"""Multi-tenant file storage manager for OKF markdown documents with atomic write and security sandboxing."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import uuid
from pathlib import Path
from typing import Protocol

from tars.config import get_settings
from tars.core.okf.models import OKFDocument
from tars.core.okf.parser import parse_okf_text
from tars.core.okf.serializer import serialize_okf_document

# Regex slug identifier for user_id and okf_id
ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


class StorageError(Exception):
    """Base exception for file storage layer errors."""


class StorageSecurityError(StorageError, ValueError):
    """Raised when an invalid identifier or path traversal security violation is detected."""


class StoragePathTraversalError(StorageSecurityError):
    """Raised specifically when a resolved path escapes the tenant sandbox directory."""


class StorageFileNotFoundError(StorageError, FileNotFoundError):
    """Raised when a requested OKF file is not found on disk."""


class StorageIOError(StorageError, OSError):
    """Raised on disk read/write/rename I/O failure."""


# Aliases for backward and test compatibility
OKFStorageError = StorageError
OKFSecurityError = StorageSecurityError
OKFPathTraversalError = StoragePathTraversalError
OKFNotFoundError = StorageFileNotFoundError


class IFileStorageManager(Protocol):
    """Protocol contract for multi-tenant file storage manager."""

    async def save_okf_file(self, user_id: str, doc: OKFDocument) -> Path:
        """Atomically serialize and save OKF document to user's isolated storage."""
        ...

    async def read_okf_file(self, user_id: str, okf_id: str) -> OKFDocument:
        """Read and parse OKF document from user's storage."""
        ...

    async def delete_okf_file(self, user_id: str, okf_id: str) -> bool:
        """Delete OKF document file from user's storage."""
        ...

    async def list_okf_files(self, user_id: str) -> list[OKFDocument]:
        """List all valid OKF documents in user's storage."""
        ...

    async def exists_okf_file(self, user_id: str, okf_id: str) -> bool:
        """Check if an OKF document exists in user's storage."""
        ...

    async def get_file_hash(self, user_id: str, okf_id: str) -> str:
        """Calculate and return SHA-256 checksum of an OKF file."""
        ...


class FileStorageManager:
    """Concrete implementation of IFileStorageManager with atomic writes and sandboxed isolation."""

    def __init__(
        self,
        base_storage_dir: Path | str | None = None,
        storage_root: Path | str | None = None,
        base_dir: Path | str | None = None,
    ) -> None:
        target_dir = base_dir if base_dir is not None else (storage_root if storage_root is not None else base_storage_dir)
        if target_dir is None:
            target_dir = get_settings().storage_dir
        self._base_dir = Path(target_dir).resolve()

    @property
    def base_dir(self) -> Path:
        """Return resolved base storage directory."""
        return self._base_dir

    @property
    def storage_root(self) -> Path:
        """Alias for base_dir."""
        return self._base_dir

    def _validate_id(self, identifier: str, name: str = "Identifier") -> str:
        """Validate slug identifier against path traversal and malicious characters."""
        if not identifier or not isinstance(identifier, str):
            raise StorageSecurityError(f"{name} must be a non-empty string.")
        if "\0" in identifier:
            raise StorageSecurityError(f"Null byte detected in {name}.")
        clean_id = identifier.strip()
        if not ID_PATTERN.match(clean_id):
            raise StorageSecurityError(
                f"Invalid {name} '{clean_id}'. Must match pattern ^[a-zA-Z0-9_-]{{1,128}}$."
            )
        return clean_id

    def get_user_wikis_dir(self, user_id: str) -> Path:
        """Get resolved and validated directory path for a user's wikis."""
        valid_user_id = self._validate_id(user_id, "user_id")
        user_dir = (self._base_dir / "users" / valid_user_id / "wikis").resolve()

        # Security sandbox check: ensure user_dir is strictly inside self._base_dir
        if not user_dir.is_relative_to(self._base_dir):
            raise StoragePathTraversalError(
                f"Path traversal detected: user directory '{user_dir}' is outside base '{self._base_dir}'."
            )
        return user_dir

    def get_file_path(self, user_id: str, okf_id: str) -> Path:
        """Get resolved and sandboxed file path for a specific user OKF document."""
        user_wikis_dir = self.get_user_wikis_dir(user_id)
        valid_okf_id = self._validate_id(okf_id, "okf_id")
        target_path = (user_wikis_dir / f"{valid_okf_id}.md").resolve()

        # Security check: target path must be directly inside user_wikis_dir
        if not target_path.is_relative_to(user_wikis_dir):
            raise StoragePathTraversalError(
                f"Path traversal detected: target path '{target_path}' is outside user sandbox '{user_wikis_dir}'."
            )
        return target_path

    @staticmethod
    def compute_sha256(content: str | bytes) -> str:
        """Calculate hexadecimal SHA-256 hash of text or bytes."""
        if isinstance(content, str):
            content_bytes = content.encode("utf-8")
        else:
            content_bytes = content
        return hashlib.sha256(content_bytes).hexdigest()

    async def save_okf_file(self, user_id: str, doc: OKFDocument) -> Path:
        """Atomically save OKF document to disk using temporary file replacement."""
        okf_id = doc.metadata.id
        target_path = self.get_file_path(user_id, okf_id)
        user_wikis_dir = target_path.parent

        def _sync_write() -> Path:
            user_wikis_dir.mkdir(parents=True, exist_ok=True)
            serialized_text = serialize_okf_document(doc)
            tmp_path = user_wikis_dir / f".tmp.{uuid.uuid4().hex}"

            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write(serialized_text)
                    f.flush()
                    os.fsync(f.fileno())

                # Atomic replacement on POSIX and modern Windows filesystems
                os.replace(tmp_path, target_path)
            except Exception as e:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
                raise StorageIOError(f"Failed to atomically write OKF file '{target_path}': {e}") from e

            return target_path

        return await asyncio.to_thread(_sync_write)

    async def read_okf_file(self, user_id: str, okf_id: str) -> OKFDocument:
        """Read and parse OKF document from user's isolated storage."""
        target_path = self.get_file_path(user_id, okf_id)

        def _sync_read() -> OKFDocument:
            if not target_path.exists() or not target_path.is_file():
                raise StorageFileNotFoundError(
                    f"OKF document '{okf_id}' not found for user '{user_id}' at '{target_path}'."
                )

            try:
                raw_text = target_path.read_text(encoding="utf-8")
            except Exception as e:
                raise StorageIOError(f"Failed to read file '{target_path}': {e}") from e

            doc = parse_okf_text(raw_text, file_path=str(target_path))
            return doc

        return await asyncio.to_thread(_sync_read)

    async def delete_okf_file(self, user_id: str, okf_id: str) -> bool:
        """Delete OKF document file from user's storage."""
        target_path = self.get_file_path(user_id, okf_id)

        def _sync_delete() -> bool:
            if not target_path.exists():
                return False
            try:
                target_path.unlink()
                return True
            except Exception as e:
                raise StorageIOError(f"Failed to delete file '{target_path}': {e}") from e

        return await asyncio.to_thread(_sync_delete)

    async def exists_okf_file(self, user_id: str, okf_id: str) -> bool:
        """Check whether OKF document file exists."""
        target_path = self.get_file_path(user_id, okf_id)
        return await asyncio.to_thread(lambda: target_path.exists() and target_path.is_file())

    async def list_okf_files(self, user_id: str) -> list[OKFDocument]:
        """List all valid OKF documents in user's wiki directory."""
        user_wikis_dir = self.get_user_wikis_dir(user_id)

        def _sync_list() -> list[OKFDocument]:
            if not user_wikis_dir.exists() or not user_wikis_dir.is_dir():
                return []

            documents: list[OKFDocument] = []
            for path in sorted(user_wikis_dir.glob("*.md")):
                # Skip temp files or hidden files
                if path.name.startswith("."):
                    continue
                try:
                    raw_text = path.read_text(encoding="utf-8")
                    doc = parse_okf_text(raw_text, file_path=str(path))
                    documents.append(doc)
                except Exception:
                    # Ignore corrupted or unparseable files during bulk listing
                    continue
            return documents

        return await asyncio.to_thread(_sync_list)

    async def get_file_hash(self, user_id: str, okf_id: str) -> str:
        """Compute SHA-256 hash of an OKF document file."""
        target_path = self.get_file_path(user_id, okf_id)

        def _sync_hash() -> str:
            if not target_path.exists():
                raise StorageFileNotFoundError(
                    f"OKF document '{okf_id}' not found for hash calculation."
                )
            raw_bytes = target_path.read_bytes()
            return hashlib.sha256(raw_bytes).hexdigest()

        return await asyncio.to_thread(_sync_hash)


__all__ = [
    "FileStorageManager",
    "IFileStorageManager",
    "OKFNotFoundError",
    "OKFPathTraversalError",
    "OKFSecurityError",
    "OKFStorageError",
    "StorageError",
    "StorageFileNotFoundError",
    "StorageIOError",
    "StoragePathTraversalError",
    "StorageSecurityError",
]
