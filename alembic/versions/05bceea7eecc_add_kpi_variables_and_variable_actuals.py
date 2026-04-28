"""add_kpi_variables_and_variable_actuals

Revision ID: 05bceea7eecc
Revises: 7a3138160dbf
Create Date: 2026-04-27 12:29:50.564184

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '05bceea7eecc'
down_revision: Union[str, None] = '7a3138160dbf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# New enum types created by this migration
_variabledatatype = sa.Enum(
    'NUMBER', 'INTEGER', 'PERCENTAGE', 'CURRENCY', 'BOOLEAN', 'DURATION_HOURS',
    name='variabledatatype',
)
_variablesourcetype = sa.Enum(
    'MANUAL', 'REST_API', 'DATABASE', 'INFLUXDB', 'WEBHOOK_RECEIVE',
    'KPI_ACTUAL', 'CSV_UPLOAD', 'FORMULA',
    name='variablesourcetype',
)
_syncstatus = sa.Enum(
    'NEVER_SYNCED', 'SYNCING', 'SUCCESS', 'FAILED', 'PARTIAL',
    name='syncstatus',
)
# measurementfrequency already exists in the DB — use create_type=False
_measurementfrequency = postgresql.ENUM(
    'DAILY', 'WEEKLY', 'MONTHLY', 'QUARTERLY', 'YEARLY', 'ON_DEMAND',
    name='measurementfrequency',
    create_type=False,
)


def upgrade() -> None:
    # Create new enum types explicitly before the tables that use them
    _variabledatatype.create(op.get_bind(), checkfirst=True)
    _variablesourcetype.create(op.get_bind(), checkfirst=True)
    _syncstatus.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'kpi_variables',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('kpi_id', sa.UUID(), nullable=False),
        sa.Column('variable_name', sa.String(length=50), nullable=False),
        sa.Column('display_label', sa.String(length=150), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('data_type', postgresql.ENUM(name='variabledatatype', create_type=False), nullable=False),
        sa.Column('unit_label', sa.String(length=50), nullable=True),
        sa.Column('source_type', postgresql.ENUM(name='variablesourcetype', create_type=False), nullable=False),
        sa.Column('source_config', sa.JSON(), nullable=True),
        sa.Column('is_required', sa.Boolean(), nullable=False),
        sa.Column('default_value', sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column('auto_sync_enabled', sa.Boolean(), nullable=False),
        sa.Column('sync_frequency', postgresql.ENUM(name='measurementfrequency', create_type=False), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_sync_status', postgresql.ENUM(name='syncstatus', create_type=False), nullable=False),
        sa.Column('last_sync_error', sa.Text(), nullable=True),
        sa.Column('display_order', sa.Integer(), nullable=False),
        sa.Column('organisation_id', sa.UUID(), nullable=False),
        sa.Column('created_by_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("variable_name ~ '^[A-Z][A-Z0-9_]{0,49}$'", name='ck_variable_name_format'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['kpi_id'], ['kpis.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organisation_id'], ['organisations.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('kpi_id', 'variable_name', name='uq_kpi_variable_name'),
    )
    op.create_table(
        'variable_actuals',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('variable_id', sa.UUID(), nullable=False),
        sa.Column('kpi_id', sa.UUID(), nullable=False),
        sa.Column('period_date', sa.Date(), nullable=False),
        sa.Column('raw_value', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('source_type', postgresql.ENUM(name='variablesourcetype', create_type=False), nullable=False),
        sa.Column('sync_metadata', sa.JSON(), nullable=True),
        sa.Column('submitted_by_id', sa.UUID(), nullable=True),
        sa.Column('is_current', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['kpi_id'], ['kpis.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['submitted_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['variable_id'], ['kpi_variables.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_variable_actuals_kpi_period', 'variable_actuals', ['kpi_id', 'period_date'], unique=False)
    op.create_index('ix_variable_actuals_var_period', 'variable_actuals', ['variable_id', 'period_date'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_variable_actuals_var_period', table_name='variable_actuals')
    op.drop_index('ix_variable_actuals_kpi_period', table_name='variable_actuals')
    op.drop_table('variable_actuals')
    op.drop_table('kpi_variables')

    _variabledatatype.drop(op.get_bind(), checkfirst=True)
    _variablesourcetype.drop(op.get_bind(), checkfirst=True)
    _syncstatus.drop(op.get_bind(), checkfirst=True)

