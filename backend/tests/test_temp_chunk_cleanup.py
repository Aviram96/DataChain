"""Tests for temp chunk cleanup."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.temp_chunk_cleanup import (
    TempChunkCleanupError,
    delete_after_successful_processing,
    delete_chunk,
    delete_chunks,
    is_managed_chunk_path,
)


def test_is_managed_chunk_path_accepts_chunk_in_temp(tmp_path: Path) -> None:
    chunk = tmp_path / "chunk_001.mp4"
    chunk.write_bytes(b"\x00")
    assert is_managed_chunk_path(chunk, tmp_path) is True


def test_is_managed_chunk_path_rejects_outside_temp(tmp_path: Path) -> None:
    outside = tmp_path.parent / "chunk_001.mp4"
    outside.write_bytes(b"\x00")
    assert is_managed_chunk_path(outside, tmp_path) is False


def test_delete_chunk_removes_file(tmp_path: Path) -> None:
    chunk = tmp_path / "chunk_000.mp4"
    chunk.write_bytes(b"\x00")
    delete_chunk(chunk, tmp_path)
    assert not chunk.exists()


def test_delete_chunk_rejects_outside_temp(tmp_path: Path) -> None:
    outside = tmp_path.parent / "chunk_000.mp4"
    outside.write_bytes(b"\x00")
    with pytest.raises(TempChunkCleanupError, match="Refusing to delete"):
        delete_chunk(outside, tmp_path)


def test_delete_chunks_count(tmp_path: Path) -> None:
    a = tmp_path / "chunk_000.mp4"
    b = tmp_path / "chunk_001.mp4"
    a.write_bytes(b"\x00")
    b.write_bytes(b"\x00")
    assert delete_chunks([a, b], tmp_path) == 2
    assert not a.exists()
    assert not b.exists()


def test_delete_after_successful_processing_removes_file(tmp_path: Path) -> None:
    chunk = tmp_path / "chunk_000.mp4"
    chunk.write_bytes(b"\x00")
    delete_after_successful_processing(chunk, tmp_path)
    assert not chunk.exists()
