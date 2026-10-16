"""contadores por día: el garaje pasa a ser un contador (tabla trackers)

Cada usuario que ya usaba el garaje recibe un contador "Mi garaje" con su tarifa y su
marcado automático; sus días y pagos pasan a ese contador.

Revision ID: a3f5c8d1e947
Revises: e7a91b3c5d02
Create Date: 2026-10-16 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f5c8d1e947'
down_revision: Union[str, Sequence[str], None] = 'e7a91b3c5d02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('trackers',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('icon', sa.String(length=16), nullable=False),
    sa.Column('direction', sa.String(length=8), server_default='pay', nullable=False),
    sa.Column('daily_rate', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('auto_mark', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('auto_filled_until', sa.Date(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_trackers_owner_id'), 'trackers', ['owner_id'], unique=False)

    # Un "Mi garaje" por cada usuario que ya usaba el garaje, con su configuración.
    op.execute("""
        INSERT INTO trackers (id, owner_id, name, icon, direction, daily_rate, auto_mark, auto_filled_until,
                              created_at, updated_at)
        SELECT gen_random_uuid()::text, u.id, 'Mi garaje', 'car', 'pay', u.garage_daily_rate, u.garage_auto_mark,
               u.garage_auto_filled_until, now(), now()
        FROM users u
        WHERE u.garage_daily_rate IS NOT NULL OR u.garage_auto_mark
           OR EXISTS (SELECT 1 FROM garage_days d WHERE d.user_id = u.id)
           OR EXISTS (SELECT 1 FROM payments p WHERE p.user_id = u.id)
    """)

    for table in ('garage_days', 'payments'):
        op.add_column(table, sa.Column('tracker_id', sa.String(length=36), nullable=True))
        op.execute(f"UPDATE {table} SET tracker_id = t.id FROM trackers t WHERE t.owner_id = {table}.user_id")
        op.alter_column(table, 'tracker_id', existing_type=sa.String(length=36), nullable=False)
        op.create_index(op.f(f'ix_{table}_tracker_id'), table, ['tracker_id'], unique=False)
        op.create_foreign_key(f'fk_{table}_tracker_id_trackers', table, 'trackers', ['tracker_id'], ['id'], ondelete='CASCADE')

    op.drop_constraint('garage_days_user_id_date_key', 'garage_days', type_='unique')
    op.create_unique_constraint('garage_days_tracker_id_date_key', 'garage_days', ['tracker_id', 'date'])

    op.drop_column('users', 'garage_auto_filled_until')
    op.drop_column('users', 'garage_auto_mark')
    op.drop_column('users', 'garage_daily_rate')


def downgrade() -> None:
    """Downgrade schema: solo se conserva el primer contador de cada usuario (los demás se pierden)."""
    op.add_column('users', sa.Column('garage_daily_rate', sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column('users', sa.Column('garage_auto_mark', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('users', sa.Column('garage_auto_filled_until', sa.Date(), nullable=True))
    op.execute("""
        WITH first AS (
            SELECT DISTINCT ON (owner_id) id, owner_id, daily_rate, auto_mark, auto_filled_until
            FROM trackers ORDER BY owner_id, created_at
        )
        UPDATE users SET garage_daily_rate = first.daily_rate, garage_auto_mark = first.auto_mark,
                         garage_auto_filled_until = first.auto_filled_until
        FROM first WHERE first.owner_id = users.id
    """)
    op.execute("""
        DELETE FROM garage_days WHERE tracker_id NOT IN (
            SELECT DISTINCT ON (owner_id) id FROM trackers ORDER BY owner_id, created_at)
    """)
    op.execute("""
        DELETE FROM payments WHERE tracker_id NOT IN (
            SELECT DISTINCT ON (owner_id) id FROM trackers ORDER BY owner_id, created_at)
    """)
    op.drop_constraint('garage_days_tracker_id_date_key', 'garage_days', type_='unique')
    op.create_unique_constraint('garage_days_user_id_date_key', 'garage_days', ['user_id', 'date'])
    for table in ('garage_days', 'payments'):
        op.drop_constraint(f'fk_{table}_tracker_id_trackers', table, type_='foreignkey')
        op.drop_index(op.f(f'ix_{table}_tracker_id'), table_name=table)
        op.drop_column(table, 'tracker_id')
    op.drop_index(op.f('ix_trackers_owner_id'), table_name='trackers')
    op.drop_table('trackers')
