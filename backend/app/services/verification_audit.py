"""Persist one server-side playback or download verification.

The caller decides when verification finished. This module writes that result
once and does not run verification again.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.verification_attempt import (
    VerificationAttempt,
    VerificationAttemptMinute,
)
from app.services.recording_verification import RecordingVerification

logger = logging.getLogger(__name__)

AuditOperation = Literal["playback", "download"]
_DETAIL_MAX = 500
_SCOPE_FOR_OPERATION = {"playback": "minute", "download": "full"}


def save_verification_audit(
    db: Session,
    *,
    user_id: UUID,
    camera_id: UUID,
    started_at: datetime,
    ended_at: datetime,
    operation: AuditOperation,
    report: RecordingVerification,
) -> bool:
    """Store ``report`` for this user and camera.

    Returns True only after commit. A database failure is logged and rolled
    back; the caller still serves the verification result it already has.
    """
    attempt = VerificationAttempt(
        user_id=user_id,
        camera_id=camera_id,
        started_at=started_at,
        ended_at=ended_at,
        scope=_SCOPE_FOR_OPERATION[operation],
        operation=operation,
        overall_status=report.overall,
        created_at=datetime.now(timezone.utc),
    )
    for segment in report.segments:
        attempt.minutes.append(
            VerificationAttemptMinute(
                started_at=segment.started_at,
                status=segment.status,
                detail=segment.detail[:_DETAIL_MAX],
                video_record_id=segment.video_record_id,
            )
        )
    try:
        db.add(attempt)
        db.commit()
    except Exception:
        logger.exception(
            "Verification audit was not saved for camera %s user %s operation %s",
            camera_id,
            user_id,
            operation,
        )
        db.rollback()
        return False
    return True
