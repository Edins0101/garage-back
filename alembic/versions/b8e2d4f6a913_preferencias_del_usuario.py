"""preferencias de la app en la cuenta (inicio y color)

Revision ID: b8e2d4f6a913
Revises: a7d3e5f9c216
Create Date: 2026-10-17 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8e2d4f6a913'
down_revision: Union[str, Sequence[str], None] = 'a7d3e5f9c216'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('preferences', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'preferences')
