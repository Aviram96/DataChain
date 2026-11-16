"""Combine recordings download helpers (Slice E / CP-E.P10)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

from app.services.recording_download import (
    RecordingDownloadError,
    assemble_range_download,
    assemble_verified_files,
    build_concat_copy_command,
    download_filename,
    ipfs_gateway_url,
    write_concat_list,
)


def test_ipfs_gateway_url_strips_slash() -> None:
    assert (
        ipfs_gateway_url("bafy123", gateway="https://gateway.pinata.cloud/")
        == "https://gateway.pinata.cloud/ipfs/bafy123"
    )


def test_download_filename_uses_utc_stamps() -> None:
    started = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    ended = datetime(2026, 8, 24, 12, 5, tzinfo=timezone.utc)
    assert download_filename(started, ended) == (
        "recordings_20260824T120000Z_20260824T120500Z.mp4"
    )


def test_write_concat_list(tmp_path: Path) -> None:
    list_path = tmp_path / "concat.txt"
    write_concat_list(["0000.mp4", "0001.mp4"], list_path)
    assert list_path.read_text(encoding="utf-8") == "file '0000.mp4'\nfile '0001.mp4'\n"


def test_build_concat_copy_command() -> None:
    cmd = build_concat_copy_command("ffmpeg", "concat.txt", "combined.mp4")
    assert cmd[0] == "ffmpeg"
    assert "-f" in cmd and "concat" in cmd
    assert "-c" in cmd and "copy" in cmd


def test_assemble_range_download_fetches_and_concats(tmp_path: Path) -> None:
    fetched: list[str] = []

    def fetch_one(cid: str, dest: Path) -> None:
        fetched.append(cid)
        dest.write_bytes(b"seg")

    def concat(paths: list[Path], output: Path) -> None:
        assert [path.name for path in paths] == ["0000.mp4", "0001.mp4"]
        output.write_bytes(b"joined")

    output = assemble_range_download(
        ["cid-a", "cid-b"],
        tmp_path / "work",
        fetch_one=fetch_one,
        concat=concat,
    )
    assert fetched == ["cid-a", "cid-b"]
    assert output.read_bytes() == b"joined"


def test_assemble_verified_files_returns_the_only_segment(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    only = work / "one.mp4"
    only.write_bytes(b"only-verified")

    def fail_concat(_paths: list[Path], _output: Path) -> None:
        raise AssertionError("a single verified file is not concatenated")

    output = assemble_verified_files([only], work, concat=fail_concat)
    assert output == only
    assert output.read_bytes() == b"only-verified"


def test_assemble_verified_files_concats_only_given_paths(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    first = work / "first.mp4"
    second = work / "second.mp4"
    rejected = work / "rejected.mp4"
    first.write_bytes(b"yes-a")
    second.write_bytes(b"yes-b")
    rejected.write_bytes(b"no")
    seen: list[list[bytes]] = []

    def concat(paths: list[Path], output: Path) -> None:
        seen.append([path.read_bytes() for path in paths])
        output.write_bytes(b"joined")

    output = assemble_verified_files([first, second], work, concat=concat)
    assert seen == [[b"yes-a", b"yes-b"]]
    assert output.read_bytes() == b"joined"
    assert rejected.read_bytes() == b"no"


def test_assemble_verified_files_rejects_empty_or_outside(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(RecordingDownloadError) as empty:
        assemble_verified_files([], work)
    assert empty.value.status_code == 404

    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"escape")
    with pytest.raises(RecordingDownloadError) as escaped:
        assemble_verified_files([outside], work)
    assert escaped.value.status_code == 502


def test_assemble_rejects_oversized_range(tmp_path: Path) -> None:
    with pytest.raises(RecordingDownloadError) as exc:
        assemble_range_download(["x"] * 1441, tmp_path)
    assert exc.value.status_code == 400


def test_fetch_cid_to_file_maps_http_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import recording_download as module

    class FakeResponse:
        status_code = 502

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def iter_content(self, _size: int):
            return iter(())

    monkeypatch.setattr(
        module.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(),
    )
    with pytest.raises(RecordingDownloadError) as exc:
        module.fetch_cid_to_file("bafy", tmp_path / "seg.mp4")
    assert exc.value.status_code == 502


def test_fetch_cid_to_file_maps_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import recording_download as module

    def boom(*args: object, **kwargs: object):
        raise requests.Timeout("slow")

    monkeypatch.setattr(module.requests, "get", boom)
    with pytest.raises(RecordingDownloadError) as exc:
        module.fetch_cid_to_file("bafy", tmp_path / "seg.mp4")
    assert exc.value.status_code == 502
