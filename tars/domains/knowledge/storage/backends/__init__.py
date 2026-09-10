"""OKF Storage Factory Module."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from tars.domains.knowledge.storage.backends.base import OKFStorageBase
from tars.domains.knowledge.storage.backends.local import LocalFileStorage
from tars.domains.knowledge.storage.backends.s3 import SeaweedS3Storage


@lru_cache(maxsize=1)
def get_okf_storage() -> OKFStorageBase:
    """Factory function returning the configured OKF storage singleton."""
    backend_type = os.getenv("TARS_STORAGE_BACKEND", "local").lower()

    if backend_type == "s3":
        endpoint_url = os.getenv(
            "TARS_S3_ENDPOINT_URL", "http://seaweedfs-s3.tars.svc.cluster.local:8333"
        )
        access_key = os.getenv("TARS_S3_ACCESS_KEY", "tars-admin-access-key")
        secret_key = os.getenv("TARS_S3_SECRET_KEY", "tars-admin-secret-key-at-least-16-chars")
        bucket_name = os.getenv("TARS_S3_BUCKET_NAME", "tars-okf")
        region_name = os.getenv("TARS_S3_REGION", "us-east-1")

        return SeaweedS3Storage(
            endpoint_url=endpoint_url,
            access_key=access_key,
            secret_key=secret_key,
            bucket_name=bucket_name,
            region_name=region_name,
        )

    # Default to Local File Storage
    storage_dir = Path(os.getenv("TARS_STORAGE_DIR", "./storage/okf"))
    return LocalFileStorage(base_dir=storage_dir)


__all__ = [
    "OKFStorageBase",
    "SeaweedS3Storage",
    "LocalFileStorage",
    "get_okf_storage",
]
