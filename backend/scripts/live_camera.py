#!/usr/bin/env python3
"""Serve a live MJPEG picture for the camera page and for ingest.

A video file is played in real time and repeated, so it behaves like a camera
without using this PC's webcam:

    .\\.venv\\Scripts\\python.exe scripts\\live_camera.py --source C:\\path\\sample2.mp4

Pass --device only when you want the built-in webcam instead.
The stream is http://127.0.0.1:8090/live.mjpg
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SOI = b"\xff\xd8"
EOI = b"\xff\xd9"
BOUNDARY = b"frame"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


class FrameHub:
    """Latest JPEG from the camera, shared with every browser and ingest."""

    def __init__(self) -> None:
        self._frame: bytes | None = None
        self._seq = 0
        self._cond = threading.Condition()

    def publish(self, frame: bytes) -> None:
        with self._cond:
            self._frame = frame
            self._seq += 1
            self._cond.notify_all()

    def wait_next(self, last_seq: int, timeout: float) -> tuple[int, bytes] | None:
        with self._cond:
            if self._seq == last_seq:
                self._cond.wait(timeout)
            if self._frame is None or self._seq == last_seq:
                return None
            return self._seq, self._frame


def _ffmpeg_command(
    ffmpeg: str,
    *,
    source: str | None,
    device: str | None,
) -> list[str]:
    if source:
        prefix = [
            "-re",
            "-stream_loop",
            "-1",
            "-i",
            source,
        ]
    else:
        prefix = [
            "-f",
            "dshow",
            "-rtbufsize",
            "50M",
            "-framerate",
            "15",
            "-video_size",
            "640x480",
            "-i",
            f"video={device}",
        ]
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        *prefix,
        "-an",
        "-c:v",
        "mjpeg",
        "-q:v",
        "8",
        "-f",
        "image2pipe",
        "pipe:1",
    ]


def _read_frames(process: subprocess.Popen[bytes], hub: FrameHub) -> None:
    assert process.stdout is not None
    buffer = b""
    while True:
        chunk = process.stdout.read(65536)
        if not chunk:
            break
        buffer += chunk
        while True:
            start = buffer.find(SOI)
            if start < 0:
                buffer = b""
                break
            end = buffer.find(EOI, start + 2)
            if end < 0:
                buffer = buffer[start:]
                break
            hub.publish(buffer[start : end + 2])
            buffer = buffer[end + 2 :]
    code = process.wait()
    logging.error("Camera capture stopped (ffmpeg exit %s)", code)


def _make_handler(hub: FrameHub) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: object) -> None:
            logging.debug("%s - %s", self.address_string(), fmt % args)

        def _is_live(self) -> bool:
            return self.path.split("?", 1)[0] == "/live.mjpg"

        def do_HEAD(self) -> None:  # noqa: N802
            if not self._is_live():
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "multipart/x-mixed-replace; boundary=frame",
            )
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            if not self._is_live():
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "multipart/x-mixed-replace; boundary=frame",
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            last_seq = 0
            try:
                while True:
                    item = hub.wait_next(last_seq, timeout=5)
                    if item is None:
                        continue
                    last_seq, frame = item
                    self.wfile.write(b"--" + BOUNDARY + b"\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode())
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Serve a looping video file, or the webcam, as MJPEG.",
    )
    parser.add_argument("--source", help="MP4 to play in real time and repeat")
    parser.add_argument("--device", help="Webcam name, used only when --source is omitted")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    if not args.source and not args.device:
        logging.error("Pass --source PATH for a simulated camera, or --device NAME for a webcam.")
        return 2

    hub = FrameHub()
    try:
        process = subprocess.Popen(
            _ffmpeg_command(args.ffmpeg, source=args.source, device=args.device),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        logging.error("FFmpeg not found (%r).", args.ffmpeg)
        return 127

    threading.Thread(target=_read_frames, args=(process, hub), daemon=True).start()
    if process.stderr is not None:
        threading.Thread(
            target=_log_stderr,
            args=(process.stderr,),
            daemon=True,
        ).start()

    server = ThreadingHTTPServer((args.host, args.port), _make_handler(hub))
    origin = args.source if args.source else f"webcam {args.device}"
    logging.info(
        "Live camera at http://%s:%s/live.mjpg from %s. Ctrl+C to stop.",
        args.host,
        args.port,
        origin,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Stopping live camera")
    finally:
        server.server_close()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    return 0


def _log_stderr(stream: object) -> None:
    for raw in stream:  # type: ignore[union-attr]
        line = raw.decode("utf-8", errors="replace").strip()
        if line:
            logging.warning("ffmpeg: %s", line)


if __name__ == "__main__":
    raise SystemExit(main())
