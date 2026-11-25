"""PostgreSQL checks for permanent deletion. Never uses the development database.

The fixture creates ``datachain_deletion_itest``, upgrades Alembic there, and
drops it. Pinata and blockchain calls are not made.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.database import get_database_url
from app.models.camera import Camera
from app.models.user import User
from app.models.verification_attempt import (
    VerificationAttempt,
    VerificationAttemptMinute,
)
from app.models.video_record import VideoRecord
from app.services.camera_deletion import (
    HAS_DEPENDENT_DATA,
    PermanentDeleteError,
    permanently_delete_camera,
    try_hold_ingest_locks,
)

TEST_DATABASE = "datachain_deletion_itest"
PROTECTED_DATABASES = {"datachain", "datachain_local", "postgres"}
CID = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
FILE_HASH = "ab" * 32
TX = "0x" + "cd" * 32
NOON = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _swap_database(url: str, database: str) -> str:
    if database in PROTECTED_DATABASES:
        raise RuntimeError(f"Refusing to target protected database {database}")
    return urlunsplit(urlsplit(url)._replace(path=f"/{database}"))


def _postgres_available(admin_url: str) -> bool:
    try:
        engine = create_engine(
            admin_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True
        )
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar()
        engine.dispose()
    except OperationalError:
        return False
    return True


@pytest.fixture(scope="module")
def postgres_url() -> str:
    """Apply the migration chain on a new database, then drop that database."""
    if TEST_DATABASE in PROTECTED_DATABASES:
        pytest.skip("test database name collides with a protected database")
    configured = get_database_url()
    source = urlsplit(configured).path.lstrip("/")
    if source == TEST_DATABASE:
        pytest.skip("DATABASE_URL already points at the disposable database")
    admin_url = configured
    if not _postgres_available(admin_url):
        pytest.skip("PostgreSQL is not available for an isolated deletion database")
    test_url = _swap_database(configured, TEST_DATABASE)
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        current = connection.execute(text("SELECT current_database()")).scalar()
        if current == TEST_DATABASE:
            raise RuntimeError("admin connection is the disposable database")
        connection.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :name AND pid <> pg_backend_pid()"
            ),
            {"name": TEST_DATABASE},
        )
        connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DATABASE}"'))
        connection.execute(text(f'CREATE DATABASE "{TEST_DATABASE}"'))
    admin.dispose()

    env = os.environ.copy()
    env["DATABASE_URL"] = test_url
    upgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if upgrade.returncode != 0:
        _drop_test_database(admin_url)
        raise RuntimeError(upgrade.stderr or upgrade.stdout)

    try:
        yield test_url
    finally:
        _drop_test_database(admin_url)


def _drop_test_database(admin_url: str) -> None:
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        current = connection.execute(text("SELECT current_database()")).scalar()
        if current == TEST_DATABASE:
            raise RuntimeError("refusing to drop the database of this connection")
        connection.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :name AND pid <> pg_backend_pid()"
            ),
            {"name": TEST_DATABASE},
        )
        connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DATABASE}"'))
    admin.dispose()


@pytest.fixture
def pg_session(postgres_url: str) -> Session:
    engine = create_engine(postgres_url, pool_pre_ping=True)
    with engine.connect() as connection:
        name = connection.execute(text("SELECT current_database()")).scalar()
        if name != TEST_DATABASE:
            raise RuntimeError(f"refusing to run deletion tests on {name}")
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_migration_matches_the_current_chain_and_keeps_restrict(
    postgres_url: str,
) -> None:
    engine = create_engine(postgres_url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT current_database()")).scalar() == (
            TEST_DATABASE
        )
        version = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
        assert version == "20261118_000006"
        operation_nullable = connection.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'public' "
                "AND table_name = 'verification_attempts' "
                "AND column_name = 'operation'"
            )
        ).scalar()
        assert operation_nullable == "YES"
        present = connection.execute(
            text("SELECT to_regclass('public.deletion_cleanup_tasks')")
        ).scalar()
        assert present is None
        video_fk = connection.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'video_records_camera_id_fkey'"
            )
        ).scalar()
        attempt_fk = connection.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'verification_attempts_camera_id_fkey'"
            )
        ).scalar()
        assert "ON DELETE RESTRICT" in video_fk
        assert "ON DELETE RESTRICT" in attempt_fk
    engine.dispose()


def test_advisory_locks_block_a_second_transaction_until_rollback(
    pg_session: Session,
) -> None:
    camera_id = uuid4()
    other = sessionmaker(bind=pg_session.get_bind())()
    try:
        assert try_hold_ingest_locks(pg_session, camera_id) is True
        assert try_hold_ingest_locks(other, camera_id) is False
        pg_session.rollback()
        assert try_hold_ingest_locks(other, camera_id) is True
        other.rollback()
    finally:
        other.close()


def test_postgres_delete_removes_only_an_empty_camera(
    pg_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_external(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("external call")

    monkeypatch.setattr("app.services.chain_anchor.anchor_segment", fail_external)
    monkeypatch.setattr("app.services.chain_anchor.get_segment", fail_external)
    monkeypatch.setattr("app.services.pinata_ipfs.requests.delete", fail_external)
    monkeypatch.setattr("app.services.pinata_ipfs.requests.post", fail_external)
    user = User(
        id=uuid4(),
        email=f"pg-{uuid4()}@example.com",
        password_hash="not-used",
    )
    owner = user.id
    pg_session.add(user)
    deleted = Camera(
        id=uuid4(),
        user_id=owner,
        name="Disposable",
        stream_url="rtsp://192.0.2.40/live",
        deleted_at=NOON,
    )
    kept = Camera(
        id=uuid4(),
        user_id=owner,
        name="Kept",
        stream_url="rtsp://192.0.2.41/live",
        deleted_at=NOON,
    )
    pg_session.add_all([deleted, kept])
    pg_session.flush()
    record = VideoRecord(
        id=uuid4(),
        camera_id=deleted.id,
        started_at=NOON,
        ended_at=NOON + timedelta(seconds=60),
        ipfs_cid=CID,
        segment_hash=FILE_HASH,
        tx_hash=TX,
    )
    shared = VideoRecord(
        id=uuid4(),
        camera_id=kept.id,
        started_at=NOON,
        ended_at=NOON + timedelta(seconds=60),
        ipfs_cid=CID,
        segment_hash=FILE_HASH,
        tx_hash=TX,
    )
    attempt = VerificationAttempt(
        id=uuid4(),
        user_id=owner,
        camera_id=deleted.id,
        started_at=NOON,
        ended_at=NOON + timedelta(minutes=1),
        scope="minute",
        overall_status="verified",
    )
    pg_session.add_all([record, shared, attempt])
    pg_session.flush()
    pg_session.add(
        VerificationAttemptMinute(
            id=uuid4(),
            attempt_id=attempt.id,
            started_at=NOON,
            status="verified",
            detail="ok",
            video_record_id=record.id,
        )
    )
    pg_session.commit()
    deleted_id = deleted.id
    kept_id = kept.id
    record_id = record.id
    shared_id = shared.id
    attempt_id = attempt.id
    folder = tmp_path / "temp" / str(deleted_id)
    folder.mkdir(parents=True)
    (folder / "segment.mp4").write_bytes(b"segment")
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()

    with pytest.raises(PermanentDeleteError) as exc:
        permanently_delete_camera(
            pg_session,
            camera_id=deleted_id,
            owner_id=owner,
            confirm_name="Disposable",
            temp_root=tmp_path / "temp",
            quarantine_root=quarantine,
            command_lister=lambda: [],
        )
    assert exc.value.status_code == 409
    assert exc.value.detail == HAS_DEPENDENT_DATA
    assert (folder / "segment.mp4").read_bytes() == b"segment"
    pg_session.expire_all()
    assert pg_session.get(Camera, deleted_id) is not None
    kept_record = pg_session.get(VideoRecord, record_id)
    assert kept_record is not None
    assert kept_record.tx_hash == TX
    assert pg_session.get(VerificationAttempt, attempt_id) is not None
    assert pg_session.get(Camera, kept_id) is not None
    other_record = pg_session.get(VideoRecord, shared_id)
    assert other_record is not None
    assert other_record.tx_hash == TX

    empty = Camera(
        id=uuid4(),
        user_id=owner,
        name="Empty",
        stream_url="rtsp://192.0.2.43/live",
        deleted_at=NOON,
    )
    pg_session.add(empty)
    pg_session.commit()
    empty_id = empty.id
    empty_folder = tmp_path / "temp" / str(empty_id)
    empty_folder.mkdir()
    (empty_folder / "segment.mp4").write_bytes(b"leave")
    outcome = permanently_delete_camera(
        pg_session,
        camera_id=empty_id,
        owner_id=owner,
        confirm_name="Empty",
        temp_root=tmp_path / "temp",
        quarantine_root=quarantine,
        command_lister=lambda: [],
    )
    assert outcome.deleted is True
    assert outcome.message == "Camera deleted."
    assert (empty_folder / "segment.mp4").read_bytes() == b"leave"
    pg_session.expire_all()
    assert pg_session.get(Camera, empty_id) is None
    assert pg_session.get(Camera, deleted_id) is not None


def test_row_lock_stops_restore_until_the_delete_transaction_ends(
    pg_session: Session,
) -> None:
    user = User(
        id=uuid4(),
        email=f"lock-{uuid4()}@example.com",
        password_hash="not-used",
    )
    camera = Camera(
        id=uuid4(),
        user_id=user.id,
        name="Locked",
        stream_url="rtsp://192.0.2.42/live",
        deleted_at=NOON,
    )
    pg_session.add_all([user, camera])
    pg_session.commit()
    other = sessionmaker(bind=pg_session.get_bind())()
    try:
        locked = pg_session.execute(
            text("SELECT id FROM cameras WHERE id = :id FOR UPDATE"),
            {"id": camera.id},
        ).scalar()
        assert locked == camera.id
        other.execute(text("SET LOCAL lock_timeout = '300ms'"))
        with pytest.raises(OperationalError):
            other.execute(
                text("UPDATE cameras SET deleted_at = NULL WHERE id = :id"),
                {"id": camera.id},
            )
        other.rollback()
        pg_session.rollback()
        other.execute(
            text("UPDATE cameras SET deleted_at = NULL WHERE id = :id"),
            {"id": camera.id},
        )
        other.commit()
        pg_session.expire_all()
        restored = pg_session.get(Camera, camera.id)
        assert restored is not None
        assert restored.deleted_at is None
    finally:
        other.close()
