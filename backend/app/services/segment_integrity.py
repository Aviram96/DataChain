"""Basic integrity check for closed MP4 segments (Slice C / CP-C.P5).

A segment may proceed to the next stage only when it is a complete MP4
(ftyp + moov), has a video stream, and a SHA-256 fingerprint can be taken.
Identity (camera + time window) is required for camera ingest filenames.
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.services.cctv_feed_simulator import DEFAULT_FFMPEG
from app.services.segment_identity import (
    SegmentIdentity,
    SegmentIdentityError,
    parse_segment_path,
)
from app.services.segment_timeline import SegmentTimelinePermanentError

DEFAULT_FFPROBE = "ffprobe"
INCOMPLETE_MP4_ERROR = "Incomplete MP4 (missing ftyp or moov)"
_HASH_CHUNK_SIZE = 1024 * 1024


class SegmentIntegrityError(Exception):
    """Segment failed the pre-stage integrity check."""


@dataclass(frozen=True)
class SegmentIntegrityResult:
    """Outcome of a basic segment integrity check."""

    ok: bool
    path: Path
    error: str | None = None
    sha256: str | None = None
    size_bytes: int = 0
    identity: SegmentIdentity | None = None


VideoProbe = Callable[[Path], bool]


def ffprobe_executable_for(ffmpeg_executable: str) -> str:
    """Derive ffprobe path/name from an ffmpeg executable."""
    path = Path(ffmpeg_executable)
    probe_name = path.name.replace("ffmpeg", DEFAULT_FFPROBE).replace(
        "FFmpeg", DEFAULT_FFPROBE
    )
    if path.parent == Path("."):
        return probe_name
    return str(path.with_name(probe_name))


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of a file, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(_HASH_CHUNK_SIZE)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def mp4_has_ftyp_and_moov(path: Path) -> bool:
    """True when the file contains complete ``ftyp`` and ``moov`` boxes."""
    found: set[bytes] = set()
    try:
        with path.open("rb") as handle:
            while True:
                header = handle.read(8)
                if len(header) < 8:
                    break
                size = int.from_bytes(header[:4], "big")
                box_type = header[4:8]
                header_len = 8
                if size == 1:
                    large = handle.read(8)
                    if len(large) < 8:
                        break
                    size = int.from_bytes(large, "big")
                    header_len = 16
                elif size == 0:
                    found.add(box_type)
                    break
                if size < header_len:
                    break
                payload = size - header_len
                found.add(box_type)
                if b"ftyp" in found and b"moov" in found:
                    return True
                handle.seek(payload, 1)
    except OSError:
        return False
    return b"ftyp" in found and b"moov" in found


def file_has_video_stream(
    path: Path,
    *,
    ffprobe_executable: str = DEFAULT_FFPROBE,
) -> bool:
    """True when ffprobe reports a video stream on the file."""
    cmd = [
        ffprobe_executable,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "csv=p=0",
        str(path),
    ]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SegmentIntegrityError(
            f"ffprobe not found ({ffprobe_executable!r}). "
            "Install FFmpeg (includes ffprobe) and ensure it is on PATH."
        ) from exc
    except subprocess.TimeoutExpired:
        return False
    if completed.returncode != 0:
        return False
    return "video" in completed.stdout.lower()


def probe_video_duration_seconds(
    path: Path,
    *,
    ffprobe_executable: str = DEFAULT_FFPROBE,
) -> float:
    """Return the duration of an MP4 file in seconds."""

    cmd = [
        ffprobe_executable,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]

    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise SegmentIntegrityError("Could not determine video duration.") from exc

    if completed.returncode != 0:
        raise SegmentIntegrityError("Could not determine video duration.")

    try:
        duration = float(completed.stdout.strip())
    except ValueError as exc:
        raise SegmentIntegrityError(
            "Invalid video duration returned by ffprobe."
        ) from exc

    if not (0 < duration < float("inf")):
        raise SegmentIntegrityError("Invalid video duration returned by ffprobe.")

    return duration


def probe_video_timing(
    path: Path,
    *,
    ffprobe_executable: str = DEFAULT_FFPROBE,
) -> tuple[float, float]:
    """Return container ``start_time`` and ``duration`` in seconds.

    Both values are required to map a segment onto the FFmpeg timeline.
    A probe that runs but omits either value will not succeed later, so
    that result is a permanent timeline error.
    """
    cmd = [
        ffprobe_executable,
        "-v",
        "error",
        "-show_entries",
        "format=start_time,duration",
        "-of",
        "default=noprint_wrappers=1",
        str(path),
    ]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise SegmentIntegrityError("Could not determine video timing.") from exc
    if completed.returncode != 0:
        raise SegmentIntegrityError("Could not determine video timing.")

    values: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        if "=" not in line:
            continue
        key, raw = line.split("=", 1)
        values[key.strip()] = raw.strip()

    start_raw = values.get("start_time", "")
    duration_raw = values.get("duration", "")
    if start_raw in ("", "N/A") or duration_raw in ("", "N/A"):
        raise SegmentTimelinePermanentError(
            "ffprobe did not return a start time and duration"
        )
    try:
        start_time = float(start_raw)
        duration = float(duration_raw)
    except ValueError as exc:
        raise SegmentTimelinePermanentError(
            "Invalid video timing returned by ffprobe."
        ) from exc
    if (
        start_time < 0
        or start_time == float("inf")
        or not (0 < duration < float("inf"))
    ):
        raise SegmentTimelinePermanentError("Invalid video timing returned by ffprobe.")
    return start_time, duration


def check_segment(
    path: Path,
    *,
    duration_seconds: int,
    require_identity: bool = True,
    probe_video: VideoProbe | None = None,
    ffprobe_executable: str = DEFAULT_FFPROBE,
) -> SegmentIntegrityResult:
    """Run the basic integrity check. Does not raise for expected failures."""
    if not path.is_file():
        return SegmentIntegrityResult(
            ok=False, path=path, error=f"Segment file missing: {path.name}"
        )
    try:
        size_bytes = path.stat().st_size
    except OSError as exc:
        return SegmentIntegrityResult(
            ok=False, path=path, error=f"Cannot stat segment: {exc}"
        )
    if size_bytes <= 0:
        return SegmentIntegrityResult(
            ok=False, path=path, error="Segment file is empty", size_bytes=0
        )

    identity: SegmentIdentity | None = None
    if require_identity:
        try:
            identity = parse_segment_path(path, duration_seconds=duration_seconds)
        except SegmentIdentityError as exc:
            return SegmentIntegrityResult(
                ok=False,
                path=path,
                error=str(exc),
                size_bytes=size_bytes,
            )

    if not mp4_has_ftyp_and_moov(path):
        return SegmentIntegrityResult(
            ok=False,
            path=path,
            error=INCOMPLETE_MP4_ERROR,
            size_bytes=size_bytes,
            identity=identity,
        )

    try:
        digest = sha256_file(path)
    except OSError as exc:
        return SegmentIntegrityResult(
            ok=False,
            path=path,
            error=f"Cannot hash segment: {exc}",
            size_bytes=size_bytes,
            identity=identity,
        )

    def _default_probe(candidate: Path) -> bool:
        return file_has_video_stream(candidate, ffprobe_executable=ffprobe_executable)

    probe = probe_video if probe_video is not None else _default_probe
    try:
        has_video = probe(path)
    except SegmentIntegrityError as exc:
        return SegmentIntegrityResult(
            ok=False,
            path=path,
            error=str(exc),
            sha256=digest,
            size_bytes=size_bytes,
            identity=identity,
        )
    if not has_video:
        return SegmentIntegrityResult(
            ok=False,
            path=path,
            error="No video stream detected",
            sha256=digest,
            size_bytes=size_bytes,
            identity=identity,
        )

    return SegmentIntegrityResult(
        ok=True,
        path=path,
        sha256=digest,
        size_bytes=size_bytes,
        identity=identity,
    )


def ffmpeg_default_probe_executable() -> str:
    """ffprobe sibling of the default ffmpeg name."""
    return ffprobe_executable_for(DEFAULT_FFMPEG)
