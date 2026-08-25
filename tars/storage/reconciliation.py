"""Storage-DB bidirectional reconciliation and differential integrity sync engine."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.core.okf.models import OKFDocument
from tars.core.okf.parser import parse_okf_text
from tars.db.models import UserWikiIndex
from tars.storage.manager import FileStorageManager, IFileStorageManager


@dataclass
class ReconciliationResult:
    """Summary of reconciliation sync execution for a specific user."""

    user_id: str
    scanned_files_count: int = 0
    inserted_count: int = 0
    created_count: int = 0
    updated_count: int = 0
    deleted_count: int = 0
    unchanged_count: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        """True if sync completed with no errors."""
        return len(self.errors) == 0


@dataclass
class IntegrityViolation:
    """Detail of a single integrity discrepancy between storage and DB."""

    user_id: str
    okf_id: str
    violation_type: str  # "MISSING_IN_DB" | "MISSING_IN_STORAGE" | "HASH_MISMATCH"
    details: str


class StorageDBReconciliationEngine:
    """Engine responsible for bidirectional synchronization between markdown files and DB metadata index."""

    def __init__(self, storage_manager: IFileStorageManager | None = None) -> None:
        self.storage: IFileStorageManager = storage_manager or FileStorageManager()

    async def reconcile_user(
        self,
        session_or_user_id: Any = None,
        user_id_or_session: Any = None,
        *,
        user_id: str | None = None,
        session: AsyncSession | None = None,
    ) -> ReconciliationResult:
        """Perform full differential sync for a single user between disk and DB.

        Supports flexible argument ordering: (user_id, session) or (session, user_id).
        """
        # Disambiguate arguments
        actual_session: AsyncSession | None = session
        actual_user_id: str | None = user_id

        for arg in (session_or_user_id, user_id_or_session):
            if isinstance(arg, AsyncSession):
                actual_session = arg
            elif isinstance(arg, str):
                actual_user_id = arg

        if actual_session is None or actual_user_id is None:
            raise ValueError("Both 'session' (AsyncSession) and 'user_id' (str) must be provided.")

        result = ReconciliationResult(user_id=actual_user_id)

        # 1. Scan user's wiki directory
        if isinstance(self.storage, FileStorageManager):
            user_wikis_dir = self.storage.get_user_wikis_dir(actual_user_id)
        else:
            user_wikis_dir = Path("./storage/users") / actual_user_id / "wikis"

        def _scan_disk() -> dict[str, tuple[OKFDocument, str, Path]]:
            if not user_wikis_dir.exists() or not user_wikis_dir.is_dir():
                return {}
            disk_docs: dict[str, tuple[OKFDocument, str, Path]] = {}
            for file_path in user_wikis_dir.glob("*.md"):
                if file_path.name.startswith("."):
                    continue
                try:
                    raw_text = file_path.read_text(encoding="utf-8")
                    file_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
                    doc = parse_okf_text(raw_text, file_path=str(file_path))
                    disk_docs[doc.metadata.id] = (doc, file_hash, file_path)
                except Exception as ex:
                    result.errors.append(f"Failed to parse disk file '{file_path.name}': {ex}")
            return disk_docs

        disk_items = await asyncio.to_thread(_scan_disk)
        result.scanned_files_count = len(disk_items)

        # 2. Fetch existing DB records for user
        query = select(UserWikiIndex).where(UserWikiIndex.user_id == actual_user_id)
        db_exec = await actual_session.execute(query)
        db_records: dict[str, UserWikiIndex] = {r.okf_id: r for r in db_exec.scalars().all()}

        # 3. Compare disk vs DB
        disk_okf_ids = set(disk_items.keys())
        db_okf_ids = set(db_records.keys())

        # A. Insert new files found on disk
        to_insert_ids = disk_okf_ids - db_okf_ids
        for okf_id in to_insert_ids:
            doc, file_hash, file_path = disk_items[okf_id]
            meta = doc.metadata
            new_record = UserWikiIndex(
                user_id=actual_user_id,
                okf_id=meta.id,
                okf_version=meta.okf_version,
                type=str(meta.type.value if hasattr(meta.type, "value") else meta.type),
                title=meta.title,
                category=meta.category,
                tags=list(meta.tags),
                importance=str(
                    meta.importance.value if hasattr(meta.importance, "value") else meta.importance
                ),
                source=str(meta.source.value if hasattr(meta.source, "value") else meta.source),
                relations=meta.relations.model_dump(),
                file_path=str(file_path),
                file_hash=file_hash,
                created_at=meta.created_at,
                updated_at=meta.updated_at,
            )
            actual_session.add(new_record)
            result.inserted_count += 1
            result.created_count += 1

        # B. Check existing records for updates
        common_ids = disk_okf_ids & db_okf_ids
        for okf_id in common_ids:
            doc, file_hash, file_path = disk_items[okf_id]
            db_record = db_records[okf_id]
            meta = doc.metadata

            # If SHA-256 hash or updated_at changed, update DB metadata
            if db_record.file_hash != file_hash or db_record.updated_at != meta.updated_at:
                db_record.okf_version = meta.okf_version
                db_record.type = str(meta.type.value if hasattr(meta.type, "value") else meta.type)
                db_record.title = meta.title
                db_record.category = meta.category
                db_record.tags = list(meta.tags)
                db_record.importance = str(
                    meta.importance.value if hasattr(meta.importance, "value") else meta.importance
                )
                db_record.source = str(
                    meta.source.value if hasattr(meta.source, "value") else meta.source
                )
                db_record.relations = meta.relations.model_dump()
                db_record.file_path = str(file_path)
                db_record.file_hash = file_hash
                db_record.updated_at = meta.updated_at
                result.updated_count += 1
            else:
                result.unchanged_count += 1

        # C. Delete orphan DB records (file removed from storage)
        to_delete_ids = db_okf_ids - disk_okf_ids
        if to_delete_ids:
            delete_stmt = delete(UserWikiIndex).where(
                UserWikiIndex.user_id == actual_user_id,
                UserWikiIndex.okf_id.in_(to_delete_ids),
            )
            await actual_session.execute(delete_stmt)
            result.deleted_count += len(to_delete_ids)

        await actual_session.flush()
        return result

    async def sync_single_document(
        self,
        user_id: str,
        doc: OKFDocument,
        file_path: Path | str,
        file_hash: str,
        session: AsyncSession,
    ) -> UserWikiIndex:
        """Inline fast synchronization after a single file write."""
        meta = doc.metadata
        query = select(UserWikiIndex).where(
            UserWikiIndex.user_id == user_id,
            UserWikiIndex.okf_id == meta.id,
        )
        record = (await session.execute(query)).scalar_one_or_none()

        if record is None:
            record = UserWikiIndex(
                user_id=user_id,
                okf_id=meta.id,
                okf_version=meta.okf_version,
                type=str(meta.type.value if hasattr(meta.type, "value") else meta.type),
                title=meta.title,
                category=meta.category,
                tags=list(meta.tags),
                importance=str(
                    meta.importance.value if hasattr(meta.importance, "value") else meta.importance
                ),
                source=str(meta.source.value if hasattr(meta.source, "value") else meta.source),
                relations=meta.relations.model_dump(),
                file_path=str(file_path),
                file_hash=file_hash,
                created_at=meta.created_at,
                updated_at=meta.updated_at,
            )
            session.add(record)
        else:
            record.okf_version = meta.okf_version
            record.type = str(meta.type.value if hasattr(meta.type, "value") else meta.type)
            record.title = meta.title
            record.category = meta.category
            record.tags = list(meta.tags)
            record.importance = str(
                meta.importance.value if hasattr(meta.importance, "value") else meta.importance
            )
            record.source = str(meta.source.value if hasattr(meta.source, "value") else meta.source)
            record.relations = meta.relations.model_dump()
            record.file_path = str(file_path)
            record.file_hash = file_hash
            record.updated_at = meta.updated_at

        await session.flush()
        return record

    async def delete_single_document_metadata(
        self, user_id: str, okf_id: str, session: AsyncSession
    ) -> bool:
        """Inline fast deletion of DB index record after a file delete."""
        stmt = delete(UserWikiIndex).where(
            UserWikiIndex.user_id == user_id,
            UserWikiIndex.okf_id == okf_id,
        )
        res = await session.execute(stmt)
        await session.flush()
        rowcount = getattr(res, "rowcount", 0)
        return bool(rowcount and rowcount > 0)

    async def verify_user_integrity(
        self, user_id: str, session: AsyncSession
    ) -> list[IntegrityViolation]:
        """Perform a dry-run audit of integrity discrepancies without modifying DB."""
        violations: list[IntegrityViolation] = []

        if isinstance(self.storage, FileStorageManager):
            user_wikis_dir = self.storage.get_user_wikis_dir(user_id)
        else:
            user_wikis_dir = Path("./storage/users") / user_id / "wikis"

        def _scan_disk() -> dict[str, str]:
            if not user_wikis_dir.exists():
                return {}
            disk_hashes: dict[str, str] = {}
            for p in user_wikis_dir.glob("*.md"):
                if p.name.startswith("."):
                    continue
                try:
                    text = p.read_text(encoding="utf-8")
                    doc = parse_okf_text(text, file_path=str(p))
                    disk_hashes[doc.metadata.id] = hashlib.sha256(text.encode("utf-8")).hexdigest()
                except Exception:
                    continue
            return disk_hashes

        disk_items = await asyncio.to_thread(_scan_disk)
        query = select(UserWikiIndex).where(UserWikiIndex.user_id == user_id)
        db_records = {r.okf_id: r for r in (await session.execute(query)).scalars().all()}

        disk_ids = set(disk_items.keys())
        db_ids = set(db_records.keys())

        for okf_id in disk_ids - db_ids:
            violations.append(
                IntegrityViolation(
                    user_id=user_id,
                    okf_id=okf_id,
                    violation_type="MISSING_IN_DB",
                    details="File exists on disk but is absent from DB index.",
                )
            )

        for okf_id in db_ids - disk_ids:
            violations.append(
                IntegrityViolation(
                    user_id=user_id,
                    okf_id=okf_id,
                    violation_type="MISSING_IN_STORAGE",
                    details="Record exists in DB index but .md file is missing from disk.",
                )
            )

        for okf_id in disk_ids & db_ids:
            disk_hash = disk_items[okf_id]
            db_hash = db_records[okf_id].file_hash
            if disk_hash != db_hash:
                violations.append(
                    IntegrityViolation(
                        user_id=user_id,
                        okf_id=okf_id,
                        violation_type="HASH_MISMATCH",
                        details=f"File hash on disk ({disk_hash[:8]}...) != DB hash ({db_hash[:8]}...).",
                    )
                )

        return violations


async def reconcile_user_storage(
    session: AsyncSession,
    user_id: str,
    storage_manager: FileStorageManager | None = None,
) -> ReconciliationResult:
    """Convenience helper for reconciling a user's storage with DB."""
    engine = StorageDBReconciliationEngine(storage_manager=storage_manager)
    return await engine.reconcile_user(session=session, user_id=user_id)


__all__ = [
    "IntegrityViolation",
    "ReconciliationResult",
    "StorageDBReconciliationEngine",
    "reconcile_user_storage",
]
