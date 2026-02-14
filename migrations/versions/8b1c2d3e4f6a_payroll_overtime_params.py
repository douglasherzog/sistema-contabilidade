"""payroll overtime params

Revision ID: 8b1c2d3e4f6a
Revises: 7e9f0a1b2c3d
Create Date: 2026-02-14 16:10:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8b1c2d3e4f6a"
down_revision = "7e9f0a1b2c3d"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("payroll_run", schema=None) as batch_op:
        batch_op.add_column(sa.Column("overtime_weekly_hours", sa.Numeric(precision=8, scale=2), nullable=False, server_default="44"))
        batch_op.add_column(sa.Column("overtime_additional_pct", sa.Numeric(precision=8, scale=2), nullable=False, server_default="50"))

    with op.batch_alter_table("payroll_run", schema=None) as batch_op:
        batch_op.alter_column("overtime_weekly_hours", server_default=None)
        batch_op.alter_column("overtime_additional_pct", server_default=None)


def downgrade():
    with op.batch_alter_table("payroll_run", schema=None) as batch_op:
        batch_op.drop_column("overtime_additional_pct")
        batch_op.drop_column("overtime_weekly_hours")
