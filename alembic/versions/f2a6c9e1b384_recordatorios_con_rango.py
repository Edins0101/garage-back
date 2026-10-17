"""recordatorios con rango de fechas: ends_on

Revision ID: f2a6c9e1b384
Revises: e4b8f2c6a719
Create Date: 2026-10-17 06:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2a6c9e1b384'
down_revision: Union[str, Sequence[str], None] = 'e4b8f2c6a719'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('reminders', sa.Column('ends_on', sa.Date(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('reminders', 'ends_on')
