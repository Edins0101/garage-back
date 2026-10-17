"""grupos: integrantes, lo compartido con cada grupo e invitaciones a grupos

Revision ID: e4b8f2c6a719
Revises: d1c7e9a2f430
Create Date: 2026-10-16 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4b8f2c6a719'
down_revision: Union[str, Sequence[str], None] = 'd1c7e9a2f430'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('groups',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_groups_owner_id'), 'groups', ['owner_id'], unique=False)
    op.create_table('group_members',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('group_id', sa.String(length=36), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=True),
    sa.Column('user_id', sa.String(length=36), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('invited_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('group_id', 'email')
    )
    op.create_index(op.f('ix_group_members_email'), 'group_members', ['email'], unique=False)
    op.create_index(op.f('ix_group_members_group_id'), 'group_members', ['group_id'], unique=False)
    op.create_index(op.f('ix_group_members_user_id'), 'group_members', ['user_id'], unique=False)
    op.create_table('group_shares',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('group_id', sa.String(length=36), nullable=False),
    sa.Column('list_id', sa.String(length=36), nullable=True),
    sa.Column('space_id', sa.String(length=36), nullable=True),
    sa.Column('tracker_id', sa.String(length=36), nullable=True),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['list_id'], ['checklists.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['space_id'], ['spaces.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tracker_id'], ['trackers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('group_id', 'list_id'),
    sa.UniqueConstraint('group_id', 'space_id'),
    sa.UniqueConstraint('group_id', 'tracker_id')
    )
    op.create_index(op.f('ix_group_shares_group_id'), 'group_shares', ['group_id'], unique=False)
    op.create_index(op.f('ix_group_shares_list_id'), 'group_shares', ['list_id'], unique=False)
    op.create_index(op.f('ix_group_shares_space_id'), 'group_shares', ['space_id'], unique=False)
    op.create_index(op.f('ix_group_shares_tracker_id'), 'group_shares', ['tracker_id'], unique=False)
    op.add_column('invites', sa.Column('group_id', sa.String(length=36), nullable=True))
    op.create_index(op.f('ix_invites_group_id'), 'invites', ['group_id'], unique=False)
    op.create_foreign_key('invites_group_id_fkey', 'invites', 'groups', ['group_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('invites_group_id_fkey', 'invites', type_='foreignkey')
    op.drop_index(op.f('ix_invites_group_id'), table_name='invites')
    op.drop_column('invites', 'group_id')
    op.drop_table('group_shares')
    op.drop_table('group_members')
    op.drop_table('groups')
