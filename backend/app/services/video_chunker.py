"""Split video input into fixed-duration MP4 segments under backend/temp/."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from app.services.cctv_feed_simulator import (
    DEFAULT_FFMPEG,
    validate_source_mp4,
)
from app.services.ffmpeg_supervisor import (
    FFmpegRunConfig,
    FFmpegSupervisor,
    resolve_max_restarts,
    resolve_restart_delay_seconds,
)

if TYPE_CHECKING:
    from app.services.chunk_processing_worker import ChunkProcessingWorker

logger = logging.getLogger(__name__)

ENV_TEMP_DIR = "CCTV_TEMP_DIR"
ENV_CHUNK_DURATION_SECONDS = "CCTV_CHUNK_DURATION_SECONDS"
DEFAULT_CHUNK_DURATION_SECONDS = 60
DEFAULT_SEGMENT_PATTERN = "chunk_%03d.mp4"
BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


class VideoChunkerError(Exception):
    """Invalid chunker configuration or runtime failure."""


@dataclass(frozen=True)
class VideoChunkerConfig:
    """Settings for FFmpeg segment output."""

    source_path: Path
    temp_dir: Path
    segment_duration_seconds: int = DEFAULT_CHUNK_DURATION_SECONDS
    ffmpeg_executable: str = DEFAULT_FFMPEG
    loop_source: bool = False
    segment_pattern: str = DEFAULT_SEGMENT_PATTERN
    input_uri: str | None = None
    extra_input_args: tuple[str, ...] = ()
    restart_on_crash: bool | None = None
    strftime_output: bool = False


def resolve_temp_dir(cli_path: str | None = None) -> Path:
    """Resolve output directory from CLI flag, then CCTV_TEMP_DIR, then backend/temp."""
    if cli_path and cli_path.strip():
        return Path(cli_path.strip()).expanduser().resolve()
    env_path = os.getenv(ENV_TEMP_DIR, "").strip()
    if env_path:
        return Path(env_path).expanduser().resolve()
    return (BACKEND_ROOT / "temp").resolve()


def resolve_chunk_duration_seconds(cli_value: int | None = None) -> int:
    """Resolve segment length; default 60 seconds (1 minute)."""
    if cli_value is not None:
        return _clamp_chunk_duration(cli_value)
    raw = os.getenv(ENV_CHUNK_DURATION_SECONDS, "").strip()
    if raw:
        try:
            return _clamp_chunk_duration(int(raw))
        except ValueError:
            pass
    return DEFAULT_CHUNK_DURATION_SECONDS


def _clamp_chunk_duration(seconds: int) -> int:
    if seconds < 1:
        raise VideoChunkerError("Chunk duration must be at least 1 second")
    return min(seconds, 3600)


def ensure_temp_dir(path: Path) -> Path:
    """Create temp directory if missing."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def segment_output_path(config: VideoChunkerConfig) -> Path:
    """Full path template passed to FFmpeg segment muxer."""
    return config.temp_dir / config.segment_pattern


def ffmpeg_input(config: VideoChunkerConfig) -> str:
    """Return the FFmpeg ``-i`` value: live URL when set, otherwise the file path."""
    if config.input_uri and config.input_uri.strip():
        return config.input_uri.strip()
    return str(config.source_path)


def _is_mjpeg_uri(uri: str) -> bool:
    path = uri.lower().split("?", 1)[0]
    return path.endswith(".mjpg") or path.endswith(".mjpeg")


def output_codec_args(config: VideoChunkerConfig) -> list[str]:
    """Copy compressed camera streams. Encode a browser MJPEG feed to H.264."""
    if _is_mjpeg_uri(ffmpeg_input(config)):
        return [
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
        ]
    return ["-c", "copy"]


def build_ffmpeg_chunk_command(config: VideoChunkerConfig) -> list[str]:
    """Build FFmpeg args: segment muxer, MP4 chunks of fixed duration."""
    cmd = [
        config.ffmpeg_executable,
        "-hide_banner",
        "-loglevel",
        "warning",
    ]
    if config.extra_input_args:
        cmd.extend(config.extra_input_args)
    if config.loop_source:
        cmd.extend(["-re", "-stream_loop", "-1"])
    cmd.extend(
        [
            "-i",
            ffmpeg_input(config),
            *output_codec_args(config),
            "-f",
            "segment",
            "-segment_time",
            str(config.segment_duration_seconds),
            "-reset_timestamps",
            "1",
            "-segment_format",
            "mp4",
        ]
    )
    if config.strftime_output:
        cmd.extend(["-strftime", "1"])
    cmd.append(str(segment_output_path(config)))
    return cmd


def list_chunk_files(temp_dir: Path, pattern: str = DEFAULT_SEGMENT_PATTERN) -> list[Path]:
    """Return chunk files matching the segment naming pattern, sorted by name."""
    prefix = pattern.split("%")[0]
    suffix = ".mp4"
    files = [
        path
        for path in temp_dir.iterdir()
        if path.is_file() and path.name.startswith(prefix) and path.suffix == suffix
    ]
    return sorted(files, key=lambda path: path.name)


class VideoChunker:
    """Run FFmpeg that writes fixed-duration MP4 segments to temp/."""

    def __init__(self, config: VideoChunkerConfig) -> None:
        self._config = config

    def run_until_signal(
        self,
        worker: ChunkProcessingWorker | None = None,
    ) -> int:
        """Start chunker; restart FFmpeg on crash when looping or live ingest."""
        if not self._config.input_uri:
            validate_source_mp4(self._config.source_path)
        ensure_temp_dir(self._config.temp_dir)
        restart_on_crash = (
            self._config.restart_on_crash
            if self._config.restart_on_crash is not None
            else self._config.loop_source
        )
        mode = "looping" if self._config.loop_source else "one pass"
        if self._config.input_uri:
            mode = "live stream"
        restart_note = "auto-restart on crash" if restart_on_crash else "no restart"
        logger.info(
            "Chunking %s into %ss segments under %s (%s; %s; Ctrl+C to stop)",
            ffmpeg_input(self._config),
            self._config.segment_duration_seconds,
            self._config.temp_dir,
            mode,
            restart_note,
        )
        run_config = FFmpegRunConfig(
            build_command=lambda: build_ffmpeg_chunk_command(self._config),
            restart_on_crash=restart_on_crash,
            restart_delay_seconds=resolve_restart_delay_seconds(),
            max_restarts=resolve_max_restarts(),
        )
        supervisor = FFmpegSupervisor(run_config)
        try:
            if worker is not None:
                worker.start()
            code = supervisor.run_until_signal()
            chunks = list_chunk_files(
                self._config.temp_dir,
                self._config.segment_pattern,
            )
            logger.info("Wrote %d chunk file(s) to %s", len(chunks), self._config.temp_dir)
            if supervisor.restart_count:
                logger.info("FFmpeg restarted %s time(s) after crash", supervisor.restart_count)
            return code
        finally:
            if worker is not None:
                worker.stop(flush=True)
