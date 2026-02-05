"""Merge multiple heads

Revision ID: merge_20260205
Revises: d5c86e2c6dc6, merge_20260204
Create Date: 2026-02-05

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "merge_20260205"
down_revision = ("d5c86e2c6dc6", "merge_20260204")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
