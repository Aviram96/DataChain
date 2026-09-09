"""Receive a registered camera stream and split it into 1-minute MP4 segments.

Slice C / CP-C.P2 attaches the camera URL; CP-C.P3 writes fixed-duration chunks;
CP-C.P4 names each file from camera ID and recording time; CP-C.P5 checks
integrity on each closed segment before the next stage; CP-C.P6 keeps those
files under temp/ until processing succeeds; CP-C.P7 deletes a temp file only
after processing succeeds and keeps failures for retry; CP-C.P8 restarts
FFmpeg after unexpected stop (capped) and marks the camera offline when the
cap is reached.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.models.camera import Camera
from app.services.camera_stream import (
    CameraStreamError,
    attach_camera_stream,
    get_active_camera,
    list_active_cameras,
)
from app.services.cctv_feed_simulator import DEFAULT_FFMPEG
from app.services.ffmpeg_supervisor import (
    FFmpegRunConfig,
    FFmpegSupervisor,
    resolve_max_restarts,
    resolve_restart_delay_seconds,
)
from app.services.chunk_processing_worker import (
    ChunkProcessingWorker,
    ChunkProcessingWorkerConfig,
)
from app.services.segment_identity import camera_segment_pattern
from app.services.segment_integrity import (
    SegmentIntegrityResult,
    check_segment,
    ffprobe_executable_for,
    file_has_video_stream,
)
from app.services.segment_staging import (
    staging_dir_for_camera,
    staging_worker_config,
)
from app.services.video_chunker import (
    DEFAULT_CHUNK_DURATION_SECONDS,
    VideoChunkerConfig,
    build_ffmpeg_chunk_command,
    ensure_temp_dir,
    resolve_chunk_duration_seconds,
)

logger = logging.getLogger(__name__)

DEFAULT_INGEST_MAX_RESTARTS = 10


def resolve_ingest_max_restarts() -> int:
    """Cap FFmpeg restarts for camera ingest (default 10). Env still wins."""
    env_value = resolve_max_restarts()
    if env_value is not None:
        return env_value
    return DEFAULT_INGEST_MAX_RESTARTS


def clear_ingest_offline(db: Session, camera_id: UUID) -> None:
    """Clear capture-offline so a new ingest run can show the camera online."""
    camera = get_active_camera(db, camera_id)
    if camera.ingest_offline_at is None:
        return
    camera.ingest_offline_at = None
    db.commit()
    logger.info("Cleared ingest-offline flag for camera %s", camera_id)


def mark_ingest_offline(db: Session, camera_id: UUID) -> None:
    """Record that ingest stopped after the FFmpeg restart cap."""
    camera = get_active_camera(db, camera_id)
    camera.ingest_offline_at = datetime.now(timezone.utc)
    db.commit()
    logger.error(
        "Marked camera %s offline after FFmpeg restart cap was reached",
        camera_id,
    )


def effective_camera_status(
    camera: Camera,
    probed: Literal["online", "offline"],
) -> Literal["online", "offline"]:
    """Offline if ingest marked the camera down, otherwise the live probe."""
    if camera.ingest_offline_at is not None:
        return "offline"
    return probed


def camera_offline_reason(
    camera: Camera,
    probed: Literal["online", "offline"],
) -> Literal["ingest_failed", "unreachable"] | None:
    """Why the camera is offline, or None when it is online.

    Ingest-gave-up (``ingest_offline_at``) takes precedence over a failed
    stream probe so the dashboard can distinguish capture stop from
    unreachable.
    """
    if effective_camera_status(camera, probed) == "online":
        return None
    if camera.ingest_offline_at is not None:
        return "ingest_failed"
    return "unreachable"


@dataclass(frozen=True)
class CameraIngestConfig:
    """Settings for receiving and chunking one camera stream."""

    camera_id: UUID
    stream_url: str
    ffmpeg_executable: str = DEFAULT_FFMPEG
    temp_dir: Path | None = None
    segment_duration_seconds: int = DEFAULT_CHUNK_DURATION_SECONDS


def camera_chunk_dir(camera_id: UUID, base: Path | None = None) -> Path:
    """Per-camera staging folder under temp/ (see ``staging_dir_for_camera``)."""
    return staging_dir_for_camera(camera_id, base)


def chunker_config_for_ingest(config: CameraIngestConfig) -> VideoChunkerConfig:
    """Map ingest settings to the shared FFmpeg segment muxer config."""
    extra: tuple[str, ...] = ()
    if config.stream_url.lower().startswith("rtsp://"):
        extra = ("-rtsp_transport", "tcp")
    return VideoChunkerConfig(
        source_path=Path("."),
        temp_dir=camera_chunk_dir(config.camera_id, config.temp_dir),
        segment_duration_seconds=config.segment_duration_seconds,
        ffmpeg_executable=config.ffmpeg_executable,
        input_uri=config.stream_url,
        extra_input_args=extra,
        restart_on_crash=True,
        segment_pattern=camera_segment_pattern(config.camera_id),
        strftime_output=True,
    )


def build_ffmpeg_receive_command(config: CameraIngestConfig) -> list[str]:
    """Build FFmpeg args: live camera URL into 1-minute MP4 segments."""
    return build_ffmpeg_chunk_command(chunker_config_for_ingest(config))


def integrity_worker_config_for_ingest(
    config: CameraIngestConfig,
) -> ChunkProcessingWorkerConfig:
    """Worker that integrity-checks closed segments and stages them under temp/."""
    chunk = chunker_config_for_ingest(config)
    ffprobe = ffprobe_executable_for(config.ffmpeg_executable)

    def _check(path: Path) -> SegmentIntegrityResult:
        return check_segment(
            path,
            duration_seconds=config.segment_duration_seconds,
            require_identity=True,
            probe_video=lambda candidate: file_has_video_stream(
                candidate, ffprobe_executable=ffprobe
            ),
        )

    return staging_worker_config(
        temp_dir=chunk.temp_dir,
        segment_pattern=chunk.segment_pattern,
        integrity_check=_check,
    )


def ingest_config_for_camera(
    db: Session,
    camera_id: UUID,
    *,
    ffmpeg_executable: str = DEFAULT_FFMPEG,
    temp_dir: Path | None = None,
    segment_duration_seconds: int | None = None,
) -> CameraIngestConfig:
    """Attach an active camera and return ingest settings for its stream URL."""
    camera = get_active_camera(db, camera_id)
    stream_url = attach_camera_stream(db, camera_id)
    logger.info(
        "Attached camera %s (%s) at %s",
        camera.id,
        camera.name,
        stream_url,
    )
    duration = (
        segment_duration_seconds
        if segment_duration_seconds is not None
        else resolve_chunk_duration_seconds()
    )
    return CameraIngestConfig(
        camera_id=camera.id,
        stream_url=stream_url,
        ffmpeg_executable=ffmpeg_executable,
        temp_dir=temp_dir,
        segment_duration_seconds=duration,
    )


def ingest_configs_for_all_active(
    db: Session,
    *,
    ffmpeg_executable: str = DEFAULT_FFMPEG,
    temp_dir: Path | None = None,
    segment_duration_seconds: int | None = None,
) -> list[CameraIngestConfig]:
    """Build ingest settings for every active camera."""
    cameras = list_active_cameras(db)
    return [
        ingest_config_for_camera(
            db,
            camera.id,
            ffmpeg_executable=ffmpeg_executable,
            temp_dir=temp_dir,
            segment_duration_seconds=segment_duration_seconds,
        )
        for camera in cameras
    ]


class CameraIngest:
    """Run FFmpeg against one registered camera stream until stopped."""

    def __init__(
        self,
        config: CameraIngestConfig,
        *,
        session_factory: sessionmaker | None = None,
    ) -> None:
        self._config = config
        self._session_factory = session_factory
        self._supervisor: FFmpegSupervisor | None = None

    @property
    def camera_id(self) -> UUID:
        return self._config.camera_id

    def stop(self) -> None:
        if self._supervisor is not None:
            self._supervisor.stop()

    def _with_session(self, action: Callable[[Session], None]) -> None:
        if self._session_factory is None:
            return
        db = self._session_factory()
        try:
            action(db)
        except CameraStreamError as exc:
            logger.error("%s", exc)
            db.rollback()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def run_until_signal(self) -> int:
        """Receive the stream and write 1-minute MP4 segments until stopped."""
        chunk_config = chunker_config_for_ingest(self._config)
        ensure_temp_dir(chunk_config.temp_dir)
        max_restarts = resolve_ingest_max_restarts()
        logger.info(
            "Chunking camera %s from %s into %ss segments under %s "
            "(staged until processing succeeds; FFmpeg max restarts %s)",
            self._config.camera_id,
            self._config.stream_url,
            chunk_config.segment_duration_seconds,
            chunk_config.temp_dir,
            max_restarts,
        )
        self._with_session(
            lambda db: clear_ingest_offline(db, self._config.camera_id)
        )
        run_config = FFmpegRunConfig(
            build_command=lambda: build_ffmpeg_chunk_command(chunk_config),
            restart_on_crash=True,
            restart_delay_seconds=resolve_restart_delay_seconds(),
            max_restarts=max_restarts,
            log_label=f"camera {self._config.camera_id}",
        )
        self._supervisor = FFmpegSupervisor(run_config)
        worker = ChunkProcessingWorker(integrity_worker_config_for_ingest(self._config))
        worker.start()
        try:
            code = self._supervisor.run_until_signal()
            if self._supervisor.gave_up_after_restarts:
                self._with_session(
                    lambda db: mark_ingest_offline(db, self._config.camera_id)
                )
            elif self._supervisor.restart_count:
                logger.info(
                    "FFmpeg restarted %s time(s) for camera %s",
                    self._supervisor.restart_count,
                    self._config.camera_id,
                )
            return code
        finally:
            worker.stop(flush=True)
