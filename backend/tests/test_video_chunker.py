"""Tests for video chunker (no real FFmpeg required)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.video_chunker import (
    VideoChunkerConfig,
    VideoChunkerError,
    build_ffmpeg_chunk_command,
    ensure_temp_dir,
    ffmpeg_input,
    list_chunk_files,
    resolve_chunk_duration_seconds,
    resolve_temp_dir,
    segment_output_path,
)


def test_resolve_temp_dir_default() -> None:
    path = resolve_temp_dir(None)
    assert path.name == "temp"
    assert path.parent.name == "backend"


def test_resolve_temp_dir_cli_over_env(tmp_path: Path, monkeypatch) -> None:
    env_dir = tmp_path / "from_env"
    cli_dir = tmp_path / "from_cli"
    monkeypatch.setenv("CCTV_TEMP_DIR", str(env_dir))
    assert resolve_temp_dir(str(cli_dir)) == cli_dir.resolve()


def test_resolve_chunk_duration_defaults(monkeypatch) -> None:
    monkeypatch.delenv("CCTV_CHUNK_DURATION_SECONDS", raising=False)
    assert resolve_chunk_duration_seconds(None) == 60
    assert resolve_chunk_duration_seconds(90) == 90


def test_resolve_chunk_duration_rejects_invalid() -> None:
    with pytest.raises(VideoChunkerError, match="at least 1"):
        resolve_chunk_duration_seconds(0)


def test_build_ffmpeg_chunk_command_one_pass(tmp_path: Path) -> None:
    source = tmp_path / "cam.mp4"
    source.write_bytes(b"\x00")
    config = VideoChunkerConfig(
        source_path=source,
        temp_dir=tmp_path / "temp",
        segment_duration_seconds=60,
        loop_source=False,
    )
    cmd = build_ffmpeg_chunk_command(config)
    assert cmd[0] == "ffmpeg"
    assert "-stream_loop" not in cmd
    assert "-f" in cmd
    assert cmd[cmd.index("-f") + 1] == "segment"
    assert cmd[cmd.index("-segment_time") + 1] == "60"
    assert str(segment_output_path(config)) in cmd


def test_build_ffmpeg_chunk_command_loop(tmp_path: Path) -> None:
    source = tmp_path / "cam.mp4"
    source.write_bytes(b"\x00")
    config = VideoChunkerConfig(
        source_path=source,
        temp_dir=tmp_path / "temp",
        loop_source=True,
    )
    cmd = build_ffmpeg_chunk_command(config)
    assert "-re" in cmd
    assert "-stream_loop" in cmd
    assert cmd[cmd.index("-stream_loop") + 1] == "-1"


def test_build_ffmpeg_chunk_command_live_url(tmp_path: Path) -> None:
    config = VideoChunkerConfig(
        source_path=tmp_path / "unused.mp4",
        temp_dir=tmp_path / "temp",
        input_uri="rtsp://192.0.2.50/live",
        extra_input_args=("-rtsp_transport", "tcp"),
        restart_on_crash=True,
    )
    cmd = build_ffmpeg_chunk_command(config)
    assert ffmpeg_input(config) == "rtsp://192.0.2.50/live"
    assert cmd[cmd.index("-i") + 1] == "rtsp://192.0.2.50/live"
    assert "-rtsp_transport" in cmd
    assert "-stream_loop" not in cmd
    assert cmd[cmd.index("-segment_time") + 1] == "60"
    assert cmd[cmd.index("-c") + 1] == "copy"


def test_build_ffmpeg_chunk_command_encodes_mjpeg(tmp_path: Path) -> None:
    config = VideoChunkerConfig(
        source_path=tmp_path / "unused.mp4",
        temp_dir=tmp_path / "temp",
        input_uri="http://127.0.0.1:8090/live.mjpg",
    )
    cmd = build_ffmpeg_chunk_command(config)
    assert "-c" not in cmd or cmd[cmd.index("-c") + 1] != "copy"
    assert cmd[cmd.index("-c:v") + 1] == "libx264"


def test_build_ffmpeg_chunk_command_strftime(tmp_path: Path) -> None:
    pattern = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee_%Y%m%dT%H%M%SZ.mp4"
    config = VideoChunkerConfig(
        source_path=tmp_path / "cam.mp4",
        temp_dir=tmp_path / "temp",
        segment_pattern=pattern,
        strftime_output=True,
    )
    cmd = build_ffmpeg_chunk_command(config)
    assert "-strftime" in cmd
    assert cmd[cmd.index("-strftime") + 1] == "1"
    assert str(segment_output_path(config)).endswith(pattern)


def test_ensure_temp_dir_creates(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "temp"
    assert not target.exists()
    ensure_temp_dir(target)
    assert target.is_dir()


def test_list_chunk_files_sorted(tmp_path: Path) -> None:
    (tmp_path / "chunk_002.mp4").write_bytes(b"\x00")
    (tmp_path / "chunk_001.mp4").write_bytes(b"\x00")
    (tmp_path / "other.txt").write_bytes(b"\x00")
    names = [path.name for path in list_chunk_files(tmp_path)]
    assert names == ["chunk_001.mp4", "chunk_002.mp4"]
