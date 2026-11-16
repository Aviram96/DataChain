"""Shared recording verification: chain metadata plus IPFS SHA-256."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.video_record import VideoRecord
from app.services.chain_anchor import ChainAnchorError, SegmentAnchor
from app.services.recording_download import RecordingDownloadError
from app.services.recording_verification import (
    RecordingVerificationError,
    verify_recording_range,
)
from app.services.segment_integrity import sha256_file

import app.models as _models  # noqa: F401

CAMERA_ID = UUID("01234567-89ab-cdef-0123-456789abcdef")
OTHER_CAMERA_ID = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
CID = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
OTHER_CID = "bafybeigothercid0000000000000000000000000000000000000000000"
FILE_BYTES = b"verified-segment-bytes"
OTHER_BYTES = b"tampered-segment-bytes"
FILE_HASH = hashlib.sha256(FILE_BYTES).hexdigest()
OTHER_HASH = hashlib.sha256(OTHER_BYTES).hexdigest()


@pytest.fixture
def db_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _add_record(
    db: Session,
    started_at: datetime,
    ended_at: datetime,
    *,
    camera_id: UUID = CAMERA_ID,
    cid: str = CID,
    segment_hash: str = FILE_HASH,
) -> VideoRecord:
    record = VideoRecord(
        id=uuid4(),
        camera_id=camera_id,
        started_at=started_at,
        ended_at=ended_at,
        ipfs_cid=cid,
        segment_hash=segment_hash,
        tx_hash="0x" + "ab" * 32,
        created_at=datetime.now(timezone.utc),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _anchor_for(
    record: VideoRecord,
    *,
    camera_id: UUID | None = None,
    cid: str | None = None,
    segment_hash: str | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
) -> SegmentAnchor:
    return SegmentAnchor(
        camera_id=record.camera_id if camera_id is None else camera_id,
        started_at=record.started_at if started_at is None else started_at,
        ended_at=record.ended_at if ended_at is None else ended_at,
        cid=record.ipfs_cid if cid is None else cid,
        segment_hash=record.segment_hash if segment_hash is None else segment_hash,
    )


def _fetch_bytes(payload: bytes):
    def fetch(_cid: str, dest: Path) -> None:
        dest.write_bytes(payload)

    return fetch


def _utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _reader_for(record: VideoRecord, outcome: SegmentAnchor | Exception):
    def read(camera_id: UUID, started_at: datetime) -> SegmentAnchor:
        assert camera_id == record.camera_id
        assert _utc(started_at) == _utc(record.started_at)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return read


def test_verified_segment_matches_chain_and_file_hash(
    db_session: Session, tmp_path: Path
) -> None:
    started = datetime(2026, 8, 24, 12, 0, 7, tzinfo=timezone.utc)
    ended = started + timedelta(seconds=47)
    record = _add_record(db_session, started, ended)
    fetched: list[str] = []

    def fetch(cid: str, dest: Path) -> None:
        fetched.append(cid)
        dest.write_bytes(FILE_BYTES)

    report = verify_recording_range(
        db_session,
        CAMERA_ID,
        started,
        ended,
        work_dir=tmp_path,
        read_anchor=_reader_for(record, _anchor_for(record)),
        fetch_file=fetch,
        hash_file=sha256_file,
    )

    assert report.overall == "verified"
    assert report.missing_intervals == ()
    assert report.excluded_intervals == ()
    assert len(report.segments) == 1
    assert report.segments[0].status == "verified"
    assert "match the blockchain anchor" in report.segments[0].detail
    assert len(report.eligible) == 1
    assert report.eligible[0].video_record_id == record.id
    assert report.eligible[0].path.read_bytes() == FILE_BYTES
    assert sha256_file(report.eligible[0].path) == FILE_HASH
    assert fetched == [CID]


def test_metadata_mismatch_is_tampered_and_skips_ipfs(
    db_session: Session, tmp_path: Path
) -> None:
    started = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    record = _add_record(db_session, started, started + timedelta(seconds=60))
    fetched: list[str] = []

    report = verify_recording_range(
        db_session,
        CAMERA_ID,
        started,
        record.ended_at,
        work_dir=tmp_path,
        read_anchor=_reader_for(record, _anchor_for(record, cid=OTHER_CID)),
        fetch_file=lambda cid, dest: fetched.append(cid),
        hash_file=sha256_file,
    )

    assert report.overall == "tampered"
    assert report.segments[0].status == "tampered"
    assert "does not match the blockchain anchor" in report.segments[0].detail
    assert report.eligible == ()
    assert fetched == []
    assert report.excluded_intervals[0].video_record_id == record.id
    assert report.excluded_intervals[0].status == "tampered"


def test_time_or_camera_mismatch_is_tampered(
    db_session: Session, tmp_path: Path
) -> None:
    started = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    ended = started + timedelta(seconds=60)
    record = _add_record(db_session, started, ended)

    shifted = verify_recording_range(
        db_session,
        CAMERA_ID,
        started,
        ended,
        work_dir=tmp_path,
        read_anchor=_reader_for(
            record,
            _anchor_for(record, ended_at=ended + timedelta(seconds=5)),
        ),
        fetch_file=_fetch_bytes(FILE_BYTES),
    )
    wrong_camera = verify_recording_range(
        db_session,
        CAMERA_ID,
        started,
        ended,
        work_dir=tmp_path,
        read_anchor=_reader_for(
            record,
            _anchor_for(record, camera_id=OTHER_CAMERA_ID),
        ),
        fetch_file=_fetch_bytes(FILE_BYTES),
    )

    assert shifted.segments[0].status == "tampered"
    assert wrong_camera.segments[0].status == "tampered"
    assert shifted.eligible == ()
    assert wrong_camera.eligible == ()


def test_file_hash_mismatch_is_tampered_and_file_is_removed(
    db_session: Session, tmp_path: Path
) -> None:
    started = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    ended = started + timedelta(seconds=60)
    record = _add_record(db_session, started, ended)

    report = verify_recording_range(
        db_session,
        CAMERA_ID,
        started,
        ended,
        work_dir=tmp_path,
        read_anchor=_reader_for(record, _anchor_for(record)),
        fetch_file=_fetch_bytes(OTHER_BYTES),
        hash_file=sha256_file,
    )

    assert report.overall == "tampered"
    assert report.segments[0].status == "tampered"
    assert "on-chain SHA-256" in report.segments[0].detail
    assert report.eligible == ()
    assert not (tmp_path / f"{record.id}.mp4").exists()


def test_missing_anchor_is_missing_not_tampered(
    db_session: Session, tmp_path: Path
) -> None:
    started = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    ended = started + timedelta(seconds=60)
    record = _add_record(db_session, started, ended)
    fetched: list[str] = []

    report = verify_recording_range(
        db_session,
        CAMERA_ID,
        started,
        ended,
        work_dir=tmp_path,
        read_anchor=_reader_for(record, ChainAnchorError("AnchorNotFound")),
        fetch_file=lambda cid, dest: fetched.append(cid),
    )

    assert report.overall == "missing"
    assert report.segments[0].status == "missing"
    assert "No blockchain anchor" in report.segments[0].detail
    assert report.missing_intervals == ()
    assert report.excluded_intervals[0].status == "missing"
    assert report.eligible == ()
    assert fetched == []


def test_wrapped_anchor_not_found_is_missing(
    db_session: Session, tmp_path: Path
) -> None:
    started = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    ended = started + timedelta(seconds=60)
    record = _add_record(db_session, started, ended)

    report = verify_recording_range(
        db_session,
        CAMERA_ID,
        started,
        ended,
        work_dir=tmp_path,
        read_anchor=_reader_for(
            record,
            ChainAnchorError("On-chain segment read failed: AnchorNotFound()"),
        ),
        fetch_file=_fetch_bytes(FILE_BYTES),
    )

    assert report.segments[0].status == "missing"
    assert report.eligible == ()


def test_ipfs_retrieval_failure_is_unavailable(
    db_session: Session, tmp_path: Path
) -> None:
    started = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    ended = started + timedelta(seconds=60)
    record = _add_record(db_session, started, ended)

    def fetch(_cid: str, _dest: Path) -> None:
        raise RecordingDownloadError("Could not retrieve a segment from IPFS.")

    report = verify_recording_range(
        db_session,
        CAMERA_ID,
        started,
        ended,
        work_dir=tmp_path,
        read_anchor=_reader_for(record, _anchor_for(record)),
        fetch_file=fetch,
        hash_file=sha256_file,
    )

    assert report.overall == "unavailable"
    assert report.segments[0].status == "unavailable"
    assert "could not be retrieved from IPFS" in report.segments[0].detail
    assert report.eligible == ()
    assert report.excluded_intervals[0].status == "unavailable"


def test_rpc_failure_is_failed_and_not_eligible(
    db_session: Session, tmp_path: Path
) -> None:
    started = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    ended = started + timedelta(seconds=60)
    record = _add_record(db_session, started, ended)
    fetched: list[str] = []

    report = verify_recording_range(
        db_session,
        CAMERA_ID,
        started,
        ended,
        work_dir=tmp_path,
        read_anchor=_reader_for(
            record, ChainAnchorError("On-chain segment read failed: timeout")
        ),
        fetch_file=lambda cid, dest: fetched.append(cid),
    )

    assert report.overall == "failed"
    assert report.segments[0].status == "failed"
    assert "could not be completed" in report.segments[0].detail
    assert report.eligible == ()
    assert fetched == []


def test_hash_error_is_failed_not_verified(db_session: Session, tmp_path: Path) -> None:
    started = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    ended = started + timedelta(seconds=60)
    record = _add_record(db_session, started, ended)

    def boom(_path: Path) -> str:
        raise OSError("disk read failed")

    report = verify_recording_range(
        db_session,
        CAMERA_ID,
        started,
        ended,
        work_dir=tmp_path,
        read_anchor=_reader_for(record, _anchor_for(record)),
        fetch_file=_fetch_bytes(FILE_BYTES),
        hash_file=boom,
    )

    assert report.overall == "failed"
    assert report.segments[0].status == "failed"
    assert report.eligible == ()
    assert not (tmp_path / f"{record.id}.mp4").exists()


def test_empty_window_is_one_missing_interval(
    db_session: Session, tmp_path: Path
) -> None:
    started = datetime(2026, 8, 24, 15, 10, 3, tzinfo=timezone.utc)
    ended = started + timedelta(minutes=5)

    report = verify_recording_range(
        db_session,
        CAMERA_ID,
        started,
        ended,
        work_dir=tmp_path,
        read_anchor=lambda *_args: pytest.fail("no chain read without a row"),
        fetch_file=lambda *_args: pytest.fail("no IPFS fetch without a row"),
    )

    assert report.overall == "missing"
    assert report.segments == ()
    assert report.eligible == ()
    assert len(report.missing_intervals) == 1
    assert report.missing_intervals[0].started_at == started
    assert report.missing_intervals[0].ended_at == ended


def test_gaps_use_stored_ranges_not_calendar_minutes(
    db_session: Session, tmp_path: Path
) -> None:
    first_start = datetime(2026, 8, 24, 12, 0, 5, 500000, tzinfo=timezone.utc)
    first_end = datetime(2026, 8, 24, 12, 0, 52, 250000, tzinfo=timezone.utc)
    second_start = datetime(2026, 8, 24, 12, 0, 55, tzinfo=timezone.utc)
    second_end = datetime(2026, 8, 24, 12, 1, 40, tzinfo=timezone.utc)
    first = _add_record(db_session, first_start, first_end)
    second = _add_record(db_session, second_start, second_end)
    anchors = {
        _utc(first.started_at): _anchor_for(first),
        _utc(second.started_at): _anchor_for(second),
    }

    def read(_camera_id: UUID, started_at: datetime) -> SegmentAnchor:
        return anchors[_utc(started_at)]

    report = verify_recording_range(
        db_session,
        CAMERA_ID,
        first_start,
        second_end,
        work_dir=tmp_path,
        read_anchor=read,
        fetch_file=_fetch_bytes(FILE_BYTES),
        hash_file=sha256_file,
    )

    assert report.overall == "missing"
    assert [segment.status for segment in report.segments] == [
        "verified",
        "verified",
    ]
    assert [item.video_record_id for item in report.eligible] == [
        first.id,
        second.id,
    ]
    assert len(report.missing_intervals) == 1
    assert report.missing_intervals[0].started_at == first_end
    assert report.missing_intervals[0].ended_at == second_start
    assert "No recording covers" in report.missing_intervals[0].detail


def test_touching_ranges_have_no_missing_interval(
    db_session: Session, tmp_path: Path
) -> None:
    first_start = datetime(2026, 8, 24, 12, 0, 5, 500000, tzinfo=timezone.utc)
    first_end = datetime(2026, 8, 24, 12, 0, 52, 250000, tzinfo=timezone.utc)
    second_end = datetime(2026, 8, 24, 12, 1, 40, tzinfo=timezone.utc)
    first = _add_record(db_session, first_start, first_end)
    second = _add_record(db_session, first_end, second_end)
    anchors = {
        _utc(first.started_at): _anchor_for(first),
        _utc(second.started_at): _anchor_for(second),
    }

    report = verify_recording_range(
        db_session,
        CAMERA_ID,
        first_start,
        second_end,
        work_dir=tmp_path,
        read_anchor=lambda _camera_id, started_at: anchors[_utc(started_at)],
        fetch_file=_fetch_bytes(FILE_BYTES),
        hash_file=sha256_file,
    )

    assert report.overall == "verified"
    assert report.missing_intervals == ()
    assert len(report.eligible) == 2


def test_partial_overlap_checks_only_overlapping_segments(
    db_session: Session, tmp_path: Path
) -> None:
    base = datetime(2026, 8, 24, 9, 0, 13, tzinfo=timezone.utc)
    spans = [
        (base, base + timedelta(seconds=40)),
        (base + timedelta(seconds=40), base + timedelta(seconds=90)),
        (base + timedelta(seconds=90), base + timedelta(seconds=130)),
    ]
    records = [_add_record(db_session, start, end) for start, end in spans]
    anchors = {_utc(record.started_at): _anchor_for(record) for record in records}
    window_start = base + timedelta(seconds=20)
    window_end = base + timedelta(seconds=90)
    fetched: list[str] = []

    def fetch(cid: str, dest: Path) -> None:
        fetched.append(cid)
        dest.write_bytes(FILE_BYTES)

    report = verify_recording_range(
        db_session,
        CAMERA_ID,
        window_start,
        window_end,
        work_dir=tmp_path,
        read_anchor=lambda _camera_id, started_at: anchors[_utc(started_at)],
        fetch_file=fetch,
        hash_file=sha256_file,
    )

    assert [segment.video_record_id for segment in report.segments] == [
        records[0].id,
        records[1].id,
    ]
    assert report.overall == "verified"
    assert report.missing_intervals == ()
    assert [item.video_record_id for item in report.eligible] == [
        records[0].id,
        records[1].id,
    ]
    assert fetched == [CID, CID]
    assert report.eligible[0].started_at == spans[0][0]
    assert report.eligible[0].ended_at == spans[0][1]


def test_partial_window_reports_interior_gap(
    db_session: Session, tmp_path: Path
) -> None:
    first_start = datetime(2026, 8, 24, 9, 0, tzinfo=timezone.utc)
    first_end = datetime(2026, 8, 24, 9, 1, tzinfo=timezone.utc)
    second_start = datetime(2026, 8, 24, 9, 2, tzinfo=timezone.utc)
    second_end = datetime(2026, 8, 24, 9, 3, tzinfo=timezone.utc)
    outside_start = datetime(2026, 8, 24, 8, 0, tzinfo=timezone.utc)
    first = _add_record(db_session, first_start, first_end)
    second = _add_record(db_session, second_start, second_end)
    outside = _add_record(
        db_session, outside_start, outside_start + timedelta(minutes=1)
    )
    anchors = {
        _utc(first.started_at): _anchor_for(first),
        _utc(second.started_at): _anchor_for(second),
        _utc(outside.started_at): _anchor_for(outside),
    }
    window_start = datetime(2026, 8, 24, 9, 0, 30, tzinfo=timezone.utc)
    window_end = datetime(2026, 8, 24, 9, 2, 30, tzinfo=timezone.utc)

    report = verify_recording_range(
        db_session,
        CAMERA_ID,
        window_start,
        window_end,
        work_dir=tmp_path,
        read_anchor=lambda _camera_id, started_at: anchors[_utc(started_at)],
        fetch_file=_fetch_bytes(FILE_BYTES),
        hash_file=sha256_file,
    )

    assert [segment.video_record_id for segment in report.segments] == [
        first.id,
        second.id,
    ]
    assert len(report.missing_intervals) == 1
    assert report.missing_intervals[0].started_at == first_end
    assert report.missing_intervals[0].ended_at == second_start
    assert report.overall == "missing"
    assert len(report.eligible) == 2


def test_multi_segment_keeps_only_verified_segments(
    db_session: Session, tmp_path: Path
) -> None:
    start = datetime(2026, 8, 24, 18, 0, 2, tzinfo=timezone.utc)
    spans = [
        (start, start + timedelta(seconds=30)),
        (start + timedelta(seconds=30), start + timedelta(seconds=70)),
        (start + timedelta(seconds=70), start + timedelta(seconds=100)),
        (start + timedelta(seconds=100), start + timedelta(seconds=140)),
    ]
    verified, tampered, unavailable, failed = [
        _add_record(db_session, began, ended) for began, ended in spans
    ]
    outcomes: dict[datetime, SegmentAnchor | Exception] = {
        _utc(verified.started_at): _anchor_for(verified),
        _utc(tampered.started_at): _anchor_for(tampered, segment_hash=OTHER_HASH),
        _utc(unavailable.started_at): _anchor_for(unavailable),
        _utc(failed.started_at): ChainAnchorError("rpc down"),
    }

    def read(_camera_id: UUID, started_at: datetime) -> SegmentAnchor:
        outcome = outcomes[_utc(started_at)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def fetch(cid: str, dest: Path) -> None:
        if cid == unavailable.ipfs_cid and dest.name.startswith(str(unavailable.id)):
            raise RecordingDownloadError("gateway down")
        dest.write_bytes(FILE_BYTES)

    report = verify_recording_range(
        db_session,
        CAMERA_ID,
        start,
        spans[-1][1],
        work_dir=tmp_path,
        read_anchor=read,
        fetch_file=fetch,
        hash_file=sha256_file,
    )

    assert [segment.status for segment in report.segments] == [
        "verified",
        "tampered",
        "unavailable",
        "failed",
    ]
    assert report.overall == "tampered"
    assert [item.video_record_id for item in report.eligible] == [verified.id]
    assert report.eligible[0].path.is_file()
    assert not (tmp_path / f"{tampered.id}.mp4").exists()
    assert not (tmp_path / f"{unavailable.id}.mp4").exists()
    excluded_ids = [item.video_record_id for item in report.excluded_intervals]
    assert excluded_ids == [tampered.id, unavailable.id, failed.id]


def test_other_camera_records_do_not_fill_gaps(
    db_session: Session, tmp_path: Path
) -> None:
    start = datetime(2026, 8, 24, 7, 0, tzinfo=timezone.utc)
    end = start + timedelta(minutes=2)
    own = _add_record(db_session, start, start + timedelta(minutes=1))
    _add_record(
        db_session,
        start + timedelta(minutes=1),
        end,
        camera_id=OTHER_CAMERA_ID,
    )

    report = verify_recording_range(
        db_session,
        CAMERA_ID,
        start,
        end,
        work_dir=tmp_path,
        read_anchor=_reader_for(own, _anchor_for(own)),
        fetch_file=_fetch_bytes(FILE_BYTES),
        hash_file=sha256_file,
    )

    assert len(report.segments) == 1
    assert report.segments[0].video_record_id == own.id
    assert report.missing_intervals[0].started_at == _utc(own.ended_at)
    assert report.missing_intervals[0].ended_at == end


def test_hash_prefix_and_case_still_match(db_session: Session, tmp_path: Path) -> None:
    started = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    ended = started + timedelta(seconds=60)
    record = _add_record(
        db_session,
        started,
        ended,
        segment_hash="0x" + FILE_HASH.upper(),
    )
    anchor = _anchor_for(record, segment_hash=FILE_HASH)

    report = verify_recording_range(
        db_session,
        CAMERA_ID,
        started,
        ended,
        work_dir=tmp_path,
        read_anchor=_reader_for(record, anchor),
        fetch_file=_fetch_bytes(FILE_BYTES),
        hash_file=sha256_file,
    )

    assert report.overall == "verified"
    assert len(report.eligible) == 1


def test_invalid_window_raises(db_session: Session, tmp_path: Path) -> None:
    moment = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(RecordingVerificationError, match="End time must be after"):
        verify_recording_range(
            db_session,
            CAMERA_ID,
            moment,
            moment,
            work_dir=tmp_path,
        )


def test_subsecond_times_match_on_whole_seconds(
    db_session: Session, tmp_path: Path
) -> None:
    started = datetime(2026, 8, 24, 12, 0, 1, 400000, tzinfo=timezone.utc)
    ended = started + timedelta(seconds=33, microseconds=200000)
    record = _add_record(db_session, started, ended)
    chain_start = datetime(2026, 8, 24, 12, 0, 1, tzinfo=timezone.utc)
    chain_end = datetime(2026, 8, 24, 12, 0, 34, tzinfo=timezone.utc)

    report = verify_recording_range(
        db_session,
        CAMERA_ID,
        started,
        ended,
        work_dir=tmp_path,
        read_anchor=_reader_for(
            record,
            _anchor_for(record, started_at=chain_start, ended_at=chain_end),
        ),
        fetch_file=_fetch_bytes(FILE_BYTES),
        hash_file=sha256_file,
    )

    assert report.segments[0].status == "verified"
