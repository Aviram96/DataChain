"""Unique segment filenames: camera ID + recording time (Slice C / CP-C.P4).

The filename ends in a literal ``Z``. Ingest runs FFmpeg with ``TZ=UTC`` because
``-strftime`` otherwise expands in local time and the stamp would be read as
UTC twice. Start/end times come from that UTC stamp plus the segment duration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

SEGMENT_TIME_FORMAT = "%Y%m%dT%H%M%SZ"
SEGMENT_NAME_RE = re.compile(
    r"^(?P<camera_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})_"
    r"(?P<started>\d{8}T\d{6}Z)\.mp4$"
)


class SegmentIdentityError(Exception):
    """Filename is not a camera+time segment name."""


@dataclass(frozen=True)
class SegmentIdentity:
    """Camera and time window encoded in a segment filename."""

    camera_id: UUID
    started_at: datetime
    ended_at: datetime
    path: Path


def camera_segment_pattern(camera_id: UUID) -> str:
    """FFmpeg strftime pattern unique per camera and recording start time."""
    return f"{camera_id}_{SEGMENT_TIME_FORMAT}.mp4"


def parse_segment_path(
    path: Path,
    *,
    duration_seconds: int,
) -> SegmentIdentity:
    """Read camera id, start, and end timestamps from a segment filename."""
    match = SEGMENT_NAME_RE.match(path.name)
    if match is None:
        raise SegmentIdentityError(f"Not a camera+time segment name: {path.name}")
    started_at = datetime.strptime(match.group("started"), SEGMENT_TIME_FORMAT).replace(
        tzinfo=timezone.utc
    )
    return SegmentIdentity(
        camera_id=UUID(match.group("camera_id")),
        started_at=started_at,
        ended_at=started_at + timedelta(seconds=duration_seconds),
        path=path,
    )
