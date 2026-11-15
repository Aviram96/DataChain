"""Run FFmpeg subprocesses with optional restart after unexpected exit."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

ENV_RESTART_DELAY_SECONDS = "CCTV_FFMPEG_RESTART_DELAY_SECONDS"
ENV_MAX_RESTARTS = "CCTV_FFMPEG_MAX_RESTARTS"
DEFAULT_RESTART_DELAY_SECONDS = 2.0

CommandBuilder = Callable[[], list[str]]


@dataclass(frozen=True)
class FFmpegRunConfig:
    """Settings for supervised FFmpeg execution."""

    build_command: CommandBuilder
    restart_on_crash: bool = False
    restart_delay_seconds: float = DEFAULT_RESTART_DELAY_SECONDS
    max_restarts: int | None = None
    log_label: str | None = None
    popen_kwargs: dict[str, Any] = field(default_factory=dict)
    graceful_stop: bool = False


def resolve_restart_delay_seconds() -> float:
    raw = os.getenv(ENV_RESTART_DELAY_SECONDS, "").strip()
    if not raw:
        return DEFAULT_RESTART_DELAY_SECONDS
    try:
        return max(0.5, min(60.0, float(raw)))
    except ValueError:
        return DEFAULT_RESTART_DELAY_SECONDS


def resolve_max_restarts() -> int | None:
    raw = os.getenv(ENV_MAX_RESTARTS, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return max(1, value) if value > 0 else None


class FFmpegSupervisor:
    """Start FFmpeg, restart after crash when enabled, stop cleanly on signal."""

    def __init__(self, config: FFmpegRunConfig) -> None:
        self._config = config
        self._process: subprocess.Popen[bytes] | None = None
        self._stopped = False
        self._restart_count = 0
        self._gave_up_after_restarts = False

    @property
    def restart_count(self) -> int:
        return self._restart_count

    @property
    def gave_up_after_restarts(self) -> bool:
        """True when FFmpeg kept crashing and the restart cap was reached."""
        return self._gave_up_after_restarts

    def _label(self) -> str:
        if self._config.log_label:
            return f" [{self._config.log_label}]"
        return ""

    def stop(self) -> None:
        if self._stopped:
            return

        self._stopped = True
        proc = self._process

        if proc is None or proc.poll() is not None:
            return

        if self._config.graceful_stop and proc.stdin is not None:
            try:
                proc.stdin.write(b"q\n")
                proc.stdin.flush()
                proc.wait(timeout=5)
                return
            except (OSError, ValueError, subprocess.TimeoutExpired):
                logger.warning("Graceful FFmpeg stop failed; using fallback")

        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


    def run_until_signal(self) -> int:
        """Run until stopped by signal or non-restartable FFmpeg exit."""
        previous_handlers: dict[int, Any] = {}

        def _handle_signal(signum: int, _frame: object | None) -> None:
            logger.info("Received signal %s; stopping FFmpeg supervisor", signum)
            self._stopped = True

            proc = self._process
            if proc is None or proc.poll() is not None:
                return

            if self._config.graceful_stop and proc.stdin is not None:
                try:
                    proc.stdin.write(b"q\n")
                    proc.stdin.flush()
                    return
                except (OSError, ValueError):
                    logger.warning("Could not send q to FFmpeg; terminating")

            proc.terminate()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                previous_handlers[sig] = signal.signal(sig, _handle_signal)
            except (ValueError, OSError):
                pass

        last_code = 0
        try:
            while not self._stopped:
                cmd = self._config.build_command()
                popen_kwargs = dict(self._config.popen_kwargs)

                if self._config.graceful_stop:
                    popen_kwargs["stdin"] = subprocess.PIPE

                self._process = subprocess.Popen(
                    cmd,
                    stderr=subprocess.PIPE,
                    **popen_kwargs,
                )

                stderr_thread = threading.Thread(
                    target=self._log_stderr,
                    args=(self._process,),
                    daemon=True,
                )
                stderr_thread.start()

                stop_requested_at = None

                while True:
                    try:
                        last_code = self._process.wait(timeout=0.5)
                        break
                    except subprocess.TimeoutExpired:
                        if not self._stopped:
                            continue

                        if stop_requested_at is None:
                            stop_requested_at = time.monotonic()

                        if time.monotonic() - stop_requested_at >= 5:
                            logger.warning(
                                "FFmpeg did not stop gracefully; terminating process"
                            )
                            self._process.terminate()

                            try:
                                last_code = self._process.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                logger.error(
                                    "FFmpeg did not terminate; killing process"
                                )
                                self._process.kill()
                                last_code = self._process.wait(timeout=5)

                            break

                stderr_thread.join(timeout=5)

                if self._stopped:
                    break
                if not self._config.restart_on_crash or last_code == 0:
                    break

                if (
                    self._config.max_restarts is not None
                    and self._restart_count >= self._config.max_restarts
                ):
                    self._gave_up_after_restarts = True
                    logger.error(
                        "FFmpeg crashed with code %s; max restarts (%s) exceeded%s",
                        last_code,
                        self._config.max_restarts,
                        self._label(),
                    )
                    break

                self._restart_count += 1
                logger.warning(
                    "FFmpeg crashed with code %s; restarting in %ss (attempt %s)%s",
                    last_code,
                    self._config.restart_delay_seconds,
                    self._restart_count,
                    self._label(),
                )
                time.sleep(self._config.restart_delay_seconds)
            return last_code
        finally:
            self.stop()
            for sig, handler in previous_handlers.items():
                try:
                    signal.signal(sig, handler)
                except (ValueError, OSError):
                    pass

    @staticmethod
    def _log_stderr(proc: subprocess.Popen[bytes]) -> None:
        if proc.stderr is None:
            return

        for raw_line in proc.stderr:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line:
                logger.warning("FFmpeg stderr: %s", line)
