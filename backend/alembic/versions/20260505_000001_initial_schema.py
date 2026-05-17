"""Create initial users, cameras, and video records tables (UUID).

Revision ID: 20260505_000001
Revises: None
Create Date: 2026-05-05 18:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260505_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "cameras",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("stream_url", sa.String(length=2000), nullable=False),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_cameras_user_id", "cameras", ["user_id"])

    op.create_table(
        "video_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("camera_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ipfs_cid", sa.String(length=255), nullable=False),
        sa.Column("tx_hash", sa.String(length=66), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_video_records_camera_id", "video_records", ["camera_id"])
    op.create_index("ix_video_records_started_at", "video_records", ["started_at"])
    op.create_index("ix_video_records_ipfs_cid", "video_records", ["ipfs_cid"])
    op.create_index("ix_video_records_tx_hash", "video_records", ["tx_hash"])


def downgrade() -> None:
    op.drop_index("ix_video_records_tx_hash", table_name="video_records")
    op.drop_index("ix_video_records_ipfs_cid", table_name="video_records")
    op.drop_index("ix_video_records_started_at", table_name="video_records")
    op.drop_index("ix_video_records_camera_id", table_name="video_records")
    op.drop_table("video_records")
    op.drop_index("ix_cameras_user_id", table_name="cameras")
    op.drop_table("cameras")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
