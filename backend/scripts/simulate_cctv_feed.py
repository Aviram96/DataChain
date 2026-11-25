#!/usr/bin/env python3
"""CLI: loop a local MP4 as a continuous CCTV-style feed (Slice C / CP-C.P1).

Run from backend/ with the venv activated:

    python scripts/simulate_cctv_feed.py --source path/to/sample.mp4

Or set CCTV_SOURCE_MP4 in .env / the shell and omit --source.
Requires FFmpeg on PATH (https://ffmpeg.org/download.html).
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.services.cctv_feed_simulator import (
    CctvFeedConfig,
    CctvFeedError,
    CctvFeedSimulator,
    resolve_source_path,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulate a continuous CCTV feed by looping a local MP4.",
    )
    parser.add_argument(
        "--source",
        "-s",
        metavar="PATH",
        help="Path to source .mp4 (overrides CCTV_SOURCE_MP4)",
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
        config = CctvFeedConfig(
            source_path=source,
            ffmpeg_executable=args.ffmpeg.strip() or "ffmpeg",
        )
        simulator = CctvFeedSimulator(config)
        return simulator.run_until_signal()
    except CctvFeedError as exc:
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
