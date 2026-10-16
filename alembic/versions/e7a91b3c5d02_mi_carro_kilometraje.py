"""mi carro: cada tantos km y kilometraje al marcar

Revision ID: e7a91b3c5d02
Revises: c4d2a6f81e35
Create Date: 2026-10-16 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7a91b3c5d02'
down_revision: Union[str, Sequence[str], None] = 'c4d2a6f81e35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('reminders', sa.Column('every_km', sa.Integer(), nullable=True))
    op.add_column('reminder_logs', sa.Column('odometer', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('reminder_logs', 'odometer')
    op.drop_column('reminders', 'every_km')
