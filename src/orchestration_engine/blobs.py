"""Compressed Content-Addressed Blob Storage for Large Task Payloads.

Prevents SQLite database and WAL bloat by offloading large task inputs and outputs
(> threshold_bytes) to a content-addressed, zlib-compressed local directory.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import zlib
from typing import Any

BLOB_MARKER_KEY = "__oe_blob__"


@dataclasses.dataclass(frozen=True)
class BlobReference:
    """Content-addressed pointer to an offloaded compressed blob."""

    blob_hash: str
    uncompressed_bytes: int
    compressed_bytes: int
    path: str


class BlobStore:
    """Zero-dependency content-addressed blob store with zlib compression."""

    def __init__(
        self, storage_dir: str = ".orchestration_blobs", compression_level: int = 6
    ) -> None:
        self.storage_dir = os.path.abspath(storage_dir)
        self.compression_level = compression_level
        os.makedirs(self.storage_dir, exist_ok=True)

    def _blob_path(self, blob_hash: str) -> str:
        prefix = blob_hash[:2]
        suffix = blob_hash[2:]
        parent = os.path.join(self.storage_dir, prefix)
        return os.path.join(parent, f"{suffix}.blob")

    def put(self, data: bytes | str | Any) -> BlobReference:
        """Compress and persist data into content-addressed blob storage."""
        if isinstance(data, bytes):
            raw_bytes = data
            is_json = False
        elif isinstance(data, str):
            raw_bytes = data.encode("utf-8")
            is_json = False
        else:
            raw_bytes = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
            is_json = True

        blob_hash = hashlib.sha256(raw_bytes).hexdigest()
        dest_path = self._blob_path(blob_hash)

        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        compressed = zlib.compress(raw_bytes, level=self.compression_level)

        # Prepend a 1-byte header flag: 1 if JSON, 0 if raw bytes/str
        header = b"\x01" if is_json else b"\x00"
        with open(dest_path, "wb") as f:
            f.write(header + compressed)

        return BlobReference(
            blob_hash=blob_hash,
            uncompressed_bytes=len(raw_bytes),
            compressed_bytes=len(compressed),
            path=dest_path,
        )

    def get(self, ref_or_hash: BlobReference | str) -> Any:
        """Decompress and return stored data by reference or hash."""
        blob_hash = ref_or_hash.blob_hash if isinstance(ref_or_hash, BlobReference) else ref_or_hash
        path = self._blob_path(blob_hash)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Blob with hash '{blob_hash}' does not exist at {path}")

        with open(path, "rb") as f:
            header = f.read(1)
            compressed = f.read()

        raw_bytes = zlib.decompress(compressed)
        if header == b"\x01":
            return json.loads(raw_bytes.decode("utf-8"))
        try:
            return raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return raw_bytes

    def has(self, blob_hash: str) -> bool:
        """Check if a blob exists."""
        return os.path.exists(self._blob_path(blob_hash))

    def delete(self, blob_hash: str) -> bool:
        """Delete a blob file."""
        path = self._blob_path(blob_hash)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    def offload_if_large(self, payload: Any, threshold_bytes: int = 65536) -> Any:
        """If serialized payload exceeds threshold_bytes, offload to blob storage.

        Returns a lightweight pointer dict. Otherwise returns payload unchanged.
        """
        try:
            raw = json.dumps(payload, default=str).encode("utf-8")
        except Exception:
            raw = str(payload).encode("utf-8")

        if len(raw) >= threshold_bytes:
            ref = self.put(payload)
            return {
                BLOB_MARKER_KEY: True,
                "blob_hash": ref.blob_hash,
                "uncompressed_bytes": ref.uncompressed_bytes,
                "compressed_bytes": ref.compressed_bytes,
                "path": ref.path,
            }
        return payload

    def resolve_if_blob(self, payload: Any) -> Any:
        """If payload is an offloaded blob pointer dict, decompress and return original."""
        if isinstance(payload, dict) and payload.get(BLOB_MARKER_KEY) is True:
            blob_hash = payload.get("blob_hash")
            if isinstance(blob_hash, str):
                return self.get(blob_hash)
        return payload
