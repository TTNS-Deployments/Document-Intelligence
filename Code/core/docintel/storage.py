"""Blob storage abstraction: a local folder or Azure Blob Storage (and Azurite).

Besides plain reads and writes it supports what the app needs instead of a database:

* blob metadata, returned by listing (the History page is built from it);
* ETags with conditional writes (``if_match`` / ``if_none_match``), used for optimistic concurrency on the daily
  page budget and to make sure two processes never claim the same job.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import shutil
import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .config import Settings


class PreconditionFailed(Exception):
    """A conditional write lost the race (the blob changed, or already exists)."""


@dataclass
class BlobInfo:
    name: str
    size: int
    etag: str
    created: datetime
    last_modified: datetime
    metadata: dict = field(default_factory=dict)


class BlobStore(ABC):
    @abstractmethod
    def put_bytes(self, container: str, name: str, data: bytes, content_type: str | None = None,
                  metadata: dict | None = None, if_match: str | None = None, if_none_match: bool = False) -> str:
        """Write a blob and return its new ETag. Raises PreconditionFailed when a condition is not met."""

    @abstractmethod
    def get_with_etag(self, container: str, name: str) -> tuple[bytes, str]: ...

    @abstractmethod
    def get_info(self, container: str, name: str) -> BlobInfo: ...

    @abstractmethod
    def exists(self, container: str, name: str) -> bool: ...

    @abstractmethod
    def delete(self, container: str, name: str) -> bool:
        """Delete a blob. Returns False when it did not exist."""

    @abstractmethod
    def list_info(self, container: str, prefix: str = "") -> list[BlobInfo]: ...

    @abstractmethod
    def iter_chunks(self, container: str, name: str, chunk_size: int = 1 << 20) -> Iterator[bytes]: ...

    def get_bytes(self, container: str, name: str) -> bytes:
        return self.get_with_etag(container, name)[0]

    def list(self, container: str, prefix: str = "") -> list[str]:
        return [b.name for b in self.list_info(container, prefix)]

    def put_json(self, container: str, name: str, obj, **kwargs) -> str:
        data = json.dumps(obj, indent=1, default=str, ensure_ascii=False).encode()
        return self.put_bytes(container, name, data, "application/json", **kwargs)

    def get_json(self, container: str, name: str):
        return json.loads(self.get_bytes(container, name))

    def get_json_with_etag(self, container: str, name: str):
        data, etag = self.get_with_etag(container, name)
        return json.loads(data), etag

    def get_json_or_none(self, container: str, name: str):
        try:
            return self.get_json(container, name)
        except FileNotFoundError:
            return None


# --------------------------------------------------------------------------------------------- local folder

_LOCK = threading.Lock()


class LocalBlobStore(BlobStore):
    """Containers are folders under ``root``. Metadata and ETags live in ``<container>/.meta/<name>.json``.

    Conditional writes take a thread lock and an ``fcntl`` file lock, so they are safe across threads and across
    processes on the same machine (for example a CLI run next to the web server).
    """

    META = ".meta"

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, container: str, name: str) -> Path:
        base = (self.root / container).resolve()
        path = (base / name).resolve()
        if base not in path.parents or name.startswith(self.META) or "/." in f"/{name}":
            raise ValueError(f"Invalid blob name: {name}")
        return path

    def _meta_path(self, container: str, name: str) -> Path:
        return self.root / container / self.META / f"{name}.json"

    @contextlib.contextmanager
    def _locked(self):
        with _LOCK:
            with (self.root / ".lock").open("a") as fh:
                fcntl.flock(fh, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(fh, fcntl.LOCK_UN)

    def _read_meta(self, container: str, name: str) -> dict:
        try:
            return json.loads(self._meta_path(container, name).read_text())
        except (FileNotFoundError, ValueError):
            return {}

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    def put_bytes(self, container, name, data, content_type=None, metadata=None, if_match=None, if_none_match=False):
        path = self._path(container, name)
        with self._locked():
            meta = self._read_meta(container, name) if path.is_file() else {}
            if if_none_match and path.is_file():
                raise PreconditionFailed(f"{container}/{name} already exists")
            if if_match is not None and (not path.is_file() or meta.get("etag") != if_match):
                raise PreconditionFailed(f"{container}/{name} was changed by someone else")
            now = datetime.now(timezone.utc).isoformat()
            etag = uuid.uuid4().hex
            new_meta = {"etag": etag, "content_type": content_type or "application/octet-stream",
                        "created": meta.get("created", now), "modified": now,
                        "metadata": dict(metadata if metadata is not None else meta.get("metadata", {}))}
            self._atomic_write(path, data)
            self._atomic_write(self._meta_path(container, name), json.dumps(new_meta).encode())
            return etag

    def set_metadata(self, container: str, name: str, metadata: dict) -> None:
        path = self._path(container, name)
        with self._locked():
            if not path.is_file():
                raise FileNotFoundError(f"{container}/{name}")
            meta = self._read_meta(container, name)
            meta["metadata"] = dict(metadata)
            self._atomic_write(self._meta_path(container, name), json.dumps(meta).encode())

    def get_with_etag(self, container, name):
        path = self._path(container, name)
        with self._locked():
            if not path.is_file():
                raise FileNotFoundError(f"{container}/{name}")
            return path.read_bytes(), self._read_meta(container, name).get("etag", "")

    def _info(self, container: str, name: str, path: Path) -> BlobInfo:
        meta = self._read_meta(container, name)
        stat = path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        created = datetime.fromisoformat(meta["created"]) if meta.get("created") else mtime
        return BlobInfo(name=name, size=stat.st_size, etag=meta.get("etag", ""), created=created,
                        last_modified=mtime, metadata=dict(meta.get("metadata", {})))

    def get_info(self, container, name):
        path = self._path(container, name)
        if not path.is_file():
            raise FileNotFoundError(f"{container}/{name}")
        return self._info(container, name, path)

    def exists(self, container, name):
        return self._path(container, name).is_file()

    def delete(self, container, name):
        path = self._path(container, name)
        with self._locked():
            existed = path.is_file()
            path.unlink(missing_ok=True)
            self._meta_path(container, name).unlink(missing_ok=True)
            return existed

    def list_info(self, container, prefix=""):
        base = self.root / container
        if not base.is_dir():
            return []
        out = []
        for p in base.rglob("*"):
            rel = p.relative_to(base).as_posix()
            if p.is_file() and not rel.startswith(self.META + "/") and not p.name.endswith(".tmp") \
                    and rel.startswith(prefix):
                with contextlib.suppress(FileNotFoundError):  # deleted while listing
                    out.append(self._info(container, rel, p))
        return sorted(out, key=lambda b: b.name)

    def iter_chunks(self, container, name, chunk_size=1 << 20):
        path = self._path(container, name)
        if not path.is_file():
            raise FileNotFoundError(f"{container}/{name}")
        with path.open("rb") as fh:
            while chunk := fh.read(chunk_size):
                yield chunk

    def clear(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------------------------- Azure Blob Storage

class AzureBlobStore(BlobStore):
    def __init__(self, settings: Settings):
        from azure.storage.blob import BlobServiceClient

        if settings.storage_connection_string:
            self.client = BlobServiceClient.from_connection_string(settings.storage_connection_string)
        elif settings.storage_account_url:
            from .azure_auth import get_credential

            self.client = BlobServiceClient(settings.storage_account_url, credential=get_credential())
        else:
            raise RuntimeError("Set AZURE_STORAGE_ACCOUNT_URL (or AZURE_STORAGE_CONNECTION_STRING for Azurite)")
        self._ensured: set[str] = set()

    def _container(self, container: str):
        client = self.client.get_container_client(container)
        if container not in self._ensured:
            from azure.core.exceptions import ResourceExistsError

            with contextlib.suppress(ResourceExistsError):
                client.create_container()
            self._ensured.add(container)
        return client

    def put_bytes(self, container, name, data, content_type=None, metadata=None, if_match=None, if_none_match=False):
        from azure.core import MatchConditions
        from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError
        from azure.storage.blob import ContentSettings

        blob = self._container(container).get_blob_client(name)
        kwargs = {"overwrite": not if_none_match}
        if content_type:
            kwargs["content_settings"] = ContentSettings(content_type=content_type)
        if metadata is not None:
            kwargs["metadata"] = metadata
        elif if_match is not None:
            # Keep existing metadata on a conditional rewrite (upload_blob replaces it otherwise).
            try:
                kwargs["metadata"] = blob.get_blob_properties().metadata
            except ResourceNotFoundError as exc:
                raise PreconditionFailed(f"{container}/{name} does not exist") from exc
        if if_match is not None:
            kwargs.update(etag=if_match, match_condition=MatchConditions.IfNotModified)
        try:
            result = blob.upload_blob(data, **kwargs)
        except (ResourceModifiedError, ResourceExistsError) as exc:
            raise PreconditionFailed(f"{container}/{name}: {exc.reason}") from exc
        except ResourceNotFoundError as exc:  # if_match on a blob that was deleted meanwhile
            raise PreconditionFailed(f"{container}/{name} does not exist") from exc
        return result["etag"]

    def set_metadata(self, container: str, name: str, metadata: dict) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            self._container(container).get_blob_client(name).set_blob_metadata(metadata)
        except ResourceNotFoundError as exc:
            raise FileNotFoundError(f"{container}/{name}") from exc

    def get_with_etag(self, container, name):
        from azure.core.exceptions import ResourceNotFoundError

        try:
            downloader = self._container(container).download_blob(name)
            return downloader.readall(), downloader.properties.etag
        except ResourceNotFoundError as exc:
            raise FileNotFoundError(f"{container}/{name}") from exc

    @staticmethod
    def _to_info(props) -> BlobInfo:
        return BlobInfo(name=props.name, size=props.size, etag=props.etag,
                        created=props.creation_time or props.last_modified, last_modified=props.last_modified,
                        metadata=dict(props.metadata or {}))

    def get_info(self, container, name):
        from azure.core.exceptions import ResourceNotFoundError

        try:
            return self._to_info(self._container(container).get_blob_client(name).get_blob_properties())
        except ResourceNotFoundError as exc:
            raise FileNotFoundError(f"{container}/{name}") from exc

    def exists(self, container, name):
        return self._container(container).get_blob_client(name).exists()

    def delete(self, container, name):
        from azure.core.exceptions import ResourceNotFoundError

        try:
            self._container(container).delete_blob(name, delete_snapshots="include")
            return True
        except ResourceNotFoundError:
            return False

    def list_info(self, container, prefix=""):
        blobs = self._container(container).list_blobs(name_starts_with=prefix or None, include=["metadata"])
        return sorted((self._to_info(b) for b in blobs), key=lambda b: b.name)

    def iter_chunks(self, container, name, chunk_size=1 << 20):
        from azure.core.exceptions import ResourceNotFoundError

        try:
            downloader = self._container(container).download_blob(name, max_concurrency=1)
        except ResourceNotFoundError as exc:
            raise FileNotFoundError(f"{container}/{name}") from exc
        yield from downloader.chunks()
