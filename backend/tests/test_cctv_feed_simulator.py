"""Tests for CCTV feed simulator (no real FFmpeg required)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.cctv_feed_simulator import (
    CctvFeedConfig,
    CctvFeedError,
    build_ffmpeg_loop_command,
    resolve_source_path,
    validate_source_mp4,
)


def test_build_ffmpeg_loop_command() -> None:
    config = CctvFeedConfig(source_path=Path("/tmp/cam.mp4"))
    cmd = build_ffmpeg_loop_command(config)
    assert cmd[0] == "ffmpeg"
    assert "-stream_loop" in cmd
    assert cmd[cmd.index("-stream_loop") + 1] == "-1"
    assert str(config.source_path) in cmd
    assert cmd[-3:] == ["-f", "mpegts", "pipe:1"]


def test_validate_source_mp4_rejects_missing(tmp_path: Path) -> None:
    missing = tmp_path / "nope.mp4"
    with pytest.raises(CctvFeedError, match="not found"):
        validate_source_mp4(missing)


def test_validate_source_mp4_rejects_wrong_suffix(tmp_path: Path) -> None:
    wrong = tmp_path / "clip.mkv"
    wrong.write_bytes(b"x")
    with pytest.raises(CctvFeedError, match="must be a .mp4"):
        validate_source_mp4(wrong)


def test_validate_source_mp4_accepts_file(tmp_path: Path) -> None:
    ok = tmp_path / "clip.mp4"
    ok.write_bytes(b"\x00")
    validate_source_mp4(ok)


def test_resolve_source_path_cli_over_env(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / "from_env.mp4"
    env_file.write_bytes(b"\x00")
    cli_file = tmp_path / "from_cli.mp4"
    cli_file.write_bytes(b"\x00")
    monkeypatch.setenv("CCTV_SOURCE_MP4", str(env_file))
    resolved = resolve_source_path(str(cli_file))
    assert resolved == cli_file.resolve()


def test_resolve_source_path_from_env(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / "from_env.mp4"
    env_file.write_bytes(b"\x00")
    monkeypatch.setenv("CCTV_SOURCE_MP4", str(env_file))
    assert resolve_source_path(None) == env_file.resolve()


def test_resolve_source_path_requires_config(monkeypatch) -> None:
    monkeypatch.delenv("CCTV_SOURCE_MP4", raising=False)
    with pytest.raises(CctvFeedError, match="No source MP4"):
        resolve_source_path(None)
