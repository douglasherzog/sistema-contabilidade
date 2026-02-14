"""competence close

Revision ID: 0f7e5a9b2c1a
Revises: 951536343444
Create Date: 2026-02-14 14:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0f7e5a9b2c1a"
down_revision = "951536343444"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "competence_close",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("year", "month", name="uq_competence_close_year_month"),
    )
    with op.batch_alter_table("competence_close", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_competence_close_year"), ["year"], unique=False)
        batch_op.create_index(batch_op.f("ix_competence_close_month"), ["month"], unique=False)


def downgrade():
    with op.batch_alter_table("competence_close", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_competence_close_month"))
        batch_op.drop_index(batch_op.f("ix_competence_close_year"))

    op.drop_table("competence_close")
