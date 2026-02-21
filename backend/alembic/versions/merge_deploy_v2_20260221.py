"""Merge deploy/v2 alembic heads

Revision ID: merge_deploy_v2
Revises: 0bb4558f35df, 6a62e30d89f9
Create Date: 2026-02-21

"""
from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401

# revision identifiers, used by Alembic.
revision = "merge_deploy_v2"
down_revision = ("0bb4558f35df", "6a62e30d89f9")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
