"""termination notice and fgts fields

Revision ID: 7e9f0a1b2c3d
Revises: 6c8d9e0f1a2b
Create Date: 2026-02-14 15:55:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7e9f0a1b2c3d"
down_revision = "6c8d9e0f1a2b"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("employee_termination", schema=None) as batch_op:
        batch_op.add_column(sa.Column("notice_type", sa.String(length=20), nullable=False, server_default="none"))
        batch_op.add_column(sa.Column("notice_days", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("fgts_balance_est", sa.Numeric(precision=12, scale=2), nullable=True))
        batch_op.add_column(sa.Column("fgts_fine_rate", sa.Numeric(precision=8, scale=4), nullable=True))
        batch_op.add_column(sa.Column("fgts_fine_est", sa.Numeric(precision=12, scale=2), nullable=True))

    with op.batch_alter_table("employee_termination", schema=None) as batch_op:
        batch_op.alter_column("notice_type", server_default=None)
        batch_op.alter_column("notice_days", server_default=None)


def downgrade():
    with op.batch_alter_table("employee_termination", schema=None) as batch_op:
        batch_op.drop_column("fgts_fine_est")
        batch_op.drop_column("fgts_fine_rate")
        batch_op.drop_column("fgts_balance_est")
        batch_op.drop_column("notice_days")
        batch_op.drop_column("notice_type")
