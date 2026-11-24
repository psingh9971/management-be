"""tenant domain (subdomain)

Existing tenants get their slug as the domain, so the initial JPenterprises tenant gets
'jpenterprises'.

Revision ID: f1b3d9a6c2e4
Revises: e5a2c7f3b8d1
Create Date: 2026-11-24 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1b3d9a6c2e4'
down_revision: Union[str, Sequence[str], None] = 'e5a2c7f3b8d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('tenants', sa.Column('domain', sa.String(length=63), nullable=True))
    op.execute("UPDATE tenants SET domain = slug")
    op.alter_column('tenants', 'domain', nullable=False)
    op.create_index(op.f('ix_tenants_domain'), 'tenants', ['domain'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_tenants_domain'), table_name='tenants')
    op.drop_column('tenants', 'domain')
