"""Read FFmpeg segment timeline data and map it to server time.

The CSV clock is the stream timeline of one FFmpeg run. The filename stamp is
the server time when the segment muxer opened that file, floored to a second.
It is not a camera capture time. One reference pair per run places every
segment on that server clock.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

from app.services.segment_identity import SEGMENT_NAME_RE, SEGMENT_TIME_FORMAT


@dataclass(frozen=True)
class SegmentTimelineEntry:
    filename: str
    media_start: float
    media_end: float


@dataclass(frozen=True)
class SegmentUtcWindow:
    """Playable server-time window for one segment.

    ``reference_kind`` records which server-time sample was used.
    ``second_segment`` is the filename and CSV start of the run's second
    segment. ``single_segment`` is the only file's open time paired with its
    container start time, and only after the run has closed.
    """

    started_at: datetime
    ended_at: datetime
    reference_media_time: float
    reference_utc: datetime
    reference_kind: str


class SegmentTimelineNotReady(Exception):
    """The run does not yet have a server-time reference."""


class SegmentTimelinePermanentError(ValueError):
    """Waiting will not make this timeline valid."""


def closed_marker_path(csv_path: Path) -> Path:
    """Marker written after this run's FFmpeg process has exited.

    A missing marker means the run is still active. That includes a backend
    stop that happens before the marker can be written.
    """
    return csv_path.with_name(f"{csv_path.name}.closed")


def is_segment_run_closed(csv_path: Path) -> bool:
    """True when the closed marker for this CSV is present."""
    return closed_marker_path(csv_path).is_file()


def mark_segment_run_closed(csv_path: Path) -> Path:
    """Write the closed marker for a timeline CSV.

    Callers may do this only after that run's FFmpeg process has exited and
    the muxer has finished writing the CSV.
    """
    marker = closed_marker_path(csv_path)
    marker.write_text("", encoding="utf-8")
    return marker


def read_segment_timeline(
    csv_path: Path,
    *,
    run_closed: bool = False,
) -> list[SegmentTimelineEntry]:
    """Read and validate segment entries from an FFmpeg CSV file.

    A trailing partial line is ignored while the run is active, because
    FFmpeg may still be writing it. After the run is closed, that partial
    line is an error: the file will not gain a terminating newline later.
    """
    text = _timeline_text(csv_path, run_closed=run_closed)
    entries: list[SegmentTimelineEntry] = []
    for row in csv.reader(StringIO(text)):
        if len(row) != 3:
            raise SegmentTimelinePermanentError("Invalid segment CSV row")

        filename, start, end = row
        if not filename.endswith(".mp4") or Path(filename).name != filename:
            raise SegmentTimelinePermanentError("Invalid segment filename")

        media_start = float(start)
        media_end = float(end)
        if (
            not math.isfinite(media_start)
            or not math.isfinite(media_end)
            or media_start < 0
            or media_end <= media_start
        ):
            raise SegmentTimelinePermanentError("Invalid segment timeline values")

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
    _require_segment_filename(segment_filename)
    matches: list[SegmentTimelineEntry] = []
    for _csv_path, entries, _closed in _read_run_timelines(temp_dir):
        for entry in entries:
            if entry.filename == segment_filename:
                matches.append(entry)

    if len(matches) > 1:
        raise SegmentTimelinePermanentError(
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
        raise SegmentTimelinePermanentError("Invalid media timing values")

    if first_segment:
        start = file_start_time
    else:
        start = entry.media_start + file_start_time

    end = start + file_duration
    tolerance = 0.1
    if start < entry.media_start - tolerance:
        raise SegmentTimelinePermanentError("Media starts before CSV segment range")
    if end > entry.media_end + tolerance:
        raise SegmentTimelinePermanentError("Media ends after CSV segment range")
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
        raise SegmentTimelinePermanentError("UTC reference must be timezone-aware")

    if not all(
        math.isfinite(value) for value in (media_start, media_end, reference_media_time)
    ):
        raise SegmentTimelinePermanentError("Invalid media timestamps")

    if media_start < 0 or media_end <= media_start:
        raise SegmentTimelinePermanentError("Invalid media range")

    reference_utc = reference_utc.astimezone(timezone.utc)
    started_at = reference_utc + timedelta(seconds=media_start - reference_media_time)
    ended_at = reference_utc + timedelta(seconds=media_end - reference_media_time)
    return started_at, ended_at


def resolve_segment_utc_window(
    temp_dir: Path,
    segment_filename: str,
    *,
    file_start_time: float,
    file_duration: float,
) -> SegmentUtcWindow:
    """Map one segment onto server time using its run's single reference.

    The reference is the second segment's filename time and CSV media start
    when that row exists. A closed run with only one segment uses that
    file's open time and the container ``start_time`` instead. An active run
    that does not yet have a second row raises ``SegmentTimelineNotReady``.
    """
    _require_segment_filename(segment_filename)
    runs = _read_run_timelines(temp_dir)
    found: list[tuple[list[SegmentTimelineEntry], int, bool]] = []
    any_active = False
    for _csv_path, rows, closed in runs:
        if not closed:
            any_active = True
        for index, entry in enumerate(rows):
            if entry.filename == segment_filename:
                found.append((rows, index, closed))

    if len(found) > 1:
        raise SegmentTimelinePermanentError(
            f"Duplicate timeline entries for segment: {segment_filename}"
        )
    if not found:
        if not runs or any_active:
            raise SegmentTimelineNotReady(
                f"Segment timeline is not ready: {segment_filename}"
            )
        raise SegmentTimelinePermanentError(
            f"Segment is not in a closed timeline: {segment_filename}"
        )

    rows, index, closed = found[0]
    entry = rows[index]
    media_start, media_end = calculate_segment_media_range(
        entry,
        file_start_time=file_start_time,
        file_duration=file_duration,
        first_segment=(index == 0),
    )
    if len(rows) >= 2:
        reference_media_time = rows[1].media_start
        reference_utc = _filename_open_time(rows[1].filename)
        reference_kind = "second_segment"
    elif closed:
        reference_media_time = file_start_time
        reference_utc = _filename_open_time(rows[0].filename)
        reference_kind = "single_segment"
    else:
        raise SegmentTimelineNotReady(
            f"Waiting for a second segment or run closure: {segment_filename}"
        )

    started_at, ended_at = media_range_to_utc(
        media_start,
        media_end,
        reference_media_time=reference_media_time,
        reference_utc=reference_utc,
    )
    return SegmentUtcWindow(
        started_at=started_at,
        ended_at=ended_at,
        reference_media_time=reference_media_time,
        reference_utc=reference_utc,
        reference_kind=reference_kind,
    )


def _timeline_text(csv_path: Path, *, run_closed: bool) -> str:
    content = csv_path.read_bytes()
    if content and not content.endswith(b"\n"):
        if run_closed:
            raise SegmentTimelinePermanentError(
                f"Segment CSV may contain an incomplete row: {csv_path.name}"
            )
        newline = content.rfind(b"\n")
        content = content[: newline + 1] if newline >= 0 else b""
    return content.decode("utf-8")


def _read_run_timelines(
    temp_dir: Path,
) -> list[tuple[Path, list[SegmentTimelineEntry], bool]]:
    runs: list[tuple[Path, list[SegmentTimelineEntry], bool]] = []
    for csv_path in sorted(temp_dir.glob("segments_*.csv")):
        closed = is_segment_run_closed(csv_path)
        rows = read_segment_timeline(csv_path, run_closed=closed)
        runs.append((csv_path, rows, closed))
    return runs


def _require_segment_filename(segment_filename: str) -> None:
    if (
        not segment_filename.endswith(".mp4")
        or Path(segment_filename).name != segment_filename
    ):
        raise SegmentTimelinePermanentError("Invalid segment filename")


def _filename_open_time(filename: str) -> datetime:
    """Server file-open time encoded in a camera segment filename."""
    match = SEGMENT_NAME_RE.match(filename)
    if match is None:
        raise SegmentTimelinePermanentError(
            f"Segment filename has no server timestamp: {filename}"
        )
    opened = datetime.strptime(match.group("started"), SEGMENT_TIME_FORMAT)
    return opened.replace(tzinfo=timezone.utc)
