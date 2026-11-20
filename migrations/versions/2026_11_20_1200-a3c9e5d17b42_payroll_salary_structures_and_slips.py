"""payroll: salary structures, assignments and salary slips

Revision ID: a3c9e5d17b42
Revises: f0706cea4a3a
Create Date: 2026-11-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a3c9e5d17b42'
down_revision: Union[str, Sequence[str], None] = 'f0706cea4a3a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Some enums are shared by two tables, so they're created once up front (create_type=False below).
ENUMS = {
    'proration_basis': ('working_days', 'calendar_days'),
    'salary_component_type': ('earning', 'deduction'),
    'salary_calculation_type': ('fixed', 'percent_of_gross', 'percent_of_component', 'balance'),
    'salary_slip_status': ('draft', 'finalized', 'paid'),
}
TABLES = (
    'salary_structures',
    'salary_structure_components',
    'employee_salary_assignments',
    'salary_slips',
    'salary_slip_lines',
)


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)


def _timestamps():
    return [
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    ]


def _id():
    return sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    op.create_table('salary_structures',
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('proration_basis', _enum('proration_basis'), server_default='working_days', nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    _id(),
    *_timestamps(),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )

    op.create_table('salary_structure_components',
    sa.Column('structure_id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('component_type', _enum('salary_component_type'), nullable=False),
    sa.Column('calculation_type', _enum('salary_calculation_type'), nullable=False),
    sa.Column('value', sa.Numeric(precision=12, scale=2), server_default='0', nullable=False),
    sa.Column('base_component_code', sa.String(length=20), nullable=True),
    sa.Column('is_prorated', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('sequence', sa.SmallInteger(), nullable=False),
    _id(),
    sa.CheckConstraint('value >= 0', name='ck_salary_component_value'),
    sa.ForeignKeyConstraint(['structure_id'], ['salary_structures.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('structure_id', 'code', name='uq_salary_component_structure_code')
    )
    op.create_index(op.f('ix_salary_structure_components_structure_id'), 'salary_structure_components', ['structure_id'], unique=False)

    op.create_table('employee_salary_assignments',
    sa.Column('employee_id', sa.Uuid(), nullable=False),
    sa.Column('structure_id', sa.Uuid(), nullable=False),
    sa.Column('monthly_gross', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('effective_from', sa.Date(), nullable=False),
    sa.Column('effective_to', sa.Date(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('assigned_by_id', sa.Uuid(), nullable=True),
    _id(),
    *_timestamps(),
    sa.CheckConstraint('effective_to IS NULL OR effective_to >= effective_from', name='ck_salary_assignment_dates'),
    sa.CheckConstraint('monthly_gross > 0', name='ck_salary_assignment_gross'),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['structure_id'], ['salary_structures.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['assigned_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('employee_id', 'effective_from', name='uq_salary_assignment_employee_from')
    )
    op.create_index(op.f('ix_employee_salary_assignments_employee_id'), 'employee_salary_assignments', ['employee_id'], unique=False)

    op.create_table('salary_slips',
    sa.Column('employee_id', sa.Uuid(), nullable=False),
    sa.Column('assignment_id', sa.Uuid(), nullable=True),
    sa.Column('structure_name', sa.String(length=100), nullable=False),
    sa.Column('year', sa.SmallInteger(), nullable=False),
    sa.Column('month', sa.SmallInteger(), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('proration_basis', _enum('proration_basis'), nullable=False),
    sa.Column('total_days', sa.SmallInteger(), nullable=False),
    sa.Column('working_days', sa.SmallInteger(), nullable=False),
    sa.Column('week_off_days', sa.SmallInteger(), nullable=False),
    sa.Column('holiday_days', sa.SmallInteger(), nullable=False),
    sa.Column('present_days', sa.SmallInteger(), nullable=False),
    sa.Column('half_days', sa.SmallInteger(), nullable=False),
    sa.Column('paid_leave_days', sa.Numeric(precision=5, scale=1), nullable=False),
    sa.Column('unpaid_leave_days', sa.Numeric(precision=5, scale=1), nullable=False),
    sa.Column('absent_days', sa.SmallInteger(), nullable=False),
    sa.Column('unmarked_days', sa.SmallInteger(), nullable=False),
    sa.Column('pre_joining_days', sa.SmallInteger(), nullable=False),
    sa.Column('lop_days', sa.Numeric(precision=5, scale=1), nullable=False),
    sa.Column('base_days', sa.SmallInteger(), nullable=False),
    sa.Column('payable_days', sa.Numeric(precision=5, scale=1), nullable=False),
    sa.Column('monthly_gross', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('gross_earnings', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('total_deductions', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('net_pay', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('status', _enum('salary_slip_status'), server_default='draft', nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('generated_by_id', sa.Uuid(), nullable=True),
    sa.Column('finalized_by_id', sa.Uuid(), nullable=True),
    sa.Column('finalized_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('payment_reference', sa.String(length=100), nullable=True),
    _id(),
    *_timestamps(),
    sa.CheckConstraint('month BETWEEN 1 AND 12', name='ck_salary_slip_month'),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['assignment_id'], ['employee_salary_assignments.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['generated_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['finalized_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('employee_id', 'year', 'month', name='uq_salary_slip_employee_month')
    )
    op.create_index(op.f('ix_salary_slips_employee_id'), 'salary_slips', ['employee_id'], unique=False)
    op.create_index(op.f('ix_salary_slips_year'), 'salary_slips', ['year'], unique=False)
    op.create_index(op.f('ix_salary_slips_month'), 'salary_slips', ['month'], unique=False)
    op.create_index(op.f('ix_salary_slips_status'), 'salary_slips', ['status'], unique=False)

    op.create_table('salary_slip_lines',
    sa.Column('slip_id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('component_type', _enum('salary_component_type'), nullable=False),
    sa.Column('is_prorated', sa.Boolean(), nullable=False),
    sa.Column('full_amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('sequence', sa.SmallInteger(), nullable=False),
    _id(),
    sa.ForeignKeyConstraint(['slip_id'], ['salary_slips.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_salary_slip_lines_slip_id'), 'salary_slip_lines', ['slip_id'], unique=False)

    # Block Supabase REST API (PostgREST) access; the app connects as table owner.
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    """Downgrade schema."""
    for table in reversed(TABLES):
        op.drop_table(table)  # drops its indexes too
    bind = op.get_bind()
    for name in ENUMS:
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
