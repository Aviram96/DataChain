from datetime import datetime, timezone

import pytest

from app.services.segment_timeline import (
    SegmentTimelineEntry,
    SegmentTimelineNotReady,
    calculate_segment_media_range,
    find_segment_timeline,
    mark_segment_run_closed,
    read_segment_timeline,
    resolve_segment_utc_window,
)

CAMERA_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_read_valid_segment_timeline(tmp_path):
    csv_path = tmp_path / "segments.csv"
    csv_path.write_text("camera_20261112T182510Z.mp4,0.000000,25.120000\n")

    entries = read_segment_timeline(csv_path)

    assert len(entries) == 1
    assert entries[0].filename == "camera_20261112T182510Z.mp4"
    assert entries[0].media_start == 0.0
    assert entries[0].media_end == 25.12


@pytest.mark.parametrize(
    "content",
    [
        "segment.mp4,0\n",
        "segment.mp4,10,5\n",
        "segment.mp4,-1,10\n",
        "segment.mp4,nan,10\n",
        "segment.mp4,0,inf\n",
        "../segment.mp4,0,10\n",
        "segment.txt,0,10\n",
    ],
)
def test_reject_invalid_segment_timeline(tmp_path, content):
    csv_path = tmp_path / "segments.csv"
    csv_path.write_text(content)

    with pytest.raises(ValueError):
        read_segment_timeline(csv_path)


def test_find_segment_across_csv_files(tmp_path):
    (tmp_path / "segments_run1.csv").write_text("first.mp4,0.0,60.0\n")
    (tmp_path / "segments_run2.csv").write_text("second.mp4,0.0,60.0\n")

    result = find_segment_timeline(tmp_path, "second.mp4")

    assert result is not None
    assert result.filename == "second.mp4"
    assert result.media_start == 0.0
    assert result.media_end == 60.0


def test_find_missing_segment_returns_none(tmp_path):
    (tmp_path / "segments_run1.csv").write_text("first.mp4,0.0,60.0\n")

    result = find_segment_timeline(tmp_path, "missing.mp4")

    assert result is None


def test_duplicate_segment_entries_raise_error(tmp_path):
    (tmp_path / "segments_run1.csv").write_text("first.mp4,0.0,60.0\n")
    (tmp_path / "segments_run2.csv").write_text("first.mp4,0.0,60.0\n")

    with pytest.raises(ValueError, match="Duplicate timeline entries"):
        find_segment_timeline(tmp_path, "first.mp4")


def test_active_run_ignores_partial_trailing_row(tmp_path):
    csv_path = tmp_path / "segments_run.csv"
    csv_path.write_bytes(b"first.mp4,0.000000,8.080000\n" b"second.mp4,8.080000,13.080")

    entries = read_segment_timeline(csv_path, run_closed=False)

    assert len(entries) == 1
    assert entries[0].filename == "first.mp4"
    assert entries[0].media_end == pytest.approx(8.08)


def test_closed_run_rejects_partial_trailing_row(tmp_path):
    csv_path = tmp_path / "segments_run.csv"
    csv_path.write_bytes(b"first.mp4,0.000000,8.080000\n" b"second.mp4,8.080000,13.080")
    mark_segment_run_closed(csv_path)

    with pytest.raises(ValueError, match="incomplete row"):
        read_segment_timeline(csv_path, run_closed=True)
    with pytest.raises(ValueError, match="incomplete row"):
        find_segment_timeline(tmp_path, "first.mp4")


def test_calculate_continuous_media_ranges():
    first = SegmentTimelineEntry("first.mp4", 0.0, 17.44)
    second = SegmentTimelineEntry("second.mp4", 17.44, 27.44)

    first_start, first_end = calculate_segment_media_range(
        first,
        file_start_time=7.44,
        file_duration=10.0,
        first_segment=True,
    )

    second_start, second_end = calculate_segment_media_range(
        second,
        file_start_time=0.0,
        file_duration=10.0,
        first_segment=False,
    )

    assert first_start == pytest.approx(7.44)
    assert first_end == pytest.approx(17.44)
    assert second_start == pytest.approx(first_end)
    assert second_end == pytest.approx(27.44)


@pytest.mark.parametrize(
    "file_start_time,file_duration,first_segment",
    [
        (0.0, 12.0, False),
        (0.0, 12.0, True),
    ],
)
def test_reject_media_range_exceeding_csv(
    file_start_time, file_duration, first_segment
):
    entry = SegmentTimelineEntry(
        filename="segment.mp4",
        media_start=10.0,
        media_end=20.0,
    )

    with pytest.raises(ValueError):
        calculate_segment_media_range(
            entry,
            file_start_time=file_start_time,
            file_duration=file_duration,
            first_segment=first_segment,
        )


def _segment_name(stamp: str) -> str:
    return f"{CAMERA_ID}_{stamp}.mp4"


