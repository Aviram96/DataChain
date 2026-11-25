#!/usr/bin/env python3
"""CLI: send one Datachain.anchorSegment transaction (CP-D.P3).

Run from backend/ with the venv activated and chain env vars set:

    python scripts/anchor_segment.py --camera-id UUID --started-at 1700000000 \\
        --ended-at 1700000060 --cid bafy... --segment-hash <64 hex chars>

Prints the transaction hash. Does not delete files or write the database.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from uuid import UUID

import app.database  # noqa: F401  — load backend/.env
from app.services.chain_anchor import (
    ChainAnchorError,
    SegmentAnchorRequest,
    anchor_segment,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Anchor one segment on Polygon Amoy and print the tx hash.",
    )
    parser.add_argument("--camera-id", type=UUID, required=True)
    parser.add_argument(
        "--started-at",
        type=int,
        required=True,
        help="UTC Unix timestamp (segment start)",
    )
    parser.add_argument(
        "--ended-at",
        type=int,
        required=True,
        help="UTC Unix timestamp (segment end)",
    )
    parser.add_argument("--cid", required=True)
    parser.add_argument(
        "--segment-hash",
        required=True,
        help="SHA-256 hex from ingest integrity check",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    request = SegmentAnchorRequest(
        camera_id=args.camera_id,
        started_at=datetime.fromtimestamp(args.started_at, tz=timezone.utc),
        ended_at=datetime.fromtimestamp(args.ended_at, tz=timezone.utc),
        cid=args.cid,
        segment_hash=args.segment_hash,
    )
    try:
        tx_hash = anchor_segment(request)
    except (ChainAnchorError, RuntimeError) as exc:
        logging.error("%s", exc)
        return 1
    print(tx_hash)
    return 0


if __name__ == "__main__":
    sys.exit(main())
