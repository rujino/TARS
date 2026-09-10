"""OKF Storage Abstract Base Class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tars.domains.knowledge.spec.models import OKFDocument, OKFMetadata


class OKFStorageBase(ABC):
    """Abstract interface defining required storage operations for OKF documents."""

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize storage backend (e.g. ensure bucket exists or dirs are created)."""
        pass

    @abstractmethod
    async def read_document(self, user_id: str, relative_path: str) -> OKFDocument:
        """Read and parse an OKF document from the storage backend.

        Args:
            user_id: Unique user identifier.
            relative_path: Document path within user root (e.g. 'preferences/work-style.md').

        Returns:
            Parsed OKFDocument instance.

        Raises:
            OKFNotFoundError: If the document does not exist.
            OKFStorageError: If reading or parsing fails.
        """
        pass

    @abstractmethod
    async def write_document(
        self,
        user_id: str,
        relative_path: str,
        document: OKFDocument,
        overwrite: bool = True,
    ) -> str:
        """Serialize and persist an OKF document.

        Args:
            user_id: Unique user identifier.
            relative_path: Target path (e.g. 'policies/deploy.md').
            document: OKFDocument instance to persist.
            overwrite: Whether to overwrite if the file already exists.

        Returns:
            Canonical storage path/key.

        Raises:
            OKFDocumentAlreadyExistsError: If overwrite is False and doc exists.
            OKFStorageError: If writing fails.
        """
        pass

    @abstractmethod
    async def delete_document(self, user_id: str, relative_path: str) -> bool:
        """Delete an OKF document.

        Returns:
            True if deleted, False if not found.
        """
        pass

    @abstractmethod
    async def exists(self, user_id: str, relative_path: str) -> bool:
        """Check if an OKF document exists."""
        pass

    @abstractmethod
    async def list_documents(
        self,
        user_id: str,
        category_dir: str | None = None,
    ) -> list[OKFMetadata]:
        """List metadata for documents in the specified directory.
        Used by the agent for progressive disclosure navigation.
        """
        pass

    @abstractmethod
    async def generate_index(
        self,
        user_id: str,
        category_dir: str | None = None,
    ) -> str:
        """Generate or refresh index.md for progressive disclosure.

        Returns:
            Generated Markdown content of index.md.
        """
        pass
