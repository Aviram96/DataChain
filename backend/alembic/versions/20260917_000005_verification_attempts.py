"""Add verification attempt audit tables (CP-E.P8).

Revision ID: 20260917_000005
Revises: 20260914_000004
Create Date: 2026-09-17 16:10:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260917_000005"
down_revision = "20260914_000004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "verification_attempts",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("camera_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("overall_status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_verification_attempts_user_id",
        "verification_attempts",
        ["user_id"],
    )
    op.create_index(
        "ix_verification_attempts_camera_id",
        "verification_attempts",
        ["camera_id"],
    )
    op.create_index(
        "ix_verification_attempts_created_at",
        "verification_attempts",
        ["created_at"],
    )

    op.create_table(
        "verification_attempt_minutes",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.String(length=500), nullable=False),
        sa.Column("video_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["verification_attempts.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_verification_attempt_minutes_attempt_id",
        "verification_attempt_minutes",
        ["attempt_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_verification_attempt_minutes_attempt_id",
        table_name="verification_attempt_minutes",
    )
    op.drop_table("verification_attempt_minutes")
    op.drop_index(
        "ix_verification_attempts_created_at",
        table_name="verification_attempts",
    )
    op.drop_index(
        "ix_verification_attempts_camera_id",
        table_name="verification_attempts",
    )
    op.drop_index(
        "ix_verification_attempts_user_id",
        table_name="verification_attempts",
    )
    op.drop_table("verification_attempts")
