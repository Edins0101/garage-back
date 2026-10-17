"""hora y anticipación en recordatorios; lista adjunta a recordatorios y contadores

Revision ID: d1c7e9a2f430
Revises: b8e2d4f6a013
Create Date: 2026-10-16 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1c7e9a2f430'
down_revision: Union[str, Sequence[str], None] = 'b8e2d4f6a013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('reminders', sa.Column('due_time', sa.Time(), nullable=True))
    op.add_column('reminders', sa.Column('alert_minutes', sa.Integer(), nullable=True))
    op.add_column('reminders', sa.Column('list_id', sa.String(length=36), nullable=True))
    op.create_index(op.f('ix_reminders_list_id'), 'reminders', ['list_id'], unique=False)
    op.create_foreign_key(
        'reminders_list_id_fkey', 'reminders', 'checklists', ['list_id'], ['id'], ondelete='SET NULL'
    )
    op.add_column('trackers', sa.Column('list_id', sa.String(length=36), nullable=True))
    op.create_index(op.f('ix_trackers_list_id'), 'trackers', ['list_id'], unique=False)
    op.create_foreign_key(
        'trackers_list_id_fkey', 'trackers', 'checklists', ['list_id'], ['id'], ondelete='SET NULL'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('trackers_list_id_fkey', 'trackers', type_='foreignkey')
    op.drop_index(op.f('ix_trackers_list_id'), table_name='trackers')
    op.drop_column('trackers', 'list_id')
    op.drop_constraint('reminders_list_id_fkey', 'reminders', type_='foreignkey')
    op.drop_index(op.f('ix_reminders_list_id'), table_name='reminders')
    op.drop_column('reminders', 'list_id')
    op.drop_column('reminders', 'alert_minutes')
    op.drop_column('reminders', 'due_time')
