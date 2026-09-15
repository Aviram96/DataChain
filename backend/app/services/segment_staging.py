"""Stage camera ingest segments under temp/ until processing succeeds (CP-C.P6).

FFmpeg writes each closed ``{camera_id}_{start}Z.mp4`` into
``temp/<camera-id>/``. Files stay there through integrity (CP-C.P5).
Camera ingest uses ``ingest_segment_processor`` (Pinata + chain + DB) with
``delete_on_success=True``. ``keep_staged_until_processing_succeeds`` remains
for tests and any path that must not delete on staging-only success.
"""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

from app.services.chunk_processing_worker import (
    ChunkProcessingWorkerConfig,
    IntegrityCheck,
)
from app.services.video_chunker import resolve_temp_dir

logger = logging.getLogger(__name__)


def staging_dir_for_camera(camera_id: UUID, base: Path | None = None) -> Path:
    """Per-camera staging folder under temp/ (default ``backend/temp/<id>/``)."""
    root = base.resolve() if base is not None else resolve_temp_dir()
    return (root / str(camera_id)).resolve()


def is_under_staging_dir(path: Path, staging_dir: Path) -> bool:
    """True when ``path`` resolves to a file inside the camera staging folder."""
    try:
        resolved = path.resolve()
        root = staging_dir.resolve()
    except OSError:
        return False
    try:
        resolved.relative_to(root)
    except ValueError:
        return False
    return resolved.is_file()


def keep_staged_until_processing_succeeds(path: Path) -> bool:
    """Processor: staging succeeded; later pipeline steps have not run yet.

    Returns True so the worker records the file as handled without treating
    IPFS / chain / DB as done. Ingest sets ``delete_on_success=False`` so the
    file is not deleted until processing actually succeeds (CP-C.P7).
    """
    logger.info("Staged under temp/ until processing succeeds: %s", path.name)
    return True


def staging_worker_config(
    *,
    temp_dir: Path,
    segment_pattern: str,
    integrity_check: IntegrityCheck | None = None,
    poll_interval_seconds: float = 1.0,
    stable_delay_seconds: float = 0.5,
) -> ChunkProcessingWorkerConfig:
    """Worker that integrity-checks then leaves files until a later processor.

    Camera ingest does not use this stub; it uses ``ingest_segment_processor``
    with ``delete_on_success=True``.
    """
    return ChunkProcessingWorkerConfig(
        temp_dir=temp_dir,
        poll_interval_seconds=poll_interval_seconds,
        stable_delay_seconds=stable_delay_seconds,
        segment_pattern=segment_pattern,
        processor=keep_staged_until_processing_succeeds,
        delete_on_success=False,
        integrity_check=integrity_check,
    )
