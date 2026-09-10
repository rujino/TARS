# SeaweedFS 기반 k3s 스토리지 인프라 구축 및 OKF 스토리지 어댑터 상세 설계 명세서

본 문서는 TARS의 지식 엔진인 **OKF(Open Knowledge Format)** 마크다운 문서 및 지식 그래프를 분산 환경에서 안정적으로 영속화하기 위해, **k3s(경량 쿠버네티스) 인프라에 SeaweedFS(S3 호환 분산 오브젝트 스토리지)를 구축하고 백엔드(`tars/core/okf/storage/`) 어댑터를 연동하기 위한 완전한 상세 설계 명세서**입니다.

이 문서는 사용자가 구현 단계에서 사전에 면밀히 검토(Review)하고, 바로 코드로 전환할 수 있도록 **실제 매니페스트 및 소스 코드 레벨의 상세 명세**를 제공합니다.

---

## 1. 아키텍처 개요 및 설계 동기 (Architecture Overview & Motivation)

### 1.1 해결하려는 핵심 과제 (TARS 다중 파드 공유 스토리지 문제)
- **현상**: TARS 백엔드는 무중단 롤링 업데이트 및 부하 분산을 위해 **`replicas: 3`**으로 배포됩니다 (`k8s/03-backend.yaml`).
- **한계**: 기존 k3s의 `local-path` 스토리지 클래스는 `ReadWriteOnce(RWO)`만 지원하므로, 여러 노드/파드가 동일한 디렉토리를 동시에 공유 마운트하여 마크다운 파일을 쓰고 읽을 수 없습니다.
- **해결책**: 백엔드 파드가 파일시스템을 직접 마운트하지 않고, **클러스터 내부 S3 REST API(`http://seaweedfs-s3.tars.svc.cluster.local:8333`)**를 통해 사용자별 OKF 지식 문서를 읽고 쓰도록 추상화합니다.

### 1.2 왜 SeaweedFS인가?
1. **완전한 오픈소스 (Apache 2.0 라이선스)**: MinIO(AGPL v3)와 달리 기업 상용화 및 사내 배포 시 라이선스 전파/공개 의무가 없습니다.
2. **작은 파일(Small Files, 1~10KB) 초고속 I/O**: Facebook Haystack 기반 구조로, 수만 개의 마크다운 파일이 빈번하게 생성/수정되는 OKF 특성에 최적화되어 있습니다.
3. **단일 바이너리/초경량 Pod**: Master, Volume Server, Filer, S3 Gateway를 단일 컨테이너 프로세스로 구동할 수 있어 k3s의 가용 리소스(메모리 100~300MB)를 극도로 절약합니다.

---

## 2. K3s 인프라 배포 매니페스트 명세

### 2.1 신규 생성 파일: `k8s/07-seaweedfs.yaml`
k3s 기본 스토리지 클래스(`local-path`)와 `tars` 네임스페이스에 최적화된 올인원 매니페스트입니다.

```yaml
# ==============================================================================
# SeaweedFS for TARS OKF Storage (k3s Production Manifest)
# Components: Master + Volume Server + Filer (Embedded LevelDB) + S3 Gateway
# ==============================================================================
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: seaweedfs-data-pvc
  namespace: tars
  labels:
    app: seaweedfs
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: local-path
  resources:
    requests:
      storage: 20Gi
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: seaweedfs-config
  namespace: tars
  labels:
    app: seaweedfs
data:
  # Filer 디렉토리 메타데이터 및 S3 인증 설정
  seaweed_s3_config.json: |
    {
      "identities": [
        {
          "name": "tars-admin",
          "credentials": [
            {
              "accessKey": "tars-admin-access-key",
              "secretKey": "tars-admin-secret-key-at-least-16-chars"
            }
          ],
          "actions": [
            "Admin",
            "Read",
            "Write",
            "List",
            "Tagging"
          ]
        }
      ]
    }
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: seaweedfs
  namespace: tars
  labels:
    app: seaweedfs
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: seaweedfs
  template:
    metadata:
      labels:
        app: seaweedfs
    spec:
      containers:
        - name: seaweedfs
          image: chrislusf/seaweedfs:latest
          imagePullPolicy: IfNotPresent
          args:
            - "server"
            - "-dir=/data"
            - "-s3"
            - "-s3.port=8333"
            - "-s3.config=/etc/seaweedfs/seaweed_s3_config.json"
            - "-volume.max=50"
          ports:
            - containerPort: 8333
              name: s3-api
              protocol: TCP
            - containerPort: 9333
              name: master
              protocol: TCP
            - containerPort: 8888
              name: filer
              protocol: TCP
            - containerPort: 8080
              name: volume
              protocol: TCP
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 1000m
              memory: 1Gi
          readinessProbe:
            httpGet:
              path: /status
              port: 9333
            initialDelaySeconds: 5
            periodSeconds: 10
            timeoutSeconds: 3
          livenessProbe:
            httpGet:
              path: /status
              port: 9333
            initialDelaySeconds: 15
            periodSeconds: 20
            timeoutSeconds: 3
          volumeMounts:
            - name: seaweedfs-data
              mountPath: /data
            - name: seaweedfs-config-volume
              mountPath: /etc/seaweedfs
      volumes:
        - name: seaweedfs-data
          persistentVolumeClaim:
            claimName: seaweedfs-data-pvc
        - name: seaweedfs-config-volume
          configMap:
            name: seaweedfs-config
---
apiVersion: v1
kind: Service
metadata:
  name: seaweedfs-s3
  namespace: tars
  labels:
    app: seaweedfs
spec:
  type: ClusterIP
  ports:
    - port: 8333
      targetPort: 8333
      name: s3-api
    - port: 8888
      targetPort: 8888
      name: filer
    - port: 9333
      targetPort: 9333
      name: master
  selector:
    app: seaweedfs
```

