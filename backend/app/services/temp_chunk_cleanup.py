"""Safely delete processed chunk files from the managed temp directory."""

from __future__ import annotations

import logging
from pathlib import Path

from app.services.video_chunker import DEFAULT_SEGMENT_PATTERN

logger = logging.getLogger(__name__)


class TempChunkCleanupError(Exception):
    """Refused or failed temp chunk deletion."""


def is_managed_chunk_path(
    path: Path,
    temp_dir: Path,
    pattern: str = DEFAULT_SEGMENT_PATTERN,
) -> bool:
    """True when path is a chunk file inside the resolved temp directory."""
    try:
        resolved = path.resolve()
        temp_resolved = temp_dir.resolve()
    except OSError:
        return False
    try:
        resolved.relative_to(temp_resolved)
    except ValueError:
        return False
    prefix = pattern.split("%")[0]
    return (
        resolved.is_file()
        and resolved.name.startswith(prefix)
        and resolved.suffix == ".mp4"
    )


def delete_chunk(
    path: Path,
    temp_dir: Path,
    pattern: str = DEFAULT_SEGMENT_PATTERN,
) -> None:
    """Delete one chunk file after validating it belongs to temp/."""
    if not is_managed_chunk_path(path, temp_dir, pattern):
        raise TempChunkCleanupError(
            f"Refusing to delete path outside managed temp chunks: {path}"
        )
    path.unlink(missing_ok=True)
    logger.info("Deleted processed chunk %s", path.name)


def delete_after_successful_processing(
    path: Path,
    temp_dir: Path,
    pattern: str = DEFAULT_SEGMENT_PATTERN,
) -> None:
    """Remove a temp segment only after processing succeeded (CP-C.P7)."""
    delete_chunk(path, temp_dir, pattern)


def delete_chunks(
    paths: list[Path],
    temp_dir: Path,
    pattern: str = DEFAULT_SEGMENT_PATTERN,
) -> int:
    """Delete many chunk files; return count removed."""
    deleted = 0
    for path in paths:
        delete_chunk(path, temp_dir, pattern)
        deleted += 1
    return deleted
