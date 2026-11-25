#!/usr/bin/env python3
"""CLI: chunk a local MP4 into 1-minute segments under backend/temp/ (Epic 5).

Run from backend/ with the venv activated:

    python scripts/chunk_cctv_feed.py --source path/to/sample.mp4

Continuous CCTV-style loop (never exits until Ctrl+C):

    python scripts/chunk_cctv_feed.py --source path/to/sample.mp4 --loop

Requires FFmpeg on PATH (https://ffmpeg.org/download.html).
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.services.cctv_feed_simulator import CctvFeedError
from app.services.chunk_processing_worker import (
    ChunkProcessingWorker,
    ChunkProcessingWorkerConfig,
)
from app.services.video_chunker import (
    VideoChunker,
    VideoChunkerConfig,
    VideoChunkerError,
    resolve_chunk_duration_seconds,
    resolve_source_path,
    resolve_temp_dir,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chunk a local MP4 into fixed-duration segments in temp/.",
    )
    parser.add_argument(
        "--source",
        "-s",
        metavar="PATH",
        help="Path to source .mp4 (overrides CCTV_SOURCE_MP4)",
    )
    parser.add_argument(
        "--temp-dir",
        "-t",
        metavar="DIR",
        help="Output directory (overrides CCTV_TEMP_DIR; default backend/temp)",
    )
    parser.add_argument(
        "--duration",
        "-d",
        type=int,
        metavar="SECONDS",
        help="Segment length in seconds (default 60; env CCTV_CHUNK_DURATION_SECONDS)",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Loop source at real-time pace like a live CCTV feed",
    )
    parser.add_argument(
        "--cleanup-after-success",
        action="store_true",
        help="Run background worker to process and delete each chunk from temp/",
    )
    parser.add_argument(
        "--ffmpeg",
        metavar="EXE",
        default="ffmpeg",
        help="FFmpeg executable name or path (default: ffmpeg)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        source = resolve_source_path(args.source)
        config = VideoChunkerConfig(
            source_path=source,
            temp_dir=resolve_temp_dir(args.temp_dir),
            segment_duration_seconds=resolve_chunk_duration_seconds(args.duration),
            ffmpeg_executable=args.ffmpeg.strip() or "ffmpeg",
            loop_source=args.loop,
        )
        worker = None
        if args.cleanup_after_success:
            worker = ChunkProcessingWorker(
                ChunkProcessingWorkerConfig(temp_dir=config.temp_dir),
            )
        chunker = VideoChunker(config)
        return chunker.run_until_signal(worker=worker)
    except (CctvFeedError, VideoChunkerError) as exc:
        logging.error("%s", exc)
        return 1
    except FileNotFoundError:
        logging.error(
            "FFmpeg not found (%r). Install FFmpeg and ensure it is on PATH.",
            args.ffmpeg,
        )
        return 127


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
