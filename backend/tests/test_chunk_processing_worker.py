"""Tests for chunk processing worker."""

from __future__ import annotations

from pathlib import Path

from app.services.chunk_processing_worker import (
    ChunkProcessingWorker,
    ChunkProcessingWorkerConfig,
)
from app.services.segment_integrity import INCOMPLETE_MP4_ERROR, SegmentIntegrityResult
from app.services.segment_timeline import (
    SegmentTimelineNotReady,
    SegmentTimelinePermanentError,
)


def test_worker_deletes_on_success(tmp_path: Path) -> None:
    chunk = tmp_path / "chunk_000.mp4"
    chunk.write_bytes(b"data")

    worker = ChunkProcessingWorker(
        ChunkProcessingWorkerConfig(
            temp_dir=tmp_path,
            stable_delay_seconds=0,
        ),
    )
    deleted = worker.process_all_blocking()
    assert deleted == 1
    assert not chunk.exists()


def test_worker_keeps_file_on_processor_failure(tmp_path: Path) -> None:
    chunk = tmp_path / "chunk_000.mp4"
    chunk.write_bytes(b"data")

    def fail_processor(_path: Path) -> bool:
        return False

    worker = ChunkProcessingWorker(
        ChunkProcessingWorkerConfig(
            temp_dir=tmp_path,
            stable_delay_seconds=0,
            processor=fail_processor,
        ),
    )
    deleted = worker.process_all_blocking()
    assert deleted == 0
    assert chunk.exists()


def test_worker_retries_after_processor_failure_then_deletes(tmp_path: Path) -> None:
    chunk = tmp_path / "chunk_000.mp4"
    chunk.write_bytes(b"data")
    attempts = {"count": 0}

    def fail_once(path: Path) -> bool:
        attempts["count"] += 1
        return attempts["count"] >= 2

    worker = ChunkProcessingWorker(
        ChunkProcessingWorkerConfig(
            temp_dir=tmp_path,
            stable_delay_seconds=0,
            processor=fail_once,
        ),
    )
    assert worker.process_all_blocking() == 0
    assert chunk.exists()
    assert worker.process_all_blocking() == 1
    assert not chunk.exists()
    assert attempts["count"] == 2


def test_worker_keeps_integrity_failure_without_deleting(tmp_path: Path) -> None:
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
    assert worker.process_all_blocking() == 0
    assert chunk.exists()
    assert called == []
    assert not (tmp_path / "chunk_000.mp4.invalid").exists()


def test_worker_retries_after_temporary_integrity_failure(tmp_path: Path) -> None:
    chunk = tmp_path / "chunk_000.mp4"
    chunk.write_bytes(b"data")

    attempts = {"count": 0}
    processed: list[Path] = []

    def integrity_check(path: Path) -> SegmentIntegrityResult:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return SegmentIntegrityResult(
                ok=False,
                path=path,
                error="ffprobe timed out",
            )
        return SegmentIntegrityResult(ok=True, path=path)

    def processor(path: Path) -> bool:
        processed.append(path)
        return True

    worker = ChunkProcessingWorker(
        ChunkProcessingWorkerConfig(
            temp_dir=tmp_path,
            stable_delay_seconds=0,
            processor=processor,
            integrity_check=integrity_check,
        ),
    )

    assert worker.process_all_blocking() == 0
    assert chunk.exists()
    assert processed == []

    assert worker.process_all_blocking() == 1
    assert not chunk.exists()
    assert processed == [chunk]
    assert attempts["count"] == 2


def test_worker_waits_for_open_mp4_then_processes_when_complete(tmp_path: Path) -> None:
    chunk = tmp_path / "chunk_000.mp4"
    chunk.write_bytes(b"partial")
    calls = {"n": 0}
    processed: list[Path] = []

    def check(path: Path) -> SegmentIntegrityResult:
        calls["n"] += 1
        if calls["n"] == 1:
            return SegmentIntegrityResult(
                ok=False,
                path=path,
                error=INCOMPLETE_MP4_ERROR,
            )
        return SegmentIntegrityResult(ok=True, path=path, sha256="abc", size_bytes=8)

    def processor(path: Path) -> bool:
        processed.append(path)
        return True

    worker = ChunkProcessingWorker(
        ChunkProcessingWorkerConfig(
            temp_dir=tmp_path,
            stable_delay_seconds=0,
            processor=processor,
            integrity_check=check,
        ),
    )
    assert worker._scan_once(final_pass=False) == 0
    assert processed == []
    assert chunk.exists()
    assert not (tmp_path / "chunk_000.mp4.invalid").exists()
    assert worker._scan_once(final_pass=False) == 1
    assert processed == [chunk]
    assert not chunk.exists()
    assert calls["n"] == 2


