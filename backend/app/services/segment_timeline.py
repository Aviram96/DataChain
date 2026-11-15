
"""Read FFmpeg segment timeline data from CSV files."""

from __future__ import annotations

import csv
import math

from dataclasses import dataclass
from pathlib import Path

from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class SegmentTimelineEntry:
    filename: str
    media_start: float
    media_end: float


def read_segment_timeline(csv_path: Path) -> list[SegmentTimelineEntry]:
    """Read and validate segment entries from an FFmpeg CSV file."""

    entries = []
    content = csv_path.read_bytes()

    if content and not content.endswith(b"\n"):
        raise ValueError(
            f"Segment CSV may contain an incomplete row: {csv_path.name}"
        )

    with csv_path.open(newline="", encoding="utf-8") as file:
        for row in csv.reader(file):
            if len(row) != 3:
                raise ValueError("Invalid segment CSV row")

            filename, start, end = row

            if not filename.endswith(".mp4") or Path(filename).name != filename:
                raise ValueError("Invalid segment filename")

            media_start = float(start)
            media_end = float(end)

            if (
                not math.isfinite(media_start)
                or not math.isfinite(media_end)
                or media_start < 0
                or media_end <= media_start
            ):
                raise ValueError("Invalid segment timeline values")

            entries.append(
                SegmentTimelineEntry(
                    filename=filename,
                    media_start=media_start,
                    media_end=media_end,
                )
            )

    return entries


def find_segment_timeline(
    temp_dir: Path,
    segment_filename: str,
) -> SegmentTimelineEntry | None:
    """Find a segment in CSV files from different FFmpeg runs."""

    if (
        not segment_filename.endswith(".mp4")
        or Path(segment_filename).name != segment_filename
    ):
        raise ValueError("Invalid segment filename")

    matches: list[SegmentTimelineEntry] = []

    for csv_path in sorted(temp_dir.glob("segments_*.csv")):
        entries = read_segment_timeline(csv_path)

        for entry in entries:
            if entry.filename == segment_filename:
                matches.append(entry)

    if len(matches) > 1:
        raise ValueError(
            f"Duplicate timeline entries for segment: {segment_filename}"
        )

    return matches[0] if matches else None


def calculate_segment_media_range(
    entry: SegmentTimelineEntry,
    *,
    file_start_time: float,
    file_duration: float,
    first_segment: bool,
) -> tuple[float, float]:
    """Calculate and validate the media range within an FFmpeg run."""

    if (
        not math.isfinite(file_start_time)
        or not math.isfinite(file_duration)
        or file_start_time < 0
        or file_duration <= 0
    ):
        raise ValueError("Invalid media timing values")

    if first_segment:
        start = file_start_time
    else:
        start = entry.media_start + file_start_time

    end = start + file_duration

    tolerance = 0.1

    if start < entry.media_start - tolerance:
        raise ValueError("Media starts before CSV segment range")

    if end > entry.media_end + tolerance:
        raise ValueError("Media ends after CSV segment range")

    return start, end

def media_range_to_utc(
    media_start: float,
    media_end: float,
    *,
    reference_media_time: float,
    reference_utc: datetime,
) -> tuple[datetime, datetime]:
    """Convert media timestamps to UTC using a known reference."""

    if reference_utc.tzinfo is None:
        raise ValueError("UTC reference must be timezone-aware")

    if not all(
        math.isfinite(value)
        for value in (media_start, media_end, reference_media_time)
    ):
        raise ValueError("Invalid media timestamps")

    if media_start < 0 or media_end <= media_start:
        raise ValueError("Invalid media range")

    reference_utc = reference_utc.astimezone(timezone.utc)

    started_at = reference_utc + timedelta(
        seconds=media_start - reference_media_time
    )

    ended_at = reference_utc + timedelta(
        seconds=media_end - reference_media_time
    )

    return started_at, ended_at