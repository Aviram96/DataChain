"""Tests for basic segment integrity (Slice C / CP-C.P5)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID
from unittest.mock import patch, MagicMock

from app.services.camera_ingest import (
    CameraIngestConfig,
    integrity_worker_config_for_ingest,
)
from app.services.chunk_processing_worker import (
    ChunkProcessingWorker,
    ChunkProcessingWorkerConfig,
)
from app.services.segment_identity import camera_segment_pattern
from app.services.segment_integrity import (
    SegmentIntegrityResult,
    check_segment,
    ffprobe_executable_for,
    mp4_has_ftyp_and_moov,
    sha256_file,
    probe_video_duration_seconds,
)

CAMERA_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def _box(box_type: bytes, payload: bytes) -> bytes:
    size = 8 + len(payload)
    return size.to_bytes(4, "big") + box_type + payload


def _minimal_mp4() -> bytes:
    ftyp = _box(b"ftyp", b"isom" + (0).to_bytes(4, "big") + b"isom")
    moov = _box(b"moov", b"")
    return ftyp + moov


def _camera_segment_path(tmp_path: Path, payload: bytes) -> Path:
    path = tmp_path / f"{CAMERA_ID}_20260824T120000Z.mp4"
    path.write_bytes(payload)
    return path


def test_ffprobe_executable_for_bare_name() -> None:
    assert ffprobe_executable_for("ffmpeg") == "ffprobe"


def test_ffprobe_executable_for_sibling_path(tmp_path: Path) -> None:
    ffmpeg = tmp_path / "ffmpeg.exe"
    assert ffprobe_executable_for(str(ffmpeg)) == str(tmp_path / "ffprobe.exe")


def test_mp4_has_ftyp_and_moov_accepts_minimal(tmp_path: Path) -> None:
    path = tmp_path / "ok.mp4"
    path.write_bytes(_minimal_mp4())
    assert mp4_has_ftyp_and_moov(path) is True


def test_mp4_has_ftyp_and_moov_rejects_truncated(tmp_path: Path) -> None:
    path = tmp_path / "bad.mp4"
    path.write_bytes(_box(b"ftyp", b"isom" + (0).to_bytes(4, "big")))
    assert mp4_has_ftyp_and_moov(path) is False


def test_check_segment_passes_complete_camera_file(tmp_path: Path) -> None:
    payload = _minimal_mp4()
    path = _camera_segment_path(tmp_path, payload)
    result = check_segment(
        path,
        duration_seconds=60,
        probe_video=lambda _p: True,
    )
    assert result.ok is True
    assert result.sha256 == hashlib.sha256(payload).hexdigest()
    assert result.identity is not None
    assert result.identity.camera_id == CAMERA_ID
    assert sha256_file(path) == result.sha256


def test_check_segment_rejects_empty(tmp_path: Path) -> None:
    path = _camera_segment_path(tmp_path, b"")
    result = check_segment(path, duration_seconds=60, probe_video=lambda _p: True)
    assert result.ok is False
    assert "empty" in (result.error or "").lower()


def test_check_segment_rejects_generic_chunk_name(tmp_path: Path) -> None:
    path = tmp_path / "chunk_000.mp4"
    path.write_bytes(_minimal_mp4())
    result = check_segment(path, duration_seconds=60, probe_video=lambda _p: True)
    assert result.ok is False
    assert result.error is not None


def test_check_segment_rejects_missing_video_stream(tmp_path: Path) -> None:
    path = _camera_segment_path(tmp_path, _minimal_mp4())
    result = check_segment(path, duration_seconds=60, probe_video=lambda _p: False)
    assert result.ok is False
    assert "video" in (result.error or "").lower()


def test_worker_skips_processor_when_integrity_fails(tmp_path: Path) -> None:
    chunk = tmp_path / "chunk_000.mp4"
    chunk.write_bytes(b"data")
    called: list[Path] = []

    def processor(path: Path) -> bool:
        called.append(path)
        return True

    def fail_check(path: Path) -> SegmentIntegrityResult:
        return SegmentIntegrityResult(ok=False, path=path, error="corrupt")

    worker = ChunkProcessingWorker(
        ChunkProcessingWorkerConfig(
            temp_dir=tmp_path,
            stable_delay_seconds=0,
            processor=processor,
            integrity_check=fail_check,
        ),
    )
    deleted = worker.process_all_blocking()
    assert deleted == 0
    assert chunk.exists()
    assert called == []


def test_worker_holds_file_when_delete_on_success_false(tmp_path: Path) -> None:
    chunk = tmp_path / "chunk_000.mp4"
    chunk.write_bytes(_minimal_mp4())

    def pass_check(path: Path) -> SegmentIntegrityResult:
        return SegmentIntegrityResult(ok=True, path=path, sha256="abc", size_bytes=1)

    worker = ChunkProcessingWorker(
        ChunkProcessingWorkerConfig(
            temp_dir=tmp_path,
            stable_delay_seconds=0,
            delete_on_success=False,
            integrity_check=pass_check,
        ),
    )
    deleted = worker.process_all_blocking()
    assert deleted == 0
    assert chunk.exists()


def test_integrity_worker_config_for_ingest_gates_then_stages(tmp_path: Path) -> None:
    config = CameraIngestConfig(
        camera_id=CAMERA_ID,
        stream_url="rtsp://192.0.2.50/live",
        temp_dir=tmp_path,
    )
    worker_config = integrity_worker_config_for_ingest(config)
    assert worker_config.integrity_check is not None
    assert worker_config.segment_pattern == camera_segment_pattern(CAMERA_ID)
    assert callable(worker_config.processor)
    assert worker_config.delete_on_success is True


def test_probe_video_duration_seconds(tmp_path: Path) -> None:
    path = tmp_path / "video.mp4"
    path.write_bytes(b"test")

    with patch("app.services.segment_integrity.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="17.280000\n",
        )

        duration = probe_video_duration_seconds(path)

    assert duration == 17.28


def test_probe_video_timing_reads_start_and_duration(tmp_path: Path) -> None:
    from app.services.segment_integrity import probe_video_timing

    path = tmp_path / "video.mp4"
    path.write_bytes(b"test")
    with patch("app.services.segment_integrity.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="start_time=3.080000\nduration=5.000000\n",
        )
        start_time, duration = probe_video_timing(path)
    assert start_time == 3.08
    assert duration == 5.0
