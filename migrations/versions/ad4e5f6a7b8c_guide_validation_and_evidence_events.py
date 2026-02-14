"""guide validation and evidence events

Revision ID: ad4e5f6a7b8c
Revises: 9c2d3e4f5a6b
Create Date: 2026-02-14 18:45:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "ad4e5f6a7b8c"
down_revision = "9c2d3e4f5a6b"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("guide_document", schema=None) as batch_op:
        batch_op.add_column(sa.Column("validation_status", sa.String(length=20), nullable=False, server_default="pending"))
        batch_op.add_column(sa.Column("validation_summary", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("validation_checked_at", sa.DateTime(), nullable=True))

    with op.batch_alter_table("guide_document", schema=None) as batch_op:
        batch_op.alter_column("validation_status", server_default=None)

    op.create_table(
        "compliance_evidence_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("entity_type", sa.String(length=30), nullable=False),
        sa.Column("entity_key", sa.String(length=80), nullable=True),
        sa.Column("actor_email", sa.String(length=255), nullable=True),
        sa.Column("details", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("compliance_evidence_event", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_compliance_evidence_event_year"), ["year"], unique=False)
        batch_op.create_index(batch_op.f("ix_compliance_evidence_event_month"), ["month"], unique=False)
        batch_op.create_index(batch_op.f("ix_compliance_evidence_event_event_type"), ["event_type"], unique=False)


def downgrade():
    with op.batch_alter_table("compliance_evidence_event", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_compliance_evidence_event_event_type"))
        batch_op.drop_index(batch_op.f("ix_compliance_evidence_event_month"))
        batch_op.drop_index(batch_op.f("ix_compliance_evidence_event_year"))
    op.drop_table("compliance_evidence_event")

    with op.batch_alter_table("guide_document", schema=None) as batch_op:
        batch_op.drop_column("validation_checked_at")
        batch_op.drop_column("validation_summary")
        batch_op.drop_column("validation_status")
