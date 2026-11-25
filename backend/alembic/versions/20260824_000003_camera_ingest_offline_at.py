"""Add ingest_offline_at for capture restart cap (Slice C / CP-C.P8).

Revision ID: 20260824_000003
Revises: 20260721_000002
Create Date: 2026-08-24 15:21:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260824_000003"
down_revision = "20260721_000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column("ingest_offline_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cameras", "ingest_offline_at")
