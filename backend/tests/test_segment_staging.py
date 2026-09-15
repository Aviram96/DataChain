"""Tests for ingest staging and delete-after-success policy (CP-C.P6–P7)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from app.services.camera_ingest import camera_chunk_dir
from app.services.chunk_processing_worker import (
    ChunkProcessingWorker,
    ChunkProcessingWorkerConfig,
)
from app.services.segment_identity import camera_segment_pattern
from app.services.segment_integrity import SegmentIntegrityResult
from app.services.segment_staging import (
    is_under_staging_dir,
    staging_dir_for_camera,
    staging_worker_config,
)

CAMERA_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def _box(box_type: bytes, payload: bytes) -> bytes:
    size = 8 + len(payload)
    return size.to_bytes(4, "big") + box_type + payload


def _minimal_mp4() -> bytes:
    ftyp = _box(b"ftyp", b"isom" + (0).to_bytes(4, "big") + b"isom")
    moov = _box(b"moov", b"")
    return ftyp + moov


def test_staging_dir_for_camera_is_under_temp(tmp_path: Path) -> None:
    staged = staging_dir_for_camera(CAMERA_ID, tmp_path)
    assert staged == (tmp_path / str(CAMERA_ID)).resolve()
    assert staged == camera_chunk_dir(CAMERA_ID, tmp_path)
    assert staged.parent == tmp_path.resolve()


def test_is_under_staging_dir_rejects_outside(tmp_path: Path) -> None:
    staging = staging_dir_for_camera(CAMERA_ID, tmp_path)
    staging.mkdir()
    inside = staging / f"{CAMERA_ID}_20260824T120000Z.mp4"
    inside.write_bytes(_minimal_mp4())
    outside = tmp_path / "other.mp4"
    outside.write_bytes(_minimal_mp4())
    assert is_under_staging_dir(inside, staging) is True
    assert is_under_staging_dir(outside, staging) is False


def test_staging_worker_keeps_file_after_processor_success(tmp_path: Path) -> None:
    staging = staging_dir_for_camera(CAMERA_ID, tmp_path)
    staging.mkdir()
    segment = staging / f"{CAMERA_ID}_20260824T120000Z.mp4"
    segment.write_bytes(_minimal_mp4())

    def pass_check(path: Path) -> SegmentIntegrityResult:
        return SegmentIntegrityResult(ok=True, path=path, sha256="abc", size_bytes=1)

    worker = ChunkProcessingWorker(
        staging_worker_config(
            temp_dir=staging,
            segment_pattern=camera_segment_pattern(CAMERA_ID),
            integrity_check=pass_check,
            stable_delay_seconds=0,
        )
    )
    deleted = worker.process_all_blocking()
    assert deleted == 0
    assert segment.exists()
    assert is_under_staging_dir(segment, staging)


def test_ingest_named_segment_deletes_only_after_processing_success(
    tmp_path: Path,
) -> None:
    staging = staging_dir_for_camera(CAMERA_ID, tmp_path)
    staging.mkdir()
    segment = staging / f"{CAMERA_ID}_20260824T120000Z.mp4"
    segment.write_bytes(_minimal_mp4())
    attempts = {"count": 0}

    def fail_then_succeed(_path: Path) -> bool:
        attempts["count"] += 1
        return attempts["count"] >= 2

    worker = ChunkProcessingWorker(
        ChunkProcessingWorkerConfig(
            temp_dir=staging,
            stable_delay_seconds=0,
            segment_pattern=camera_segment_pattern(CAMERA_ID),
            processor=fail_then_succeed,
            delete_on_success=True,
        )
    )
    assert worker.process_all_blocking() == 0
    assert segment.exists()
    assert worker.process_all_blocking() == 1
    assert not segment.exists()

