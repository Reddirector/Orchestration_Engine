"""Tests for Compressed Content-Addressed Blob Storage."""

from __future__ import annotations

from typing import Any

import pytest

from orchestration_engine.blobs import (
    BLOB_MARKER_KEY,
    BlobReference,
    BlobStore,
)


def test_blob_store_put_get_json(tmp_path: Any) -> None:
    store = BlobStore(storage_dir=str(tmp_path / "blobs"))

    data = {"matrix": [[i * j for j in range(50)] for i in range(50)], "name": "weights"}
    ref = store.put(data)

    assert isinstance(ref, BlobReference)
    assert len(ref.blob_hash) == 64
    assert ref.compressed_bytes < ref.uncompressed_bytes
    assert store.has(ref.blob_hash) is True

    recovered = store.get(ref)
    assert recovered == data


def test_blob_store_string_and_bytes(tmp_path: Any) -> None:
    store = BlobStore(storage_dir=str(tmp_path / "blobs"))

    # String test
    text = "A" * 10000
    ref_txt = store.put(text)
    assert store.get(ref_txt.blob_hash) == text

    # Raw bytes test
    raw = b"\x00\x01\x02\x03\xff" * 2000
    ref_bin = store.put(raw)
    assert store.get(ref_bin.blob_hash) == raw


def test_blob_store_offload_and_resolve(tmp_path: Any) -> None:
    store = BlobStore(storage_dir=str(tmp_path / "blobs"))

    # Small payload -> not offloaded
    small = {"small": "data"}
    res_small = store.offload_if_large(small, threshold_bytes=1000)
    assert res_small == small
    assert store.resolve_if_blob(res_small) == small

    # Large payload -> offloaded
    large = {"huge_array": [i for i in range(5000)]}
    res_large = store.offload_if_large(large, threshold_bytes=500)
    assert isinstance(res_large, dict)
    assert res_large[BLOB_MARKER_KEY] is True
    assert "blob_hash" in res_large

    # Resolves back to identical data
    resolved = store.resolve_if_blob(res_large)
    assert resolved == large


def test_blob_store_missing_and_delete(tmp_path: Any) -> None:
    store = BlobStore(storage_dir=str(tmp_path / "blobs"))

    with pytest.raises(FileNotFoundError):
        store.get("nonexistent_hash_12345")

    ref = store.put("temporary data")
    assert store.has(ref.blob_hash) is True
    assert store.delete(ref.blob_hash) is True
    assert store.has(ref.blob_hash) is False
    assert store.delete(ref.blob_hash) is False
