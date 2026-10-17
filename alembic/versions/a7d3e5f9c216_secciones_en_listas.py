"""secciones dentro de las listas (Baño, Patio, Perros…)

Revision ID: a7d3e5f9c216
Revises: f2a6c9e1b384
Create Date: 2026-10-17 07:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7d3e5f9c216'
down_revision: Union[str, Sequence[str], None] = 'f2a6c9e1b384'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('checklist_items', sa.Column('section', sa.String(length=60), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('checklist_items', 'section')
