"""Merge multiple heads

Revision ID: merge_20260204
Revises: 6a62e30d89f9, 90b409d06e50
Create Date: 2026-02-04

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "merge_20260204"
down_revision = ("6a62e30d89f9", "90b409d06e50")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
