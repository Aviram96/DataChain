"""Loop a local MP4 as a continuous CCTV-style feed via FFmpeg (Slice C / CP-C.P1)."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from app.services.ffmpeg_supervisor import (
    FFmpegRunConfig,
    FFmpegSupervisor,
    resolve_max_restarts,
    resolve_restart_delay_seconds,
)

logger = logging.getLogger(__name__)

ENV_SOURCE_MP4 = "CCTV_SOURCE_MP4"
DEFAULT_FFMPEG = "ffmpeg"


class CctvFeedError(Exception):
    """Invalid configuration or simulator state."""


@dataclass(frozen=True)
class CctvFeedConfig:
    """Settings for the looping feed subprocess."""

    source_path: Path
    ffmpeg_executable: str = DEFAULT_FFMPEG


def resolve_source_path(cli_path: str | None = None) -> Path:
    """Resolve MP4 path from CLI flag, then CCTV_SOURCE_MP4 env."""
    if cli_path and cli_path.strip():
        return Path(cli_path.strip()).expanduser().resolve()
    env_path = os.getenv(ENV_SOURCE_MP4, "").strip()
    if env_path:
        return Path(env_path).expanduser().resolve()
    raise CctvFeedError(
        "No source MP4 configured. Pass --source PATH or set "
        f"{ENV_SOURCE_MP4} in the environment (see backend/.env.example)."
    )


def validate_source_mp4(path: Path) -> None:
    """Ensure the file exists and is an .mp4 (case-insensitive)."""
    if not path.is_file():
        raise CctvFeedError(f"Source file not found: {path}")
    if path.suffix.lower() != ".mp4":
        raise CctvFeedError(f"Source must be a .mp4 file (got {path.suffix!r}): {path}")


def build_ffmpeg_loop_command(config: CctvFeedConfig) -> list[str]:
    """Build FFmpeg args: real-time pace, infinite loop, MPEG-TS to stdout."""
    return [
        config.ffmpeg_executable,
        "-hide_banner",
        "-loglevel",
        "warning",
        "-re",
        "-stream_loop",
        "-1",
        "-i",
        str(config.source_path),
        "-c",
        "copy",
        "-f",
        "mpegts",
        "pipe:1",
    ]


class CctvFeedSimulator:
    """Run FFmpeg that loops one MP4 like a live CCTV source."""

    def __init__(self, config: CctvFeedConfig) -> None:
        self._config = config
        self._supervisor: FFmpegSupervisor | None = None

    def run_until_signal(self) -> int:
        """Start feed, restart FFmpeg on crash, stop cleanly on signal."""
        validate_source_mp4(self._config.source_path)
        logger.info(
            "Starting CCTV feed simulation from %s "
            "(Ctrl+C to stop; auto-restart on crash)",
            self._config.source_path,
        )
        run_config = FFmpegRunConfig(
            build_command=lambda: build_ffmpeg_loop_command(self._config),
            restart_on_crash=True,
            restart_delay_seconds=resolve_restart_delay_seconds(),
            max_restarts=resolve_max_restarts(),
            popen_kwargs={"stdout": sys.stdout.buffer},
        )
        self._supervisor = FFmpegSupervisor(run_config)
        return self._supervisor.run_until_signal()
