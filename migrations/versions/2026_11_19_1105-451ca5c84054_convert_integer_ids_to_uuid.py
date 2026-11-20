"""convert integer ids to uuid

Converts every integer primary key (and the employee_id foreign keys that point
at employees.id) to UUID in place, preserving existing rows and relationships.
New ids default to gen_random_uuid().

Revision ID: 451ca5c84054
Revises: 2c4c7b28be1d
Create Date: 2026-11-19 11:05:00

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '451ca5c84054'
down_revision: Union[str, Sequence[str], None] = '2c4c7b28be1d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PARENT = 'employees'
# Tables with an employee_id FK -> employees.id
CHILDREN = (
    'employee_bank_details',
    'employee_aadhaar_cards',
    'employee_pan_cards',
    'attendance_punches',
)
# One-to-one tables: employee_id is unique
ONE_TO_ONE = ('employee_bank_details', 'employee_aadhaar_cards', 'employee_pan_cards')
ALL_TABLES = (PARENT, 'users') + CHILDREN


def upgrade() -> None:
    # 1. New UUID id on every table. Adding a column with a volatile default
    #    gives each existing row its own random UUID.
    for t in ALL_TABLES:
        op.execute(f'ALTER TABLE "{t}" ADD COLUMN new_id uuid NOT NULL DEFAULT gen_random_uuid()')

    # 2. Map each child's integer employee_id to the employee's new UUID.
    for t in CHILDREN:
        op.execute(f'ALTER TABLE "{t}" ADD COLUMN new_employee_id uuid')
        op.execute(
            f'UPDATE "{t}" c SET new_employee_id = e.new_id '
            f'FROM "{PARENT}" e WHERE c.employee_id = e.id'
        )
        op.execute(f'ALTER TABLE "{t}" ALTER COLUMN new_employee_id SET NOT NULL')

    # 3. Drop the FKs so the old integer columns can go.
    for t in CHILDREN:
        op.execute(f'ALTER TABLE "{t}" DROP CONSTRAINT IF EXISTS "{t}_employee_id_fkey"')

    # 4. Swap employee_id columns (dropping the old column also drops its unique
    #    constraints and indexes; they are recreated below).
    for t in CHILDREN:
        op.execute(f'ALTER TABLE "{t}" DROP COLUMN employee_id')
        op.execute(f'ALTER TABLE "{t}" RENAME COLUMN new_employee_id TO employee_id')

    # 5. Swap primary keys (dropping the old column also drops its sequence).
    for t in ALL_TABLES:
        op.execute(f'ALTER TABLE "{t}" DROP COLUMN id')
        op.execute(f'ALTER TABLE "{t}" RENAME COLUMN new_id TO id')
        op.execute(f'ALTER TABLE "{t}" ADD CONSTRAINT "{t}_pkey" PRIMARY KEY (id)')

    # 6. Recreate FKs, unique constraints and indexes on employee_id.
    for t in CHILDREN:
        op.execute(
            f'ALTER TABLE "{t}" ADD CONSTRAINT "{t}_employee_id_fkey" '
            f'FOREIGN KEY (employee_id) REFERENCES "{PARENT}"(id) ON DELETE CASCADE'
        )
    for t in ONE_TO_ONE:
        op.execute(f'ALTER TABLE "{t}" ADD CONSTRAINT "{t}_employee_id_key" UNIQUE (employee_id)')
    op.execute(
        'ALTER TABLE attendance_punches ADD CONSTRAINT uq_punch_employee_time_device '
        'UNIQUE (employee_id, punch_time, device_id)'
    )
    op.create_index('ix_attendance_punches_employee_id', 'attendance_punches', ['employee_id'])


def downgrade() -> None:
    # The original integer ids are not retained, so this cannot be reversed faithfully.
    raise NotImplementedError("UUID -> integer id conversion is irreversible; restore from a backup instead")
