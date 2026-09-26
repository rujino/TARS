"""Media and character asset serving endpoints with S3 and local storage support."""

from __future__ import annotations

import mimetypes
import os
import re
from pathlib import Path
from typing import Any, Literal

import aioboto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, Response, status

from tars.config import get_settings

router = APIRouter(prefix="/assets", tags=["Assets"])

# Regex for allowed filename to prevent path traversal
SAFE_FILENAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+\.(png|webp|jpg|jpeg|svg)$")
VALID_SPEAKERS = {"vera", "miu"}


@router.get("/characters/{speaker}/{filename}")
async def get_character_asset(
    speaker: Literal["vera", "miu"],
    filename: str,
) -> Response:
    """Serve character sprite images from object storage (SeaweedFS/S3) or local filesystem.

    Returns the image with appropriate Content-Type and HTTP caching headers.
    """
    if speaker not in VALID_SPEAKERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid speaker '{speaker}'. Must be one of {list(VALID_SPEAKERS)}",
        )

    clean_filename = filename.strip()
    if not SAFE_FILENAME_PATTERN.match(clean_filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid asset filename. Must match pattern ^[a-zA-Z0-9_-]+\\.(png|webp|jpg|jpeg|svg)$",
        )

    settings = get_settings()
    content_type, _ = mimetypes.guess_type(clean_filename)
    if not content_type:
        content_type = "image/png"

    # 1. S3 / SeaweedFS Object Storage Backend
    if settings.storage_backend == "s3":
        s3_key = f"characters/{speaker}/{clean_filename}"
        session = aioboto3.Session()
        try:
            async with session.client(
                "s3",
                endpoint_url=settings.s3_endpoint_url,
                aws_access_key_id=settings.s3_access_key,
                aws_secret_access_key=settings.s3_secret_key,
                region_name=settings.s3_region,
            ) as s3:
                response = await s3.get_object(
                    Bucket=settings.s3_assets_bucket_name,
                    Key=s3_key,
                )
                async with response["Body"] as stream:
                    image_bytes = await stream.read()
                    return Response(
                        content=image_bytes,
                        media_type=content_type,
                        headers={
                            "Cache-Control": "public, max-age=86400, stale-while-revalidate=3600",
                        },
                    )
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")
            if error_code in ("NoSuchKey", "404", "NotFound", "NoSuchBucket"):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Character asset not found in object storage: {s3_key}",
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error reading asset from object storage: {exc}",
            ) from exc

    # 2. Local Filesystem Storage Fallback
    local_path = (
        Path(settings.storage_dir) / "assets" / "characters" / speaker / clean_filename
    ).resolve()

    # Path traversal protection
    expected_parent = (Path(settings.storage_dir) / "assets" / "characters" / speaker).resolve()
    if not local_path.is_relative_to(expected_parent):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Path traversal detected",
        )

    if not local_path.exists() or not local_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Character asset not found locally: {local_path.name}",
        )

    image_bytes = local_path.read_bytes()
    return Response(
        content=image_bytes,
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=86400, stale-while-revalidate=3600",
        },
    )
