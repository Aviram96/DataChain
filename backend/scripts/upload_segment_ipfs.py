#!/usr/bin/env python3
"""CLI: upload one local video segment to IPFS via Pinata (CP-D.P1).

Run from backend/ with the venv activated and PINATA_JWT set in .env:

    python scripts/upload_segment_ipfs.py path/to/segment.mp4

Prints the CID on success. Does not delete the file or write the database.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import app.database  # noqa: F401  — load backend/.env
from app.services.pinata_ipfs import PinataUploadError, upload_segment

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload one MP4 segment to Pinata and print its IPFS CID.",
    )
    parser.add_argument(
        "path",
        type=Path,
        help="Local segment file (typically under backend/temp/)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        cid = upload_segment(args.path)
    except (PinataUploadError, RuntimeError) as exc:
        logging.error("%s", exc)
        return 1
    print(cid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
