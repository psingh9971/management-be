"""offer letters

Revision ID: c71d4e2a9f60
Revises: a3c9e5d17b42
Create Date: 2026-11-21 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c71d4e2a9f60'
down_revision: Union[str, Sequence[str], None] = 'a3c9e5d17b42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('offer_letters',
    sa.Column('letter_number', sa.String(length=30), nullable=False),
    sa.Column('employee_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Enum('provisional', 'confirmed', 'withdrawn', name='offer_letter_status'), server_default='provisional', nullable=False),
    sa.Column('candidate_name', sa.String(length=200), nullable=False),
    sa.Column('designation', sa.String(length=100), nullable=False),
    sa.Column('department', sa.String(length=100), nullable=True),
    sa.Column('work_location', sa.String(length=150), nullable=True),
    sa.Column('offer_date', sa.Date(), nullable=False),
    sa.Column('tentative_joining_date', sa.Date(), nullable=True),
    sa.Column('joining_date', sa.Date(), nullable=True),
    sa.Column('valid_until', sa.Date(), nullable=True),
    sa.Column('assignment_id', sa.Uuid(), nullable=True),
    sa.Column('structure_name', sa.String(length=100), nullable=False),
    sa.Column('monthly_gross', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('annual_gross', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('monthly_deductions', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('monthly_net', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('components', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('terms', sa.Text(), nullable=True),
    sa.Column('issued_by_id', sa.Uuid(), nullable=True),
    sa.Column('confirmed_by_id', sa.Uuid(), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('withdrawn_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('withdrawal_reason', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['assignment_id'], ['employee_salary_assignments.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['issued_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['confirmed_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('letter_number')
    )
    op.create_index(op.f('ix_offer_letters_employee_id'), 'offer_letters', ['employee_id'], unique=False)
    op.create_index(op.f('ix_offer_letters_status'), 'offer_letters', ['status'], unique=False)
    op.create_index('uq_offer_letters_single_active', 'offer_letters', ['employee_id'], unique=True,
                    postgresql_where=sa.text("status <> 'withdrawn'"))

    # Block Supabase REST API (PostgREST) access; the app connects as table owner.
    op.execute('ALTER TABLE "offer_letters" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('offer_letters')
    sa.Enum(name='offer_letter_status').drop(op.get_bind(), checkfirst=True)
