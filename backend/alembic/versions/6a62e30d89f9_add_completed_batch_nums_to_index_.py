"""add completed_batch_nums to index_attempt

Revision ID: 6a62e30d89f9
Revises: e7f8a9b0c1d2
Create Date: 2026-02-02 17:30:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "6a62e30d89f9"
down_revision = "a3b8d9e2f1c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "index_attempt",
        sa.Column(
            "completed_batch_nums",
            postgresql.JSONB(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("index_attempt", "completed_batch_nums")
