"""Add segment_hash and allow video_records.tx_hash to be null (CP-D.P6).

Revision ID: 20260914_000004
Revises: 20260824_000003
Create Date: 2026-09-14 14:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260914_000004"
down_revision = "20260824_000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "video_records",
        sa.Column("segment_hash", sa.String(length=64), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE video_records SET segment_hash = repeat('0', 64) "
            "WHERE segment_hash IS NULL"
        )
    )
    op.alter_column(
        "video_records",
        "segment_hash",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.alter_column(
        "video_records",
        "tx_hash",
        existing_type=sa.String(length=66),
        nullable=True,
    )
    op.create_unique_constraint(
        "uq_video_records_camera_id_started_at",
        "video_records",
        ["camera_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_video_records_camera_id_started_at",
        "video_records",
        type_="unique",
    )
    op.execute(
        sa.text(
            "UPDATE video_records SET tx_hash = repeat('0', 66) "
            "WHERE tx_hash IS NULL"
        )
    )
    op.alter_column(
        "video_records",
        "tx_hash",
        existing_type=sa.String(length=66),
        nullable=False,
    )
    op.drop_column("video_records", "segment_hash")
