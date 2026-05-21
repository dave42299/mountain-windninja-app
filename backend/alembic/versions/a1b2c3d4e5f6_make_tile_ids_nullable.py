"""make elevation_tile_id nullable

Revision ID: a1b2c3d4e5f6
Revises: 6434a0ff27e2
Create Date: 2026-05-21 02:55:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "6434a0ff27e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "forecasts", "elevation_tile_id", existing_type=op.f("UUID"), nullable=True
    )


def downgrade() -> None:
    op.alter_column(
        "forecasts", "elevation_tile_id", existing_type=op.f("UUID"), nullable=False
    )