def test_worker_rejects_incomplete_mp4_when_ingest_stops(tmp_path: Path) -> None:
    chunk = tmp_path / "chunk_000.mp4"
    chunk.write_bytes(b"partial")
    calls = {"n": 0}

    def check(path: Path) -> SegmentIntegrityResult:
        calls["n"] += 1
        return SegmentIntegrityResult(
            ok=False,
            path=path,
            error=INCOMPLETE_MP4_ERROR,
        )

    def processor(path: Path) -> bool:
        raise AssertionError("open segment must not be processed")

    worker = ChunkProcessingWorker(
        ChunkProcessingWorkerConfig(
            temp_dir=tmp_path,
            stable_delay_seconds=0,
            processor=processor,
            integrity_check=check,
        ),
    )
    assert worker.process_all_blocking() == 0
    assert chunk.exists()
    assert not (tmp_path / "chunk_000.mp4.invalid").exists()
    assert worker.process_all_blocking() == 0
    assert calls["n"] == 1


def test_worker_skips_newest_segment_during_recording(tmp_path: Path) -> None:
    older = tmp_path / "chunk_001.mp4"
    newest = tmp_path / "chunk_002.mp4"
    older.write_bytes(b"complete")
    newest.write_bytes(b"still recording")

    processed: list[Path] = []

    def processor(path: Path) -> bool:
        processed.append(path)
        return True

    worker = ChunkProcessingWorker(
        ChunkProcessingWorkerConfig(
            temp_dir=tmp_path,
            stable_delay_seconds=0,
            processor=processor,
            skip_newest_segment=True,
        ),
    )

    worker._scan_once(final_pass=False)

    assert processed == [older]
    assert not older.exists()
    assert newest.exists()


def test_worker_retries_until_timeline_is_ready(tmp_path: Path) -> None:
    chunk = tmp_path / "chunk_000.mp4"
    chunk.write_bytes(b"data")
    calls = {"n": 0}

    def processor(_path: Path) -> bool:
        calls["n"] += 1
        if calls["n"] == 1:
            raise SegmentTimelineNotReady("waiting for the second segment")
        return True

    worker = ChunkProcessingWorker(
        ChunkProcessingWorkerConfig(
            temp_dir=tmp_path,
            stable_delay_seconds=0,
            processor=processor,
        ),
    )
    assert worker.process_all_blocking() == 0
    assert chunk.exists()
    assert worker.process_all_blocking() == 1
    assert not chunk.exists()
    assert calls["n"] == 2


def test_worker_does_not_retry_a_permanent_timeline_failure(tmp_path: Path) -> None:
    chunk = tmp_path / "chunk_000.mp4"
    chunk.write_bytes(b"data")
    calls = {"n": 0}

    def processor(_path: Path) -> bool:
        calls["n"] += 1
        raise SegmentTimelinePermanentError("incomplete row")

    worker = ChunkProcessingWorker(
        ChunkProcessingWorkerConfig(
            temp_dir=tmp_path,
            stable_delay_seconds=0,
            processor=processor,
        ),
    )
    assert worker.process_all_blocking() == 0
    assert chunk.exists()
    assert (tmp_path / "chunk_000.mp4.invalid").is_file()
    assert worker.process_all_blocking() == 0
    assert chunk.exists()
    assert calls["n"] == 1

    restarted = ChunkProcessingWorker(
        ChunkProcessingWorkerConfig(
            temp_dir=tmp_path,
            stable_delay_seconds=0,
            processor=processor,
        ),
    )
    assert restarted.process_all_blocking() == 0
    assert calls["n"] == 1
