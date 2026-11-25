"""Add operation to verification attempts.

Revision ID: 20261118_000006
Revises: 20260917_000005
Create Date: 2026-11-18 19:40:00

Existing client-submitted rows keep a null operation. Playback and download
audits set ``playback`` or ``download``. Status columns are already strings,
so ``unavailable`` and ``failed`` need no further change.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261118_000006"
down_revision = "20260917_000005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "verification_attempts",
        sa.Column("operation", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("verification_attempts", "operation")
