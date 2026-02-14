"""add xsd validation fields to esocial_submission

Revision ID: c8d4e5f6a7b8
Revises: be7f8a9b0c1d
Create Date: 2026-02-14 20:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c8d4e5f6a7b8"
down_revision = "be7f8a9b0c1d"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("esocial_submission", schema=None) as batch_op:
        batch_op.add_column(sa.Column("xsd_validation_status", sa.String(length=20), nullable=False, server_default="pending"))
        batch_op.add_column(sa.Column("xsd_validation_summary", sa.String(length=500), nullable=True))

    with op.batch_alter_table("esocial_submission", schema=None) as batch_op:
        batch_op.alter_column("xsd_validation_status", server_default=None)


def downgrade():
    with op.batch_alter_table("esocial_submission", schema=None) as batch_op:
        batch_op.drop_column("xsd_validation_summary")
        batch_op.drop_column("xsd_validation_status")
