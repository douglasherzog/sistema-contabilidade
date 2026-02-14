"""company official profile and esocial submission

Revision ID: be7f8a9b0c1d
Revises: ad4e5f6a7b8c
Create Date: 2026-02-14 19:05:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "be7f8a9b0c1d"
down_revision = "ad4e5f6a7b8c"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("company", schema=None) as batch_op:
        batch_op.add_column(sa.Column("tax_regime", sa.String(length=20), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("esocial_classification", sa.String(length=10), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("company_size", sa.String(length=20), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("payroll_tax_relief", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("state_registration", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("municipal_registration", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("responsible_name", sa.String(length=255), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("responsible_cpf", sa.String(length=20), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("responsible_email", sa.String(length=255), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("responsible_phone", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("establishment_cnpj", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("establishment_cnae", sa.String(length=20), nullable=True))

    with op.batch_alter_table("company", schema=None) as batch_op:
        batch_op.alter_column("tax_regime", server_default=None)
        batch_op.alter_column("esocial_classification", server_default=None)
        batch_op.alter_column("company_size", server_default=None)
        batch_op.alter_column("payroll_tax_relief", server_default=None)
        batch_op.alter_column("responsible_name", server_default=None)
        batch_op.alter_column("responsible_cpf", server_default=None)
        batch_op.alter_column("responsible_email", server_default=None)

    op.create_table(
        "esocial_submission",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("xml_filename", sa.String(length=255), nullable=False),
        sa.Column("protocol", sa.String(length=120), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("actor_email", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("esocial_submission", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_esocial_submission_event_type"), ["event_type"], unique=False)


def downgrade():
    with op.batch_alter_table("esocial_submission", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_esocial_submission_event_type"))
    op.drop_table("esocial_submission")

    with op.batch_alter_table("company", schema=None) as batch_op:
        batch_op.drop_column("establishment_cnae")
        batch_op.drop_column("establishment_cnpj")
        batch_op.drop_column("responsible_phone")
        batch_op.drop_column("responsible_email")
        batch_op.drop_column("responsible_cpf")
        batch_op.drop_column("responsible_name")
        batch_op.drop_column("municipal_registration")
        batch_op.drop_column("state_registration")
        batch_op.drop_column("payroll_tax_relief")
        batch_op.drop_column("company_size")
        batch_op.drop_column("esocial_classification")
        batch_op.drop_column("tax_regime")
