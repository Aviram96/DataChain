"""Tests for camera+time segment filenames (Slice C / CP-C.P4)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from app.services.segment_identity import (
    SegmentIdentityError,
    camera_segment_pattern,
    parse_segment_path,
)
from app.services.video_chunker import list_chunk_files


def test_camera_segment_pattern_includes_id_and_strftime() -> None:
    camera_id = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    assert camera_segment_pattern(camera_id) == (
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee_%Y%m%dT%H%M%SZ.mp4"
    )


def test_parse_segment_path_returns_camera_and_time_window(tmp_path: Path) -> None:
    camera_id = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    path = tmp_path / f"{camera_id}_20260824T120000Z.mp4"
    path.write_bytes(b"\x00")
    identity = parse_segment_path(path, duration_seconds=60)
    assert identity.camera_id == camera_id
    assert identity.started_at == datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)
    assert identity.ended_at == datetime(2026, 8, 24, 12, 1, 0, tzinfo=timezone.utc)
    assert identity.path == path


def test_parse_segment_path_rejects_generic_chunk_name(tmp_path: Path) -> None:
    path = tmp_path / "chunk_000.mp4"
    path.write_bytes(b"\x00")
    with pytest.raises(SegmentIdentityError, match="Not a camera\\+time"):
        parse_segment_path(path, duration_seconds=60)


def test_list_chunk_files_matches_camera_time_pattern(tmp_path: Path) -> None:
    camera_id = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    pattern = camera_segment_pattern(camera_id)
    kept = tmp_path / f"{camera_id}_20260824T120000Z.mp4"
    other = tmp_path / "bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee_20260824T120000Z.mp4"
    kept.write_bytes(b"\x00")
    other.write_bytes(b"\x00")
    names = [path.name for path in list_chunk_files(tmp_path, pattern)]
    assert names == [kept.name]
