#!/usr/bin/env python3
"""CLI: receive registered camera streams and write 1-minute MP4 segments.

Integrity-checked minutes are uploaded to Pinata, anchored on Polygon, and
saved in PostgreSQL. Temp files are deleted only after that succeeds.
Unexpected FFmpeg stops restart up to a cap; then the camera is marked offline.

Run from backend/ with the venv activated and Postgres available:

    python scripts/ingest_camera.py --camera-id UUID
    python scripts/ingest_camera.py --all
    python scripts/ingest_camera.py --supervise

Requires FFmpeg on PATH (https://ffmpeg.org/download.html).
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from pathlib import Path
from uuid import UUID

# `python scripts/ingest_camera.py` puts scripts/ on sys.path. Pytest already
# adds the backend root (pyproject.toml pythonpath); do the same here.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.db.session import get_engine, get_sessionmaker  # noqa: E402
from app.services.camera_ingest import (  # noqa: E402
    CameraIngest,
    CameraIngestConfig,
    ingest_config_for_camera,
    ingest_configs_for_all_active,
)
from app.services.camera_stream import CameraStreamError  # noqa: E402
from app.services.cctv_feed_simulator import DEFAULT_FFMPEG  # noqa: E402
from app.services.ingest_supervisor import (  # noqa: E402
    IngestSupervisor,
    PostgresIngestLock,
    install_supervisor_signals,
    manual_ingest_available,
)
from app.services.video_chunker import (  # noqa: E402
    resolve_chunk_duration_seconds,
    resolve_temp_dir,
)

import app.models  # noqa: E402,F401  — register ORM mappers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Receive camera streams, write 1-minute MP4 segments under temp/, "
            "and keep them staged until processing succeeds. "
            "Temp files are deleted only after processing succeeds. "
            "Unexpected FFmpeg stops restart up to a cap, then the camera "
            "is marked offline."
        ),
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--camera-id",
        metavar="UUID",
        help="Ingest one active camera by id",
    )
    target.add_argument(
        "--all",
        action="store_true",
        help="Ingest every active (non-deleted) camera",
    )
    target.add_argument(
        "--supervise",
        action="store_true",
        help=(
            "Watch active cameras and record each one. New and restored "
            "cameras are picked up; archived cameras stop. Does not run "
            "inside the API."
        ),
    )
    parser.add_argument(
        "--ffmpeg",
        metavar="EXE",
        default=DEFAULT_FFMPEG,
        help="FFmpeg executable name or path (default: ffmpeg)",
    )
    parser.add_argument(
        "--temp-dir",
        "-t",
        metavar="DIR",
        help=(
            "Base temp directory (default backend/temp; each camera gets a "
            "subfolder). Segments stay there until processing succeeds."
        ),
    )
    parser.add_argument(
        "--duration",
        "-d",
        type=int,
        metavar="SECONDS",
        help="Segment length in seconds (default 60)",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help=(
            "Play the source in real time and repeat it, so a file or HTTP "
            "MP4 behaves like a camera that does not end."
        ),
    )
    return parser.parse_args(argv)


def _run_one(config: CameraIngestConfig, session_factory, lock) -> int:
    if not manual_ingest_available(lock, config.camera_id):
        return 1
    try:
        return CameraIngest(config, session_factory=session_factory).run_until_signal()
    finally:
        lock.release(config.camera_id)


def _run_all(configs: list[CameraIngestConfig], session_factory, lock) -> int:
    if not configs:
        logging.error("No active cameras to ingest.")
        return 1
    claimed = [
        config for config in configs if manual_ingest_available(lock, config.camera_id)
    ]
    if not claimed:
        return 1
    ingests = [
        CameraIngest(config, session_factory=session_factory) for config in claimed
    ]
    threads = [
        threading.Thread(
            target=ingest.run_until_signal,
            name=f"ingest-{ingest.camera_id}",
            daemon=True,
        )
        for ingest in ingests
    ]
    for thread in threads:
        thread.start()
    logging.info("Chunking %s camera stream(s); Ctrl+C to stop", len(ingests))
    try:
        while any(thread.is_alive() for thread in threads):
            time.sleep(0.5)
    except KeyboardInterrupt:
        logging.info("Stopping camera ingest")
        for ingest in ingests:
            ingest.stop()
    finally:
        for ingest, thread in zip(ingests, threads, strict=True):
            thread.join(timeout=10)
            if thread.is_alive():
                logging.error(
                    "Ingest for camera %s did not stop; keeping its lock",
                    ingest.camera_id,
                )
                continue
            lock.release(ingest.camera_id)
    return 0


def _run_supervise(
    session_factory,
    lock,
    ffmpeg: str,
    temp_dir: Path,
    duration: int,
    loop_source: bool,
) -> int:
    supervisor = IngestSupervisor(
        session_factory=session_factory,
        lock=lock,
        temp_dir=temp_dir,
        ffmpeg_executable=ffmpeg,
        segment_duration_seconds=duration,
        loop_source=loop_source,
    )
    install_supervisor_signals(supervisor)
    return supervisor.run()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    ffmpeg = args.ffmpeg.strip() or DEFAULT_FFMPEG
    temp_dir = resolve_temp_dir(args.temp_dir)
    duration = resolve_chunk_duration_seconds(args.duration)
    SessionLocal = get_sessionmaker()
    lock = PostgresIngestLock(get_engine())
    if args.supervise:
        try:
            return _run_supervise(
                SessionLocal,
                lock,
                ffmpeg,
                temp_dir,
                duration,
                args.loop,
            )
        except FileNotFoundError:
            logging.error(
                "FFmpeg not found (%r). Install FFmpeg and ensure it is on PATH.",
                ffmpeg,
            )
            return 127
    db = SessionLocal()
    one: CameraIngestConfig | None = None
    many: list[CameraIngestConfig] | None = None
    try:
        if args.camera_id:
            camera_id = UUID(args.camera_id)
            one = ingest_config_for_camera(
                db,
                camera_id,
                ffmpeg_executable=ffmpeg,
                temp_dir=temp_dir,
                segment_duration_seconds=duration,
                loop_source=args.loop,
            )
        else:
            many = ingest_configs_for_all_active(
                db,
                ffmpeg_executable=ffmpeg,
                temp_dir=temp_dir,
                segment_duration_seconds=duration,
                loop_source=args.loop,
            )
    except CameraStreamError as exc:
        logging.error("%s", exc)
        return 1
    except ValueError:
        logging.error("Invalid camera id: %s", args.camera_id)
        return 1
    finally:
        db.close()

    try:
        if one is not None:
            return _run_one(one, SessionLocal, lock)
        return _run_all(many or [], SessionLocal, lock)
    except FileNotFoundError:
        logging.error(
            "FFmpeg not found (%r). Install FFmpeg and ensure it is on PATH.",
            ffmpeg,
        )
        return 127


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
