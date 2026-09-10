"""SeaweedFS / S3 Compatible OKF Storage Adapter using aioboto3."""

from __future__ import annotations

import posixpath
from typing import Any

import aioboto3
from botocore.exceptions import ClientError

from tars.domains.knowledge.spec.errors import (
    OKFDocumentAlreadyExistsError,
    OKFNotFoundError,
    OKFStorageError,
)
from tars.domains.knowledge.spec.models import OKFDocument, OKFMetadata
from tars.domains.knowledge.spec.parser import parse_okf_text
from tars.domains.knowledge.spec.serializer import serialize_okf_document
from tars.domains.knowledge.storage.backends.base import OKFStorageBase


class SeaweedS3Storage(OKFStorageBase):
    """Asynchronous S3 storage adapter optimized for SeaweedFS."""

    def __init__(
        self,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket_name: str = "tars-okf",
        region_name: str = "us-east-1",
    ) -> None:
        self.endpoint_url = endpoint_url
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket_name = bucket_name
        self.region_name = region_name
        self._session = aioboto3.Session()

    def _get_client(self) -> Any:
        return self._session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region_name,
        )

    def _build_key(self, user_id: str, relative_path: str) -> str:
        clean_path = posixpath.normpath(relative_path.lstrip("/"))
        if clean_path.startswith("..") or "/../" in clean_path:
            raise OKFStorageError(f"Path traversal detected: '{relative_path}'")
        return posixpath.join("users", user_id, clean_path)

    async def initialize(self) -> None:
        """Ensure the target OKF bucket exists in SeaweedFS."""
        async with self._get_client() as s3:
            try:
                await s3.head_bucket(Bucket=self.bucket_name)
            except ClientError as exc:
                error_code = exc.response.get("Error", {}).get("Code")
                if error_code in ("404", "NoSuchBucket", "NotFound"):
                    await s3.create_bucket(Bucket=self.bucket_name)
                else:
                    raise OKFStorageError(
                        f"Failed to initialize S3 bucket '{self.bucket_name}': {exc}"
                    ) from exc

    async def exists(self, user_id: str, relative_path: str) -> bool:
        s3_key = self._build_key(user_id, relative_path)
        async with self._get_client() as s3:
            try:
                await s3.head_object(Bucket=self.bucket_name, Key=s3_key)
                return True
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                    return False
                raise OKFStorageError(
                    f"Failed to check existence for '{s3_key}': {exc}", path=s3_key
                ) from exc

    async def read_document(self, user_id: str, relative_path: str) -> OKFDocument:
        s3_key = self._build_key(user_id, relative_path)
        async with self._get_client() as s3:
            try:
                response = await s3.get_object(Bucket=self.bucket_name, Key=s3_key)
                async with response["Body"] as stream:
                    content_bytes = await stream.read()
                    raw_text = content_bytes.decode("utf-8")
                    doc = parse_okf_text(raw_text)
                    doc.file_path = relative_path
                    return doc
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404", "NotFound"):
                    raise OKFNotFoundError(
                        f"Document not found: '{relative_path}'", path=s3_key
                    ) from exc
                raise OKFStorageError(
                    f"Error reading S3 object '{s3_key}': {exc}", path=s3_key
                ) from exc

    async def write_document(
        self,
        user_id: str,
        relative_path: str,
        document: OKFDocument,
        overwrite: bool = True,
    ) -> str:
        s3_key = self._build_key(user_id, relative_path)
        if not overwrite and await self.exists(user_id, relative_path):
            raise OKFDocumentAlreadyExistsError(
                f"Document already exists at '{relative_path}'", path=s3_key
            )

        serialized_text = serialize_okf_document(document)
        async with self._get_client() as s3:
            try:
                await s3.put_object(
                    Bucket=self.bucket_name,
                    Key=s3_key,
                    Body=serialized_text.encode("utf-8"),
                    ContentType="text/markdown; charset=utf-8",
                )
                document.file_path = relative_path
                return s3_key
            except ClientError as exc:
                raise OKFStorageError(
                    f"Error writing S3 object '{s3_key}': {exc}", path=s3_key
                ) from exc

    async def delete_document(self, user_id: str, relative_path: str) -> bool:
        s3_key = self._build_key(user_id, relative_path)
        if not await self.exists(user_id, relative_path):
            return False
        async with self._get_client() as s3:
            try:
                await s3.delete_object(Bucket=self.bucket_name, Key=s3_key)
                return True
            except ClientError as exc:
                raise OKFStorageError(
                    f"Error deleting S3 object '{s3_key}': {exc}", path=s3_key
                ) from exc

    async def list_documents(
        self,
        user_id: str,
        category_dir: str | None = None,
    ) -> list[OKFMetadata]:
        prefix = (
            posixpath.join("users", user_id, category_dir.lstrip("/"))
            if category_dir
            else f"users/{user_id}/"
        )
        if not prefix.endswith("/"):
            prefix += "/"

        results: list[OKFMetadata] = []
        async with self._get_client() as s3:
            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if key.endswith("index.md") or not key.endswith(".md"):
                        continue
                    # Read and extract metadata
                    rel_path = key.removeprefix(f"users/{user_id}/")
                    try:
                        doc = await self.read_document(user_id, rel_path)
                        results.append(doc.metadata)
                    except Exception:
                        continue
        return results

    async def generate_index(
        self,
        user_id: str,
        category_dir: str | None = None,
    ) -> str:
        """Generate a progressive disclosure index.md listing title and descriptions."""
        docs = await self.list_documents(user_id, category_dir)
        heading = f"# Knowledge Index: {category_dir or 'Root'}\n\n"
        items: list[str] = []
        for meta in docs:
            desc = meta.description or meta.title
            items.append(f"* [{meta.title}]({meta.id}.md) - {desc}")

        content = heading + "\n".join(items) + "\n"
        index_rel_path = posixpath.join(category_dir, "index.md") if category_dir else "index.md"
        s3_key = self._build_key(user_id, index_rel_path)

        async with self._get_client() as s3:
            await s3.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=content.encode("utf-8"),
                ContentType="text/markdown; charset=utf-8",
            )
        return content
