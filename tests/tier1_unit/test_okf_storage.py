"""Tier 1 Unit Tests: OKF Storage Adapters (Local & SeaweedFS/S3) & Factory."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from botocore.exceptions import ClientError

from tars.core.okf.errors import (
    OKFDocumentAlreadyExistsError,
    OKFNotFoundError,
    OKFStorageError,
)
from tars.core.okf.models import (
    OKFDocument,
    OKFImportance,
    OKFMetadata,
    OKFRelations,
    OKFSource,
    OKFType,
)
from tars.core.okf.serializer import serialize_okf_document
from tars.core.okf.storage import (
    LocalFileStorage,
    SeaweedS3Storage,
    get_okf_storage,
)


@pytest.fixture
def sample_doc() -> OKFDocument:
    """Fixture returning a standard OKF document for storage testing."""
    metadata = OKFMetadata(
        okf_version="1.0",
        id="test-doc-001",
        type=OKFType.PREFERENCE,
        title="Test Preference Document",
        description="A sample document for testing OKF storage adapters.",
        category="preferences",
        tags=["unit-test", "storage"],
        importance=OKFImportance.HIGH,
        source=OKFSource.MANUAL,
        relations=OKFRelations(depends_on=[], related_to=[]),
    )
    return OKFDocument(
        metadata=metadata,
        content="# Test Content\n\nThis is a sample document for testing storage.",
    )


# ==============================================================================
# 1. LocalFileStorage Unit Tests
# ==============================================================================


class TestLocalFileStorage:
    """Unit tests for LocalFileStorage adapter."""

    @pytest.mark.asyncio
    async def test_initialize_creates_directory(self, tmp_path: Path) -> None:
        target_dir = tmp_path / "custom_okf_dir"
        storage = LocalFileStorage(base_dir=target_dir)
        assert not target_dir.exists()

        await storage.initialize()
        assert target_dir.is_dir()

    @pytest.mark.asyncio
    async def test_write_and_read_document(
        self, tmp_path: Path, sample_doc: OKFDocument
    ) -> None:
        storage = LocalFileStorage(base_dir=tmp_path)
        await storage.initialize()

        user_id = "user-123"
        rel_path = "preferences/test-doc-001.md"

        # Write
        saved_path = await storage.write_document(user_id, rel_path, sample_doc)
        assert Path(saved_path).is_file()
        assert sample_doc.file_path == rel_path

        # Exists
        assert await storage.exists(user_id, rel_path) is True
        assert await storage.exists(user_id, "non_existent.md") is False

        # Read
        loaded_doc = await storage.read_document(user_id, rel_path)
        assert loaded_doc.metadata.id == sample_doc.metadata.id
        assert loaded_doc.metadata.title == sample_doc.metadata.title
        assert loaded_doc.metadata.description == sample_doc.metadata.description
        assert "# Test Content" in loaded_doc.content
        assert loaded_doc.file_path == rel_path

    @pytest.mark.asyncio
    async def test_write_overwrite_protection(
        self, tmp_path: Path, sample_doc: OKFDocument
    ) -> None:
        storage = LocalFileStorage(base_dir=tmp_path)
        await storage.initialize()

        user_id = "user-123"
        rel_path = "preferences/test-doc-001.md"

        await storage.write_document(user_id, rel_path, sample_doc)

        # Attempt write with overwrite=False
        with pytest.raises(OKFDocumentAlreadyExistsError) as exc_info:
            await storage.write_document(user_id, rel_path, sample_doc, overwrite=False)
        assert "already exists" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_read_not_found(self, tmp_path: Path) -> None:
        storage = LocalFileStorage(base_dir=tmp_path)
        await storage.initialize()

        with pytest.raises(OKFNotFoundError) as exc_info:
            await storage.read_document("user-123", "missing/file.md")
        assert "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_delete_document(
        self, tmp_path: Path, sample_doc: OKFDocument
    ) -> None:
        storage = LocalFileStorage(base_dir=tmp_path)
        await storage.initialize()

        user_id = "user-123"
        rel_path = "policies/policy-01.md"

        # Delete non-existent
        assert await storage.delete_document(user_id, rel_path) is False

        # Create and delete
        await storage.write_document(user_id, rel_path, sample_doc)
        assert await storage.exists(user_id, rel_path) is True

        assert await storage.delete_document(user_id, rel_path) is True
        assert await storage.exists(user_id, rel_path) is False

    @pytest.mark.asyncio
    async def test_list_and_generate_index(
        self, tmp_path: Path, sample_doc: OKFDocument
    ) -> None:
        storage = LocalFileStorage(base_dir=tmp_path)
        await storage.initialize()

        user_id = "user-456"

        # Initially empty
        docs = await storage.list_documents(user_id, "preferences")
        assert docs == []

        # Add 2 documents
        doc1 = sample_doc
        doc2 = OKFDocument(
            metadata=OKFMetadata(
                id="pref-002",
                type=OKFType.PREFERENCE,
                title="Second Preference",
                description="Another preference item",
            ),
            content="Content 2",
        )

        await storage.write_document(user_id, "preferences/test-doc-001.md", doc1)
        await storage.write_document(user_id, "preferences/pref-002.md", doc2)

        docs = await storage.list_documents(user_id, "preferences")
        assert len(docs) == 2
        titles = {d.title for d in docs}
        assert "Test Preference Document" in titles
        assert "Second Preference" in titles

        # Generate index
        index_content = await storage.generate_index(user_id, "preferences")
        assert "# Knowledge Index: preferences" in index_content
        assert "* [Test Preference Document](test-doc-001.md) - A sample document" in index_content
        assert "* [Second Preference](pref-002.md) - Another preference item" in index_content

        # Verify index.md is not listed in list_documents
        docs_after = await storage.list_documents(user_id, "preferences")
        assert len(docs_after) == 2

    @pytest.mark.asyncio
    async def test_path_traversal_prevention(self, tmp_path: Path) -> None:
        storage = LocalFileStorage(base_dir=tmp_path)
        await storage.initialize()

        with pytest.raises(OKFStorageError) as exc_info:
            await storage.read_document("user-1", "../../etc/passwd")
        assert "traversal" in str(exc_info.value).lower()


# ==============================================================================
# 2. SeaweedS3Storage Unit Tests (AsyncMocked)
# ==============================================================================


class AsyncContextManagerMock:
    """Helper async context manager for mocking aioboto3 client context."""

    def __init__(self, client: AsyncMock) -> None:
        self.client = client

    async def __aenter__(self) -> AsyncMock:
        return self.client

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass


class TestSeaweedS3Storage:
    """Unit tests for SeaweedS3Storage adapter using mocked aioboto3 client."""

    @pytest.fixture
    def mock_client(self) -> AsyncMock:
        client = AsyncMock()
        return client

    @pytest.fixture
    def s3_storage(self, mock_client: AsyncMock) -> SeaweedS3Storage:
        storage = SeaweedS3Storage(
            endpoint_url="http://mock-seaweedfs:8333",
            access_key="mock-access-key",
            secret_key="mock-secret-key",
            bucket_name="tars-okf",
            region_name="us-east-1",
        )
        storage._get_client = MagicMock(return_value=AsyncContextManagerMock(mock_client))  # type: ignore[method-assign]
        return storage

    @pytest.mark.asyncio
    async def test_initialize_creates_bucket_when_missing(
        self, s3_storage: SeaweedS3Storage, mock_client: AsyncMock
    ) -> None:
        # Simulate 404 NoSuchBucket on head_bucket
        client_err = ClientError(
            error_response={"Error": {"Code": "404", "Message": "Not Found"}},
            operation_name="HeadBucket",
        )
        mock_client.head_bucket.side_effect = client_err

        await s3_storage.initialize()

        mock_client.head_bucket.assert_awaited_once_with(Bucket="tars-okf")
        mock_client.create_bucket.assert_awaited_once_with(Bucket="tars-okf")

    @pytest.mark.asyncio
    async def test_initialize_bucket_already_exists(
        self, s3_storage: SeaweedS3Storage, mock_client: AsyncMock
    ) -> None:
        mock_client.head_bucket.return_value = {}

        await s3_storage.initialize()

        mock_client.head_bucket.assert_awaited_once_with(Bucket="tars-okf")
        mock_client.create_bucket.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_exists(
        self, s3_storage: SeaweedS3Storage, mock_client: AsyncMock
    ) -> None:
        # Document exists
        mock_client.head_object.return_value = {}
        assert await s3_storage.exists("u1", "doc.md") is True

        # Document not found
        client_err = ClientError(
            error_response={"Error": {"Code": "404", "Message": "Not Found"}},
            operation_name="HeadObject",
        )
        mock_client.head_object.side_effect = client_err
        assert await s3_storage.exists("u1", "missing.md") is False

    @pytest.mark.asyncio
    async def test_write_document_success(
        self, s3_storage: SeaweedS3Storage, sample_doc: OKFDocument, mock_client: AsyncMock
    ) -> None:
        s3_storage.exists = AsyncMock(return_value=False)  # type: ignore[method-assign]

        key = await s3_storage.write_document("u1", "prefs/theme.md", sample_doc)
        assert key == "users/u1/prefs/theme.md"
        mock_client.put_object.assert_awaited_once()
        call_kwargs = mock_client.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "tars-okf"
        assert call_kwargs["Key"] == "users/u1/prefs/theme.md"
        assert call_kwargs["ContentType"] == "text/markdown; charset=utf-8"
        assert b"test-doc-001" in call_kwargs["Body"]

    @pytest.mark.asyncio
    async def test_write_document_already_exists_conflict(
        self, s3_storage: SeaweedS3Storage, sample_doc: OKFDocument
    ) -> None:
        s3_storage.exists = AsyncMock(return_value=True)  # type: ignore[method-assign]

        with pytest.raises(OKFDocumentAlreadyExistsError):
            await s3_storage.write_document(
                "u1", "prefs/theme.md", sample_doc, overwrite=False
            )

    @pytest.mark.asyncio
    async def test_read_document_success(
        self, s3_storage: SeaweedS3Storage, sample_doc: OKFDocument, mock_client: AsyncMock
    ) -> None:
        serialized = serialize_okf_document(sample_doc)
        body_stream = AsyncMock()
        body_stream.read.return_value = serialized.encode("utf-8")

        stream_ctx = AsyncMock()
        stream_ctx.__aenter__.return_value = body_stream
        stream_ctx.__aexit__.return_value = None

        mock_client.get_object.return_value = {"Body": stream_ctx}

        doc = await s3_storage.read_document("u1", "prefs/test-doc-001.md")
        assert doc.metadata.id == sample_doc.metadata.id
        assert doc.metadata.title == sample_doc.metadata.title
        assert doc.file_path == "prefs/test-doc-001.md"

    @pytest.mark.asyncio
    async def test_read_document_not_found(
        self, s3_storage: SeaweedS3Storage, mock_client: AsyncMock
    ) -> None:
        client_err = ClientError(
            error_response={"Error": {"Code": "NoSuchKey", "Message": "The specified key does not exist."}},
            operation_name="GetObject",
        )
        mock_client.get_object.side_effect = client_err

        with pytest.raises(OKFNotFoundError):
            await s3_storage.read_document("u1", "missing.md")

    @pytest.mark.asyncio
    async def test_delete_document(
        self, s3_storage: SeaweedS3Storage, mock_client: AsyncMock
    ) -> None:
        s3_storage.exists = AsyncMock(return_value=True)  # type: ignore[method-assign]
        res = await s3_storage.delete_document("u1", "to_delete.md")
        assert res is True
        mock_client.delete_object.assert_awaited_once_with(
            Bucket="tars-okf", Key="users/u1/to_delete.md"
        )

        s3_storage.exists = AsyncMock(return_value=False)  # type: ignore[method-assign]
        res2 = await s3_storage.delete_document("u1", "missing.md")
        assert res2 is False

    @pytest.mark.asyncio
    async def test_generate_index(
        self, s3_storage: SeaweedS3Storage, sample_doc: OKFDocument, mock_client: AsyncMock
    ) -> None:
        s3_storage.list_documents = AsyncMock(return_value=[sample_doc.metadata])  # type: ignore[method-assign]

        content = await s3_storage.generate_index("u1", "preferences")
        assert "# Knowledge Index: preferences" in content
        assert "* [Test Preference Document](test-doc-001.md)" in content
        mock_client.put_object.assert_awaited_once()
        call_kwargs = mock_client.put_object.call_args[1]
        assert call_kwargs["Key"] == "users/u1/preferences/index.md"


# ==============================================================================
# 3. Factory Unit Tests
# ==============================================================================


def test_get_okf_storage_local(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    get_okf_storage.cache_clear()
    monkeypatch.setenv("TARS_STORAGE_BACKEND", "local")
    monkeypatch.setenv("TARS_STORAGE_DIR", str(tmp_path))

    storage = get_okf_storage()
    assert isinstance(storage, LocalFileStorage)
    assert storage.base_dir == tmp_path
    get_okf_storage.cache_clear()


def test_get_okf_storage_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    get_okf_storage.cache_clear()
    monkeypatch.setenv("TARS_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("TARS_S3_ENDPOINT_URL", "http://custom-s3:9000")
    monkeypatch.setenv("TARS_S3_ACCESS_KEY", "custom-key")
    monkeypatch.setenv("TARS_S3_SECRET_KEY", "custom-secret")
    monkeypatch.setenv("TARS_S3_BUCKET_NAME", "my-bucket")
    monkeypatch.setenv("TARS_S3_REGION", "ap-northeast-2")

    storage = get_okf_storage()
    assert isinstance(storage, SeaweedS3Storage)
    assert storage.endpoint_url == "http://custom-s3:9000"
    assert storage.access_key == "custom-key"
    assert storage.secret_key == "custom-secret"
    assert storage.bucket_name == "my-bucket"
    assert storage.region_name == "ap-northeast-2"
    get_okf_storage.cache_clear()
