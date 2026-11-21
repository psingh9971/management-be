"""employee soft delete

Revision ID: d4f8a1b9e3c2
Revises: c71d4e2a9f60
Create Date: 2026-11-21 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4f8a1b9e3c2'
down_revision: Union[str, Sequence[str], None] = 'c71d4e2a9f60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('employees', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_employees_deleted_at'), 'employees', ['deleted_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_employees_deleted_at'), table_name='employees')
    op.drop_column('employees', 'deleted_at')