---

### 2.2 기존 설정 파일 갱신 명세

#### (1) `k8s/01-config.yaml` 추가 항목
```yaml
data:
  # ... 기존 설정 유지 ...
  TARS_STORAGE_BACKEND: "s3" # "s3" 또는 "local"
  TARS_S3_ENDPOINT_URL: "http://seaweedfs-s3.tars.svc.cluster.local:8333"
  TARS_S3_BUCKET_NAME: "tars-okf"
  TARS_S3_REGION: "us-east-1"
```

#### (2) `k8s/01-secret.example.yaml` 추가 항목
```yaml
stringData:
  # ... 기존 시크릿 유지 ...
  TARS_S3_ACCESS_KEY: "tars-admin-access-key"
  TARS_S3_SECRET_KEY: "tars-admin-secret-key-at-least-16-chars"
```

#### (3) `k8s/deploy.sh` 실행 순서 추가
```bash
# k8s/02-db.yaml 적용 직후에 seaweedfs 적용
kubectl apply -f "${PROJECT_ROOT}/k8s/02-db.yaml"
echo "📦 Applying SeaweedFS S3 Storage..."
kubectl apply -f "${PROJECT_ROOT}/k8s/07-seaweedfs.yaml"
kubectl apply -f "${PROJECT_ROOT}/k8s/03-backend.yaml"
```

---

## 3. OKF 버킷 및 디렉토리 구조 표준

- **버킷명**: `tars-okf`
- **사용자 격리 Key 패턴**: `users/{user_id}/...`

```text
s3://tars-okf/
└── users/
    └── {user_id}/
        ├── index.md                      # 최상위 지식 색인 (Progressive Disclosure)
        ├── log.md                        # 지식 변경 타임라인
        ├── preferences/
        │   ├── index.md                  # 카테고리별 색인
        │   └── work-style.md             # 개별 OKF 문서
        ├── projects/
        │   ├── index.md
        │   └── tars.md
        ├── policies/
        │   ├── index.md
        │   └── deploy-freeze.md
        └── contacts/
            ├── index.md
            └── coworkers.md
```

---

## 4. 백엔드 스토리지 어댑터 코드 설계 명세 (`tars/core/okf/storage/`)

TARS 백엔드 코드가 특정 스토리지 구현체(S3, 로컬 파일시스템 등)에 종속되지 않도록 **추상화 계층(Interface)과 팩토리 패턴**을 적용합니다.

### 4.1 디렉토리 구조
```text
tars/core/okf/
├── __init__.py
├── errors.py              # [수정] 스토리지 관련 예외 추가
├── models.py              # 기존 OKF Pydantic 모델
├── parser.py              # 기존 파서
├── serializer.py          # 기존 시리얼라이저
├── validator.py           # 기존 검증기
└── storage/               # [신규 생성] 스토리지 어댑터 패키지
    ├── __init__.py        # Factory: get_okf_storage()
    ├── base.py            # 추상 클래스 (OKFStorageBase)
    ├── s3.py              # SeaweedFS / S3 비동기 어댑터 (aioboto3)
    └── local.py           # 로컬 파일시스템 어댑터 (개발/테스트용)
```

