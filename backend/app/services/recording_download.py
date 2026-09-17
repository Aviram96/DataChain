"""Combine one-minute recordings into one MP4 for download (Slice E / CP-E.P10)."""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import requests

from app.config import get_ipfs_gateway_base, get_ipfs_gateway_timeout_seconds
from app.services.cctv_feed_simulator import DEFAULT_FFMPEG

logger = logging.getLogger(__name__)

MAX_DOWNLOAD_SEGMENTS = 24 * 60
CONCAT_LIST_NAME = "concat.txt"
COMBINED_NAME = "combined.mp4"

FetchOne = Callable[[str, Path], None]
ConcatOnce = Callable[[list[Path], Path], None]


class RecordingDownloadError(Exception):
    """IPFS fetch or FFmpeg concat failed."""

    def __init__(self, detail: str, status_code: int = 502) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def ipfs_gateway_url(cid: str, *, gateway: str | None = None) -> str:
    base = (gateway or get_ipfs_gateway_base()).rstrip("/")
    trimmed = cid.strip()
    return f"{base}/ipfs/{trimmed}"


def download_filename(started_at: datetime, ended_at: datetime) -> str:
    return (
        f"recordings_{_stamp(started_at)}_{_stamp(ended_at)}.mp4"
    )


def write_concat_list(segment_names: list[str], list_path: Path) -> None:
    lines = [f"file '{name}'" for name in segment_names]
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_concat_copy_command(ffmpeg: str, list_name: str, output_name: str) -> list[str]:
    return [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        list_name,
        "-c",
        "copy",
        output_name,
    ]


def fetch_cid_to_file(
    cid: str,
    dest: Path,
    *,
    gateway: str | None = None,
    timeout_seconds: float | None = None,
) -> None:
    trimmed = cid.strip()
    if not trimmed:
        raise RecordingDownloadError("A recording is missing its IPFS CID.")
    url = ipfs_gateway_url(trimmed, gateway=gateway)
    timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else get_ipfs_gateway_timeout_seconds()
    )
    try:
        with requests.get(url, stream=True, timeout=timeout) as response:
            if response.status_code != 200:
                raise RecordingDownloadError(
                    "Could not retrieve a segment from IPFS.",
                    502,
                )
            with dest.open("wb") as handle:
                for chunk in response.iter_content(64 * 1024):
                    if chunk:
                        handle.write(chunk)
    except requests.RequestException as exc:
        raise RecordingDownloadError(
            "Could not retrieve a segment from IPFS.",
            502,
        ) from exc
    if dest.stat().st_size <= 0:
        raise RecordingDownloadError("Could not retrieve a segment from IPFS.", 502)


def concat_mp4s(
    segment_paths: list[Path],
    output: Path,
    *,
    ffmpeg: str = DEFAULT_FFMPEG,
    timeout_seconds: float = 300.0,
) -> None:
    if not segment_paths:
        raise RecordingDownloadError("No recordings in that range.", 404)
    work = output.parent
    list_path = work / CONCAT_LIST_NAME
    write_concat_list([path.name for path in segment_paths], list_path)
    command = build_concat_copy_command(ffmpeg, list_path.name, output.name)
    try:
        completed = subprocess.run(
            command,
            cwd=work,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RecordingDownloadError(
            "FFmpeg is required to combine recordings.",
            503,
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RecordingDownloadError(
            "Combining recordings took too long. Try a shorter range.",
            504,
        ) from exc
    if completed.returncode != 0 or not output.is_file() or output.stat().st_size <= 0:
        logger.error(
            "FFmpeg concat failed: %s",
            (completed.stderr or b"").decode("utf-8", errors="replace")[-500:],
        )
        raise RecordingDownloadError("Could not combine recordings into one file.", 502)


def assemble_range_download(
    cids: list[str],
    work_dir: Path,
    *,
    fetch_one: FetchOne | None = None,
    concat: ConcatOnce | None = None,
) -> Path:
    """Fetch each CID from the IPFS gateway and concat into ``combined.mp4``."""
    if len(cids) > MAX_DOWNLOAD_SEGMENTS:
        raise RecordingDownloadError(
            "Choose a range of 24 hours or less to download.",
            400,
        )
    work_dir.mkdir(parents=True, exist_ok=True)
    fetch = fetch_one if fetch_one is not None else fetch_cid_to_file
    merge = concat if concat is not None else concat_mp4s
    segment_paths: list[Path] = []
    for index, cid in enumerate(cids):
        dest = work_dir / f"{index:04d}.mp4"
        fetch(cid, dest)
        segment_paths.append(dest)
    output = work_dir / COMBINED_NAME
    merge(segment_paths, output)
    return output


def _stamp(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
