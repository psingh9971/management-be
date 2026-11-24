"""multi-tenancy: tenants table and tenant_id on every tenant-owned table

All existing rows are moved into the initial tenant, JPenterprises (slug 'jpenterprises').

Revision ID: e5a2c7f3b8d1
Revises: d4f8a1b9e3c2
Create Date: 2026-11-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a2c7f3b8d1'
down_revision: Union[str, Sequence[str], None] = 'd4f8a1b9e3c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Fixed so the migration also works in offline (--sql) mode
# The initial tenant that owns all pre-tenancy data
DEFAULT_TENANT_ID = '00000000-0000-0000-0000-000000000001'

TENANT_TABLES = [
    'users',
    'employees',
    'employee_bank_details',
    'employee_aadhaar_cards',
    'employee_pan_cards',
    'attendance_punches',
    'attendance_records',
    'week_off_policies',
    'holidays',
    'leave_types',
    'leave_balances',
    'leave_requests',
    'salary_structures',
    'employee_salary_assignments',
    'salary_slips',
    'offer_letters',
]

# Globally-unique constraints (Postgres default names) -> per-tenant replacements
UNIQUE_SWAPS = [
    # (table, old constraint, new constraint, column)
    ('employees', 'employees_email_key', 'uq_employees_tenant_email', 'email'),
    ('employee_aadhaar_cards', 'employee_aadhaar_cards_aadhaar_number_key', 'uq_aadhaar_cards_tenant_number', 'aadhaar_number'),
    ('employee_pan_cards', 'employee_pan_cards_pan_number_key', 'uq_pan_cards_tenant_number', 'pan_number'),
    ('week_off_policies', 'week_off_policies_name_key', 'uq_week_off_policies_tenant_name', 'name'),
    ('leave_types', 'leave_types_name_key', 'uq_leave_types_tenant_name', 'name'),
    ('leave_types', 'leave_types_code_key', 'uq_leave_types_tenant_code', 'code'),
    ('salary_structures', 'salary_structures_name_key', 'uq_salary_structures_tenant_name', 'name'),
    ('offer_letters', 'offer_letters_letter_number_key', 'uq_offer_letters_tenant_number', 'letter_number'),
]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'tenants',
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('slug', sa.String(length=63), nullable=False),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_tenants_slug'), 'tenants', ['slug'], unique=True)

    op.execute(
        f"INSERT INTO tenants (id, name, slug) VALUES ('{DEFAULT_TENANT_ID}', 'JPenterprises', 'jpenterprises')"
    )

    for table in TENANT_TABLES:
        op.add_column(table, sa.Column('tenant_id', sa.Uuid(), nullable=True))
        op.execute(f"UPDATE {table} SET tenant_id = '{DEFAULT_TENANT_ID}'")
        op.alter_column(table, 'tenant_id', nullable=False)
        op.create_foreign_key(
            f'{table}_tenant_id_fkey', table, 'tenants', ['tenant_id'], ['id'], ondelete='RESTRICT'
        )
        op.create_index(f'ix_{table}_tenant_id', table, ['tenant_id'], unique=False)

    # ---- Unique values become unique per tenant ----
    for table, old, new, column in UNIQUE_SWAPS:
        op.execute(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {old}')
        op.create_unique_constraint(new, table, ['tenant_id', column])

    # Unique indexes -> plain indexes + per-tenant unique constraints
    op.drop_index('ix_employees_employee_code', table_name='employees')
    op.create_index('ix_employees_employee_code', 'employees', ['employee_code'], unique=False)
    op.create_unique_constraint('uq_employees_tenant_code', 'employees', ['tenant_id', 'employee_code'])

    op.drop_index('ix_holidays_date', table_name='holidays')
    op.create_index('ix_holidays_date', 'holidays', ['date'], unique=False)
    op.create_unique_constraint('uq_holidays_tenant_date', 'holidays', ['tenant_id', 'date'])

    # One default week-off policy per tenant (was: one overall)
    op.drop_index('uq_week_off_policies_single_default', table_name='week_off_policies')
    op.create_index(
        'uq_week_off_policies_single_default', 'week_off_policies', ['tenant_id'],
        unique=True, postgresql_where=sa.text('is_default'),
    )


def downgrade() -> None:
    """Downgrade schema. Fails if two tenants share a value that was globally unique before."""
    op.drop_index('uq_week_off_policies_single_default', table_name='week_off_policies')
    op.create_index(
        'uq_week_off_policies_single_default', 'week_off_policies', ['is_default'],
        unique=True, postgresql_where=sa.text('is_default'),
    )

    op.drop_constraint('uq_holidays_tenant_date', 'holidays', type_='unique')
    op.drop_index('ix_holidays_date', table_name='holidays')
    op.create_index('ix_holidays_date', 'holidays', ['date'], unique=True)

    op.drop_constraint('uq_employees_tenant_code', 'employees', type_='unique')
    op.drop_index('ix_employees_employee_code', table_name='employees')
    op.create_index('ix_employees_employee_code', 'employees', ['employee_code'], unique=True)

    for table, old, new, column in reversed(UNIQUE_SWAPS):
        op.drop_constraint(new, table, type_='unique')
        op.create_unique_constraint(old, table, [column])

    for table in reversed(TENANT_TABLES):
        op.drop_index(f'ix_{table}_tenant_id', table_name=table)
        op.drop_constraint(f'{table}_tenant_id_fkey', table, type_='foreignkey')
        op.drop_column(table, 'tenant_id')

    op.drop_index(op.f('ix_tenants_slug'), table_name='tenants')
    op.drop_table('tenants')