---

### 4.2 `tars/core/okf/errors.py` 확장 명세
스토리지 작업 중 발생하는 에러 계층을 정의합니다.

```python
# tars/core/okf/errors.py 에 추가할 클래스

class OKFStorageError(OKFError):
    """Raised when an underlying storage read/write operation fails."""
    def __init__(self, message: str, path: str | None = None) -> None:
        super().__init__(message)
        self.path = path


class OKFNotFoundError(OKFStorageError):
    """Raised when a requested OKF document or index does not exist."""


class OKFDocumentAlreadyExistsError(OKFStorageError):
    """Raised when attempting to create a document that already exists without overwrite flag."""
```

---

### 4.3 추상 인터페이스: `tars/core/okf/storage/base.py`

```python
"""OKF Storage Abstract Base Class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tars.core.okf.models import OKFDocument, OKFMetadata


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
```

---

### 4.4 S3/SeaweedFS 비동기 구현체: `tars/core/okf/storage/s3.py`

```python
"""SeaweedFS / S3 Compatible OKF Storage Adapter using aioboto3."""

from __future__ import annotations

import posixpath
from typing import Any
import aioboto3
from botocore.exceptions import ClientError

from tars.core.okf.errors import (
    OKFDocumentAlreadyExistsError,
    OKFNotFoundError,
    OKFStorageError,
)
from tars.core.okf.models import OKFDocument, OKFMetadata
from tars.core.okf.parser import parse_okf_text
from tars.core.okf.serializer import serialize_okf_document
from tars.core.okf.storage.base import OKFStorageBase


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
        clean_path = relative_path.lstrip("/")
        return posixpath.join("users", user_id, clean_path)

    async def initialize(self) -> None:
        """Ensure the target OKF bucket exists in SeaweedFS."""
        async with self._get_client() as s3:
            try:
                await s3.head_bucket(Bucket=self.bucket_name)
            except ClientError as exc:
                error_code = exc.response.get("Error", {}).get("Code")
                if error_code in ("404", "NoSuchBucket"):
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
                if exc.response.get("Error", {}).get("Code") == "404":
                    return False
                raise OKFStorageError(f"Failed to check existence for '{s3_key}': {exc}", path=s3_key) from exc

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
                if exc.response.get("Error", {}).get("Code") == "NoSuchKey":
                    raise OKFNotFoundError(f"Document not found: '{relative_path}'", path=s3_key) from exc
                raise OKFStorageError(f"Error reading S3 object '{s3_key}': {exc}", path=s3_key) from exc

    async def write_document(
        self,
        user_id: str,
        relative_path: str,
        document: OKFDocument,
        overwrite: bool = True,
    ) -> str:
        s3_key = self._build_key(user_id, relative_path)
        if not overwrite and await self.exists(user_id, relative_path):
            raise OKFDocumentAlreadyExistsError(f"Document already exists at '{relative_path}'", path=s3_key)

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
                raise OKFStorageError(f"Error writing S3 object '{s3_key}': {exc}", path=s3_key) from exc

    async def delete_document(self, user_id: str, relative_path: str) -> bool:
        s3_key = self._build_key(user_id, relative_path)
        if not await self.exists(user_id, relative_path):
            return False
        async with self._get_client() as s3:
            try:
                await s3.delete_object(Bucket=self.bucket_name, Key=s3_key)
                return True
            except ClientError as exc:
                raise OKFStorageError(f"Error deleting S3 object '{s3_key}': {exc}", path=s3_key) from exc

    async def list_documents(
        self,
        user_id: str,
        category_dir: str | None = None,
    ) -> list[OKFMetadata]:
        prefix = posixpath.join("users", user_id, category_dir.lstrip("/")) if category_dir else f"users/{user_id}/"
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
            desc = getattr(meta, "description", None) or meta.title
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
```

---

### 4.5 로컬 파일시스템 어댑터: `tars/core/okf/storage/local.py`
오프라인 로컬 개발 및 유닛 테스트(pytest) 격리를 위한 구현체입니다.

