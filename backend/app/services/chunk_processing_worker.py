"""Background worker: process chunk files and remove them from temp/ on success."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.services.ingest_segment_processor import IngestPermanentError
from app.services.segment_integrity import INCOMPLETE_MP4_ERROR, SegmentIntegrityResult
from app.services.segment_timeline import (
    SegmentTimelineNotReady,
    SegmentTimelinePermanentError,
)
from app.services.temp_chunk_cleanup import (
    TempChunkCleanupError,
    delete_after_successful_processing,
)
from app.services.video_chunker import DEFAULT_SEGMENT_PATTERN, list_chunk_files

logger = logging.getLogger(__name__)

ChunkProcessor = Callable[[Path], bool]
IntegrityCheck = Callable[[Path], SegmentIntegrityResult]


def stub_chunk_processor(path: Path) -> bool:
    """Placeholder until Epic 6 IPFS/chain/DB processing replaces it."""
    logger.info("Stub-processed chunk %s (Epic 6 will upload and anchor)", path.name)
    return True


@dataclass
class ChunkProcessingWorkerConfig:
    """Polling worker settings."""

    temp_dir: Path
    poll_interval_seconds: float = 1.0
    stable_delay_seconds: float = 0.5
    segment_pattern: str = DEFAULT_SEGMENT_PATTERN
    processor: ChunkProcessor = field(default=stub_chunk_processor)
    delete_on_success: bool = True
    integrity_check: IntegrityCheck | None = None
    skip_newest_segment: bool = False


class ChunkProcessingWorker:
    """Poll temp/ for new chunk files; optionally integrity-check, then process.

    CP-C.P7: delete a temp file only after the processor returns True and
    ``delete_on_success`` is set. Processor failures leave the file in place
    for retry. Integrity failures stay in temp/ and are not handed on (CP-C.P5).

    A normal MP4 gains its ``moov`` box only when FFmpeg closes the segment.
    While ingest is running, a missing ``moov`` means the minute is still open,
    so that file is checked again later. On shutdown, a file that is still
    incomplete is a real integrity failure.
    """

    def __init__(self, config: ChunkProcessingWorkerConfig) -> None:
        self._config = config
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._handled: set[Path] = set()
        self._awaiting_retry: set[Path] = set()
        self._permanent_failure: set[Path] = set()
        self._open_segment_notice: set[Path] = set()
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="chunk-processing-worker",
            daemon=True,
        )
        self._thread.start()
        role = "cleanup" if self._config.delete_on_success else "staging"
        logger.info(
            "Chunk %s worker watching %s (poll every %ss)",
            role,
            self._config.temp_dir,
            self._config.poll_interval_seconds,
        )

    def stop(self, *, flush: bool = True) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        if flush:
            self._scan_once(final_pass=True)

    def process_all_blocking(self) -> int:
        """Process every stable chunk currently in temp/; return deleted count."""
        return self._scan_once(final_pass=True)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self._scan_once(final_pass=False)
            self._stop_event.wait(self._config.poll_interval_seconds)

    def _scan_once(self, *, final_pass: bool) -> int:
        deleted = 0
        if not self._config.temp_dir.is_dir():
            return 0
        chunks = list_chunk_files(
            self._config.temp_dir,
            self._config.segment_pattern,
        )

        if self._config.skip_newest_segment and not final_pass and chunks:
            chunks = chunks[:-1]

        for path in chunks:
            with self._lock:
                if path in self._handled or path in self._permanent_failure:
                    continue
            if _timeline_invalid_marker(path).is_file():
                with self._lock:
                    self._permanent_failure.add(path)
                continue

            if not final_pass and not _is_file_stable(
                path,
                self._config.stable_delay_seconds,
            ):
                continue
            if self._config.integrity_check is not None:
                result = self._config.integrity_check(path)
                if not result.ok:
                    if not final_pass and result.error == INCOMPLETE_MP4_ERROR:
                        self._note_open_segment(path)
                        continue
                    logger.error(
                        "Segment integrity failed for %s: %s",
                        path.name,
                        result.error,
                    )
                    with self._lock:
                        self._open_segment_notice.discard(path)
                        if final_pass and result.error == INCOMPLETE_MP4_ERROR:
                            self._handled.add(path)
                    continue
                logger.info(
                    "Segment integrity ok %s sha256=%s bytes=%s",
                    path.name,
                    result.sha256,
                    result.size_bytes,
                )
            try:
                processed = self._config.processor(path)
            except SegmentTimelineNotReady:
                self._note_retry(path, timeline_not_ready=True)
                continue
            except (SegmentTimelinePermanentError, IngestPermanentError) as exc:
                self._keep_permanent_failure(path, exc)
                continue
            if not processed:
                self._note_retry(path, timeline_not_ready=False)
                continue
            if self._config.delete_on_success:
                try:
                    delete_after_successful_processing(
                        path,
                        self._config.temp_dir,
                        self._config.segment_pattern,
                    )
                    deleted += 1
                except TempChunkCleanupError as exc:
                    logger.error("%s", exc)
                    continue
            with self._lock:
                self._handled.add(path)
                self._awaiting_retry.discard(path)
                self._open_segment_notice.discard(path)
        return deleted

    def _note_retry(self, path: Path, *, timeline_not_ready: bool) -> None:
        with self._lock:
            first_retry = path not in self._awaiting_retry
            self._awaiting_retry.add(path)
        if not first_retry:
            logger.debug("Retrying staged segment %s", path.name)
            return
        if timeline_not_ready:
            logger.info(
                "Segment timeline is not ready; keeping %s for retry",
                path.name,
            )
            return
        logger.warning(
            "Processing did not succeed; keeping %s for retry",
            path.name,
        )

    def _keep_permanent_failure(self, path: Path, exc: Exception) -> None:
        """Keep the segment, log once, and do not process it again."""
        marker = _timeline_invalid_marker(path)
        if not marker.is_file():
            try:
                marker.write_text(f"{exc}\n", encoding="utf-8")
            except OSError:
                logger.error(
                    "Cannot record permanent timeline failure for %s",
                    path.name,
                )
            logger.error(
                "Permanent timeline failure for %s: %s",
                path.name,
                exc,
            )
        with self._lock:
            self._permanent_failure.add(path)
            self._awaiting_retry.discard(path)
            self._open_segment_notice.discard(path)

    def _note_open_segment(self, path: Path) -> None:
        """Remember a segment FFmpeg has not closed yet; log that once."""
        with self._lock:
            first_notice = path not in self._open_segment_notice
            self._open_segment_notice.add(path)
        if first_notice:
            logger.info(
                "Segment %s is still being written; waiting until it is complete",
                path.name,
            )


def _timeline_invalid_marker(path: Path) -> Path:
    return path.with_name(f"{path.name}.invalid")


def _is_file_stable(path: Path, delay_seconds: float) -> bool:
    """True when file size is unchanged after a short wait (write likely complete)."""
    try:
        first_size = path.stat().st_size
    except OSError:
        return False
    if first_size <= 0:
        return False
    time.sleep(delay_seconds)
    try:
        return path.stat().st_size == first_size
    except OSError:
        return False
