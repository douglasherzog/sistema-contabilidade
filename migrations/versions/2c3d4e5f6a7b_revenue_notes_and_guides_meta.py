"""revenue notes and guides metadata without PDF

Revision ID: 2c3d4e5f6a7b
Revises: 0f7e5a9b2c1a
Create Date: 2026-02-14 15:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2c3d4e5f6a7b"
down_revision = "0f7e5a9b2c1a"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("guide_document", schema=None) as batch_op:
        batch_op.alter_column("filename", existing_type=sa.String(length=255), nullable=True)

    op.create_table(
        "revenue_note",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("issued_at", sa.Date(), nullable=True),
        sa.Column("customer_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("revenue_note", schema=None) as batch_op:
        batch_op.create_index("ix_revenue_note_year", ["year"], unique=False)
        batch_op.create_index("ix_revenue_note_month", ["month"], unique=False)
        batch_op.create_index("ix_revenue_note_year_month", ["year", "month"], unique=False)


def downgrade():
    with op.batch_alter_table("revenue_note", schema=None) as batch_op:
        batch_op.drop_index("ix_revenue_note_year_month")
        batch_op.drop_index("ix_revenue_note_month")
        batch_op.drop_index("ix_revenue_note_year")

    op.drop_table("revenue_note")

    with op.batch_alter_table("guide_document", schema=None) as batch_op:
        batch_op.alter_column("filename", existing_type=sa.String(length=255), nullable=False)
