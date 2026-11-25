#!/usr/bin/env python3
"""CLI: process existing temp/ chunks and delete them on success (Epic 5).

Run from backend/ after chunking (or when chunks accumulated without cleanup):

    python scripts/process_temp_chunks.py

Uses the stub processor until Epic 6 replaces it with IPFS/chain/DB steps.
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.services.chunk_processing_worker import (
    ChunkProcessingWorker,
    ChunkProcessingWorkerConfig,
)
from app.services.video_chunker import resolve_temp_dir

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Process chunk files in temp/ and delete each on success.",
    )
    parser.add_argument(
        "--temp-dir",
        "-t",
        metavar="DIR",
        help="Chunk directory (overrides CCTV_TEMP_DIR; default backend/temp)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    temp_dir = resolve_temp_dir(args.temp_dir)
    worker = ChunkProcessingWorker(ChunkProcessingWorkerConfig(temp_dir=temp_dir))
    deleted = worker.process_all_blocking()
    logging.info(
        "Cleanup complete: removed %d chunk file(s) from %s", deleted, temp_dir
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
