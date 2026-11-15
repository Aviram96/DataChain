
import pytest

from app.services.segment_timeline import (
    SegmentTimelineEntry,
    calculate_segment_media_range,
    find_segment_timeline,
    read_segment_timeline,
)
def test_read_valid_segment_timeline(tmp_path):
    csv_path = tmp_path / "segments.csv"
    csv_path.write_text(
        "camera_20261112T182510Z.mp4,0.000000,25.120000\n"
    )

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
    (tmp_path / "segments_run1.csv").write_text(
        "first.mp4,0.0,60.0\n"
    )
    (tmp_path / "segments_run2.csv").write_text(
        "second.mp4,0.0,60.0\n"
    )

    result = find_segment_timeline(tmp_path, "second.mp4")

    assert result is not None
    assert result.filename == "second.mp4"
    assert result.media_start == 0.0
    assert result.media_end == 60.0


def test_find_missing_segment_returns_none(tmp_path):
    (tmp_path / "segments_run1.csv").write_text(
        "first.mp4,0.0,60.0\n"
    )

    result = find_segment_timeline(tmp_path, "missing.mp4")

    assert result is None


def test_duplicate_segment_entries_raise_error(tmp_path):
    (tmp_path / "segments_run1.csv").write_text(
        "first.mp4,0.0,60.0\n"
    )
    (tmp_path / "segments_run2.csv").write_text(
        "first.mp4,0.0,60.0\n"
    )

    with pytest.raises(ValueError, match="Duplicate timeline entries"):
        find_segment_timeline(tmp_path, "first.mp4")


def test_reject_incomplete_csv_row(tmp_path):
    csv_path = tmp_path / "segments.csv"

    csv_path.write_bytes(
        b"segment.mp4,0.000000,60.000000"
    )

    with pytest.raises(ValueError, match="incomplete row"):
        read_segment_timeline(csv_path)

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