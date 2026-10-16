"""recordatorios y secciones compartidas

Revision ID: 8b3e1d7a9c20
Revises: 1f8ccde247b4
Create Date: 2026-10-16 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b3e1d7a9c20'
down_revision: Union[str, Sequence[str], None] = '1f8ccde247b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('spaces',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'kind')
    )
    op.create_index(op.f('ix_spaces_owner_id'), 'spaces', ['owner_id'], unique=False)

    op.create_table('space_members',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('space_id', sa.String(length=36), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=True),
    sa.Column('user_id', sa.String(length=36), nullable=True),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('invited_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['space_id'], ['spaces.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('space_id', 'email')
    )
    op.create_index(op.f('ix_space_members_email'), 'space_members', ['email'], unique=False)
    op.create_index(op.f('ix_space_members_space_id'), 'space_members', ['space_id'], unique=False)
    op.create_index(op.f('ix_space_members_user_id'), 'space_members', ['user_id'], unique=False)

    op.create_table('reminders',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('space_id', sa.String(length=36), nullable=False),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('every', sa.Integer(), nullable=True),
    sa.Column('unit', sa.String(length=8), nullable=True),
    sa.Column('anchor_day', sa.Integer(), nullable=True),
    sa.Column('next_due', sa.Date(), nullable=False),
    sa.Column('notify_days_before', sa.Integer(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('finished', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['space_id'], ['spaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reminders_space_id'), 'reminders', ['space_id'], unique=False)

    op.create_table('reminder_logs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('reminder_id', sa.String(length=36), nullable=False),
    sa.Column('due_date', sa.Date(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('note', sa.String(length=200), nullable=True),
    sa.Column('done_by', sa.String(length=36), nullable=True),
    sa.Column('done_by_name', sa.String(length=120), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['done_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['reminder_id'], ['reminders.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reminder_logs_reminder_id'), 'reminder_logs', ['reminder_id'], unique=False)

    # Las invitaciones pueden ser a una lista o a una sección.
    with op.batch_alter_table('invites') as batch:
        batch.alter_column('list_id', existing_type=sa.String(length=36), nullable=True)
        batch.add_column(sa.Column('space_id', sa.String(length=36), nullable=True))
        batch.create_index(batch.f('ix_invites_space_id'), ['space_id'], unique=False)
        batch.create_foreign_key('fk_invites_space_id_spaces', 'spaces', ['space_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM invites WHERE list_id IS NULL")
    with op.batch_alter_table('invites') as batch:
        batch.drop_constraint('fk_invites_space_id_spaces', type_='foreignkey')
        batch.drop_index(batch.f('ix_invites_space_id'))
        batch.drop_column('space_id')
        batch.alter_column('list_id', existing_type=sa.String(length=36), nullable=False)
    op.drop_index(op.f('ix_reminder_logs_reminder_id'), table_name='reminder_logs')
    op.drop_table('reminder_logs')
    op.drop_index(op.f('ix_reminders_space_id'), table_name='reminders')
    op.drop_table('reminders')
    op.drop_index(op.f('ix_space_members_user_id'), table_name='space_members')
    op.drop_index(op.f('ix_space_members_space_id'), table_name='space_members')
    op.drop_index(op.f('ix_space_members_email'), table_name='space_members')
    op.drop_table('space_members')
    op.drop_index(op.f('ix_spaces_owner_id'), table_name='spaces')
    op.drop_table('spaces')
