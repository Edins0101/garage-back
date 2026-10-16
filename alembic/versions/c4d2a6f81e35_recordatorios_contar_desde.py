"""recordatorios: contar el siguiente desde la fecha o desde que se hizo

Revision ID: c4d2a6f81e35
Revises: 8b3e1d7a9c20
Create Date: 2026-10-16 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d2a6f81e35'
down_revision: Union[str, Sequence[str], None] = '8b3e1d7a9c20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('reminders', sa.Column('count_from', sa.String(length=8), server_default='due', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('reminders', 'count_from')
