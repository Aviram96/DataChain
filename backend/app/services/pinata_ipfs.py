"""Upload one-minute video segments to IPFS via Pinata (Slice D / CP-D.P1).

Pinata has no official Python SDK; this uses the documented pinFileToIPFS
REST API. Ingest does not call this yet (temp files stay staged).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import requests

from app.config import get_pinata_jwt, get_pinata_timeout_seconds

logger = logging.getLogger(__name__)

PINATA_PIN_FILE_URL = "https://api.pinata.cloud/pinning/pinFileToIPFS"


class PinataUploadError(Exception):
    """Pinata rejected the upload or returned no CID."""


def upload_segment(
    path: Path,
    *,
    jwt: str | None = None,
    timeout_seconds: float | None = None,
) -> str:
    """Upload a local segment file to Pinata and return its IPFS CID."""
    resolved = path.resolve()
    if not resolved.is_file():
        raise PinataUploadError(f"Segment file not found: {resolved}")
    size = resolved.stat().st_size
    if size <= 0:
        raise PinataUploadError(f"Segment file is empty: {resolved}")

    token = jwt if jwt is not None else get_pinata_jwt()
    timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else get_pinata_timeout_seconds()
    )

    logger.info("Uploading segment %s (%s bytes) to Pinata", resolved.name, size)
    try:
        with resolved.open("rb") as handle:
            response = requests.post(
                PINATA_PIN_FILE_URL,
                headers={"Authorization": f"Bearer {token}"},
                files={"file": (resolved.name, handle, "video/mp4")},
                data={
                    "pinataMetadata": json.dumps({"name": resolved.name}),
                    "pinataOptions": json.dumps({"cidVersion": 1}),
                },
                timeout=timeout,
            )
    except requests.RequestException as exc:
        raise PinataUploadError(f"Pinata upload failed for {resolved.name}") from exc

    if response.status_code != 200:
        raise PinataUploadError(
            f"Pinata upload failed for {resolved.name}: HTTP {response.status_code}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise PinataUploadError(
            f"Pinata returned non-JSON for {resolved.name}"
        ) from exc

    cid = payload.get("IpfsHash")
    if not isinstance(cid, str) or not cid.strip():
        raise PinataUploadError(f"Pinata response missing IpfsHash for {resolved.name}")

    cid = cid.strip()
    logger.info("Pinned segment %s cid=%s", resolved.name, cid)
    return cid
