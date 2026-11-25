"""Add soft-delete and unique active camera name per user.

Revision ID: 20260721_000002
Revises: 20260505_000001
Create Date: 2026-07-21 16:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260721_000002"
down_revision = "20260505_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_cameras_deleted_at", "cameras", ["deleted_at"])
    op.create_index(
        "uq_cameras_user_id_name_active",
        "cameras",
        ["user_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )

    # Soft-deleted cameras must keep historical video_records (Slice B / CP-B.P3).
    op.drop_constraint(
        "video_records_camera_id_fkey",
        "video_records",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "video_records_camera_id_fkey",
        "video_records",
        "cameras",
        ["camera_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "video_records_camera_id_fkey",
        "video_records",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "video_records_camera_id_fkey",
        "video_records",
        "cameras",
        ["camera_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_index("uq_cameras_user_id_name_active", table_name="cameras")
    op.drop_index("ix_cameras_deleted_at", table_name="cameras")
    op.drop_column("cameras", "deleted_at")
