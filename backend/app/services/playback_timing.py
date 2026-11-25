"""Diagnostic clocks for one verified playback request.

Logs durations and byte counts. It does not record tokens, keys, URLs, or file paths.
"""

from __future__ import annotations

import re
import time
from contextvars import ContextVar, Token
from uuid import uuid4

import logging

logger = logging.getLogger("uvicorn.error")

_current: ContextVar["PlaybackTiming | None"] = ContextVar(
    "playback_timing",
    default=None,
)
_SAFE = re.compile(r"[A-Za-z0-9_.:-]{1,80}")


class PlaybackTiming:
    """Elapsed time from the start of one playback request."""

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self.started = time.perf_counter()

    def step(self, event: str, started_at: float, **fields: object) -> None:
        now = time.perf_counter()
        parts = [
            f"playback-timing id={self.request_id}",
            f"event={event}",
            f"elapsed_ms={_ms(now - self.started)}",
            f"step_ms={_ms(now - started_at)}",
        ]
        for key, value in fields.items():
            safe = _safe(value)
            if safe is not None:
                parts.append(f"{_safe(key) or 'field'}={safe}")
        logger.info(" ".join(parts))


def playback_timing_id(raw: str | None) -> str:
    if raw and _SAFE.fullmatch(raw):
        return raw
    return uuid4().hex


def start_playback_timing(request_id: str) -> Token["PlaybackTiming | None"]:
    return _current.set(PlaybackTiming(request_id))


def finish_playback_timing(
    token: Token["PlaybackTiming | None"],
    *,
    outcome: str,
) -> None:
    timing = _current.get()
    if timing is not None:
        timing.step("response_ready", timing.started, outcome=outcome)
    _current.reset(token)


def log_playback_step(event: str, started_at: float, **fields: object) -> None:
    timing = _current.get()
    if timing is None:
        return
    timing.step(event, started_at, **fields)


def _ms(seconds: float) -> str:
    return f"{seconds * 1000:.3f}"


def _safe(value: object) -> str | None:
    text = str(value)
    if _SAFE.fullmatch(text):
        return text
    return None