```python
"""Local Filesystem OKF Storage Adapter."""

from __future__ import annotations

from pathlib import Path
from tars.core.okf.errors import OKFDocumentAlreadyExistsError, OKFNotFoundError, OKFStorageError
from tars.core.okf.models import OKFDocument, OKFMetadata
from tars.core.okf.parser import parse_okf_text
from tars.core.okf.serializer import serialize_okf_document
from tars.core.okf.storage.base import OKFStorageBase


class LocalFileStorage(OKFStorageBase):
    """Local disk storage adapter for development and unit testing."""

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir).resolve()

    def _resolve_path(self, user_id: str, relative_path: str) -> Path:
        target = (self.base_dir / "users" / user_id / relative_path.lstrip("/")).resolve()
        # Security: Prevent Directory Traversal
        if not str(target).startswith(str(self.base_dir)):
            raise OKFStorageError(f"Path traversal detected: '{relative_path}'")
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
            raise OKFDocumentAlreadyExistsError(f"Document already exists: '{relative_path}'", path=str(path))
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

    async def list_documents(self, user_id: str, category_dir: str | None = None) -> list[OKFMetadata]:
        target_dir = self.base_dir / "users" / user_id
        if category_dir:
            target_dir = target_dir / category_dir.lstrip("/")
        if not target_dir.is_dir():
            return []

        results: list[OKFMetadata] = []
        for file in target_dir.glob("*.md"):
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
        items = [f"* [{m.title}]({m.id}.md) - {m.title}" for m in docs]
        content = heading + "\n".join(items) + "\n"
        index_path = self._resolve_path(user_id, f"{category_dir}/index.md" if category_dir else "index.md")
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(content, encoding="utf-8")
        return content
```

---

### 4.6 스토리지 팩토리: `tars/core/okf/storage/__init__.py`

```python
"""OKF Storage Factory Module."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from tars.core.okf.storage.base import OKFStorageBase
from tars.core.okf.storage.local import LocalFileStorage
from tars.core.okf.storage.s3 import SeaweedS3Storage


@lru_cache(maxsize=1)
def get_okf_storage() -> OKFStorageBase:
    """Factory function returning the configured OKF storage singleton."""
    backend_type = os.getenv("TARS_STORAGE_BACKEND", "local").lower()

    if backend_type == "s3":
        endpoint_url = os.getenv("TARS_S3_ENDPOINT_URL", "http://seaweedfs-s3.tars.svc.cluster.local:8333")
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
```

---

## 5. 의존성 패키지 명세 (`pyproject.toml`)

비동기 S3 통신을 위해 `pyproject.toml`의 `dependencies`에 다음 패키지를 추가해야 합니다:

```toml
dependencies = [
    # ... 기존 의존성 ...
    "aioboto3>=13.0.0",
    "boto3>=1.34.0",
]
```

---

## 6. 구현 및 배포 검토 체크리스트 (Review & Execution Checklist)

나중에 작업을 진행하실 때 다음 순서대로 체크하며 반영하시면 됩니다:

- [ ] **1단계: 의존성 추가**
  - `pyproject.toml`에 `aioboto3` 추가 후 `uv sync` 또는 `pip install -e .` 실행
- [ ] **2단계: 설정 및 시크릿 갱신**
  - `k8s/01-config.yaml`에 `TARS_STORAGE_BACKEND`, `TARS_S3_ENDPOINT_URL`, `TARS_S3_BUCKET_NAME` 반영
  - `k8s/01-secret.example.yaml` 및 `01-secret.yaml`에 `TARS_S3_ACCESS_KEY`, `TARS_S3_SECRET_KEY` 반영
- [ ] **3단계: SeaweedFS 매니페스트 생성 및 배포 스크립트 반영**
  - `k8s/07-seaweedfs.yaml` 파일 생성
  - `k8s/deploy.sh`에 `kubectl apply -f k8s/07-seaweedfs.yaml` 추가
- [ ] **4단계: 백엔드 스토리지 어댑터 코드 작성**
  - `tars/core/okf/errors.py`에 예외 클래스 추가
  - `tars/core/okf/storage/` 패키지 생성 (`base.py`, `s3.py`, `local.py`, `__init__.py`)
- [ ] **5단계: 유닛 테스트 및 클러스터 통합 검증**
  - `tests/tier1_unit/test_okf_storage.py`를 작성하여 `LocalFileStorage` 및 모킹된 `SeaweedS3Storage` 단위 테스트 통과 확인
  - k3s 클러스터 배포 후 `aws --endpoint-url=http://localhost:8333 s3 ls`로 파드 간 동시 읽기/쓰기 동작 검증
