"""Tests for Pinata segment upload (CP-D.P1). HTTP is mocked."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.services.pinata_ipfs import PinataUploadError, upload_segment

CID = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"


def _segment(tmp_path: Path) -> Path:
    path = tmp_path / "cam_20260914T120000Z.mp4"
    path.write_bytes(b"\x00\x01fake-mp4")
    return path


def test_upload_segment_returns_cid(tmp_path: Path) -> None:
    path = _segment(tmp_path)
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"IpfsHash": CID}
    with patch("app.services.pinata_ipfs.requests.post", return_value=response) as post:
        assert upload_segment(path, jwt="test-jwt", timeout_seconds=5) == CID
    post.assert_called_once()
    kwargs = post.call_args.kwargs
    assert kwargs["headers"]["Authorization"] == "Bearer test-jwt"
    assert "file" in kwargs["files"]


def test_upload_segment_rejects_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.mp4"
    with pytest.raises(PinataUploadError, match="not found"):
        upload_segment(missing, jwt="test-jwt")


def test_upload_segment_rejects_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.mp4"
    path.write_bytes(b"")
    with pytest.raises(PinataUploadError, match="empty"):
        upload_segment(path, jwt="test-jwt")


def test_upload_segment_http_error(tmp_path: Path) -> None:
    path = _segment(tmp_path)
    response = MagicMock()
    response.status_code = 401
    with patch("app.services.pinata_ipfs.requests.post", return_value=response):
        with pytest.raises(PinataUploadError, match="HTTP 401"):
            upload_segment(path, jwt="test-jwt")


def test_upload_segment_network_error(tmp_path: Path) -> None:
    path = _segment(tmp_path)
    with patch(
        "app.services.pinata_ipfs.requests.post",
        side_effect=requests.ConnectionError("down"),
    ):
        with pytest.raises(PinataUploadError, match="Pinata upload failed"):
            upload_segment(path, jwt="test-jwt")


def test_upload_segment_missing_cid(tmp_path: Path) -> None:
    path = _segment(tmp_path)
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {}
    with patch("app.services.pinata_ipfs.requests.post", return_value=response):
        with pytest.raises(PinataUploadError, match="IpfsHash"):
            upload_segment(path, jwt="test-jwt")