def test_second_segment_reference_keeps_ranges_contiguous(tmp_path):
    first = _segment_name("20261115T120000Z")
    second = _segment_name("20261115T120008Z")
    csv_path = tmp_path / "segments_run.csv"
    csv_path.write_text(f"{first},0.000000,8.080000\n" f"{second},8.080000,13.080000\n")

    first_window = resolve_segment_utc_window(
        tmp_path,
        first,
        file_start_time=3.08,
        file_duration=5.0,
    )
    second_window = resolve_segment_utc_window(
        tmp_path,
        second,
        file_start_time=0.0,
        file_duration=5.0,
    )

    assert first_window.reference_kind == "second_segment"
    assert second_window.reference_kind == "second_segment"
    assert first_window.reference_utc == datetime(
        2026, 11, 15, 12, 0, 8, tzinfo=timezone.utc
    )
    assert first_window.reference_media_time == pytest.approx(8.08)
    assert first_window.ended_at == second_window.started_at
    offset = (first_window.started_at - first_window.reference_utc).total_seconds()
    assert offset == pytest.approx(3.08 - 8.08)
    span = (second_window.ended_at - second_window.started_at).total_seconds()
    assert span == pytest.approx(5)


def test_active_single_row_is_not_ready(tmp_path):
    filename = _segment_name("20261115T120000Z")
    csv_path = tmp_path / "segments_run.csv"
    csv_path.write_text(f"{filename},0.000000,8.080000\n")

    with pytest.raises(SegmentTimelineNotReady):
        resolve_segment_utc_window(
            tmp_path,
            filename,
            file_start_time=3.08,
            file_duration=5.0,
        )


def test_closed_single_segment_uses_open_time_and_start_time(tmp_path):
    filename = _segment_name("20261115T120000Z")
    csv_path = tmp_path / "segments_run.csv"
    csv_path.write_text(f"{filename},0.000000,8.080000\n")
    mark_segment_run_closed(csv_path)

    window = resolve_segment_utc_window(
        tmp_path,
        filename,
        file_start_time=3.08,
        file_duration=5.0,
    )

    assert window.reference_kind == "single_segment"
    assert window.reference_media_time == pytest.approx(3.08)
    assert window.started_at == datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)
    span = (window.ended_at - window.started_at).total_seconds()
    assert span == pytest.approx(5)


def test_separate_runs_keep_separate_references(tmp_path):
    first_run_a = _segment_name("20261115T120000Z")
    second_run_a = _segment_name("20261115T120008Z")
    only_run_b = _segment_name("20261115T130000Z")
    run_a = tmp_path / "segments_a.csv"
    run_b = tmp_path / "segments_b.csv"
    run_a.write_text(
        f"{first_run_a},0.000000,8.080000\n" f"{second_run_a},8.080000,13.080000\n"
    )
    run_b.write_text(f"{only_run_b},0.000000,4.000000\n")
    mark_segment_run_closed(run_b)

    from_a = resolve_segment_utc_window(
        tmp_path,
        first_run_a,
        file_start_time=3.08,
        file_duration=5.0,
    )
    from_b = resolve_segment_utc_window(
        tmp_path,
        only_run_b,
        file_start_time=1.0,
        file_duration=3.0,
    )

    assert from_a.reference_kind == "second_segment"
    assert from_a.reference_utc == datetime(2026, 11, 15, 12, 0, 8, tzinfo=timezone.utc)
    assert from_b.reference_kind == "single_segment"
    assert from_b.started_at == datetime(2026, 11, 15, 13, 0, 0, tzinfo=timezone.utc)


def test_duplicate_filename_is_refused_by_resolver(tmp_path):
    filename = _segment_name("20261115T120000Z")
    (tmp_path / "segments_run1.csv").write_text(f"{filename},0.000000,8.080000\n")
    (tmp_path / "segments_run2.csv").write_text(f"{filename},0.000000,8.080000\n")
    mark_segment_run_closed(tmp_path / "segments_run1.csv")
    mark_segment_run_closed(tmp_path / "segments_run2.csv")

    with pytest.raises(ValueError, match="Duplicate timeline entries"):
        resolve_segment_utc_window(
            tmp_path,
            filename,
            file_start_time=0.0,
            file_duration=8.08,
        )


def test_missing_segment_in_closed_runs_is_an_error(tmp_path):
    filename = _segment_name("20261115T120000Z")
    csv_path = tmp_path / "segments_run.csv"
    csv_path.write_text(f"{filename},0.000000,8.080000\n")
    mark_segment_run_closed(csv_path)

    with pytest.raises(ValueError, match="not in a closed timeline"):
        resolve_segment_utc_window(
            tmp_path,
            _segment_name("20261115T120008Z"),
            file_start_time=0.0,
            file_duration=5.0,
        )
