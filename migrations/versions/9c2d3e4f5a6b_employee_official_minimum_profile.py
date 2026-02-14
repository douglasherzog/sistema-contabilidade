"""employee official minimum profile

Revision ID: 9c2d3e4f5a6b
Revises: 8b1c2d3e4f6a
Create Date: 2026-02-14 18:10:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9c2d3e4f5a6b"
down_revision = "8b1c2d3e4f6a"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("employee", schema=None) as batch_op:
        batch_op.add_column(sa.Column("birth_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("role_title", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("pis", sa.String(length=20), nullable=True))


def downgrade():
    with op.batch_alter_table("employee", schema=None) as batch_op:
        batch_op.drop_column("pis")
        batch_op.drop_column("role_title")
        batch_op.drop_column("birth_date")
