"""Reachability probe for camera stream URLs (Slice B / CP-B.P4).

HTTP and HTTPS stay reachable when the URL answers. RTSP is online only when
DESCRIBE of the full configured URL, including its path, returns RTSP/1.0 200.
An open port or an OPTIONS response is not enough.
"""

from __future__ import annotations

import socket
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Literal
from urllib.parse import urlparse

from app.config import get_camera_probe_timeout_seconds

DEFAULT_PORTS: dict[str, int] = {
    "http": 80,
    "https": 443,
    "rtsp": 554,
}


def resolve_stream_host_port(stream_url: str) -> tuple[str, int] | None:
    """Parse a supported stream URL into host and port, or None if invalid."""
    parsed = urlparse(stream_url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in DEFAULT_PORTS:
        return None
    host = parsed.hostname
    if not host:
        return None
    port = parsed.port if parsed.port is not None else DEFAULT_PORTS[scheme]
    return host, port


def _http_stream_reachable(stream_url: str, timeout: float) -> bool:
    """Treat any HTTP response (including 4xx/5xx) as a reachable stream host."""
    request = urllib.request.Request(
        stream_url,
        method="HEAD",
        headers={"User-Agent": "DatachainCameraProbe/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read(0)
        return True
    except urllib.error.HTTPError:
        # Server answered — endpoint is reachable.
        return True
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        # Some servers reject HEAD; retry with a ranged GET.
        get_request = urllib.request.Request(
            stream_url,
            headers={
                "User-Agent": "DatachainCameraProbe/1.0",
                "Range": "bytes=0-0",
            },
        )
        try:
            with urllib.request.urlopen(get_request, timeout=timeout) as response:
                response.read(1)
            return True
        except urllib.error.HTTPError:
            return True
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return False


def _rtsp_status_is_ok(data: bytes) -> bool:
    """True only for a complete ``RTSP/1.0 200`` status line."""
    if not data:
        return False
    line = data.split(b"\r\n", 1)[0].split(b"\n", 1)[0].strip()
    try:
        text = line.decode("ascii")
    except UnicodeDecodeError:
        return False
    parts = text.split()
    return len(parts) >= 2 and parts[0] == "RTSP/1.0" and parts[1] == "200"


def _read_rtsp_status(sock: socket.socket) -> bytes:
    """Read the status line. A timeout or closed socket returns what arrived."""
    data = b""
    while b"\r\n" not in data and b"\n" not in data and len(data) < 512:
        chunk = sock.recv(512 - len(data))
        if not chunk:
            break
        data += chunk
    return data


def _rtsp_stream_reachable(
    stream_url: str, host: str, port: int, timeout: float
) -> bool:
    """DESCRIBE the configured URL. Only RTSP/1.0 200 means the stream is up."""
    try:
        payload = (
            f"DESCRIBE {stream_url} RTSP/1.0\r\n"
            f"CSeq: 1\r\n"
            f"User-Agent: DatachainCameraProbe/1.0\r\n"
            f"Accept: application/sdp\r\n"
            f"\r\n"
        ).encode("ascii")
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(payload)
            return _rtsp_status_is_ok(_read_rtsp_status(sock))
    except (OSError, TimeoutError, UnicodeError):
        return False


def probe_stream_reachable(
    stream_url: str,
    *,
    timeout: float | None = None,
) -> bool:
    """Return True when the camera stream endpoint appears reachable."""
    target = resolve_stream_host_port(stream_url)
    if target is None:
        return False
    host, port = target
    seconds = timeout if timeout is not None else get_camera_probe_timeout_seconds()
    scheme = (urlparse(stream_url).scheme or "").lower()

    if scheme in ("http", "https"):
        return _http_stream_reachable(stream_url, seconds)
    if scheme == "rtsp":
        return _rtsp_stream_reachable(stream_url, host, port, seconds)
    return False


def probe_status(stream_url: str) -> Literal["online", "offline"]:
    """Return ``online`` or ``offline`` for a stream URL."""
    return "online" if probe_stream_reachable(stream_url) else "offline"


def probe_many_statuses(
    stream_urls: list[str],
) -> list[Literal["online", "offline"]]:
    """Probe multiple stream URLs concurrently; order matches input."""
    if not stream_urls:
        return []
    workers = min(len(stream_urls), 10)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(probe_status, stream_urls))
