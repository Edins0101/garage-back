"""compartir contadores: miembros e invitaciones a contadores

Revision ID: b8e2d4f6a013
Revises: a3f5c8d1e947
Create Date: 2026-10-16 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8e2d4f6a013'
down_revision: Union[str, Sequence[str], None] = 'a3f5c8d1e947'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('tracker_members',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('tracker_id', sa.String(length=36), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=True),
    sa.Column('user_id', sa.String(length=36), nullable=True),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('invited_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['tracker_id'], ['trackers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tracker_id', 'email')
    )
    op.create_index(op.f('ix_tracker_members_email'), 'tracker_members', ['email'], unique=False)
    op.create_index(op.f('ix_tracker_members_tracker_id'), 'tracker_members', ['tracker_id'], unique=False)
    op.create_index(op.f('ix_tracker_members_user_id'), 'tracker_members', ['user_id'], unique=False)

    op.add_column('invites', sa.Column('tracker_id', sa.String(length=36), nullable=True))
    op.create_index(op.f('ix_invites_tracker_id'), 'invites', ['tracker_id'], unique=False)
    op.create_foreign_key('fk_invites_tracker_id_trackers', 'invites', 'trackers', ['tracker_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM invites WHERE tracker_id IS NOT NULL")
    op.drop_constraint('fk_invites_tracker_id_trackers', 'invites', type_='foreignkey')
    op.drop_index(op.f('ix_invites_tracker_id'), table_name='invites')
    op.drop_column('invites', 'tracker_id')
    op.drop_index(op.f('ix_tracker_members_user_id'), table_name='tracker_members')
    op.drop_index(op.f('ix_tracker_members_tracker_id'), table_name='tracker_members')
    op.drop_index(op.f('ix_tracker_members_email'), table_name='tracker_members')
    op.drop_table('tracker_members')
