"""Planes de fortalecimiento guardados por estudiante y huella de datos (módulo informe)

Revisión: 0007
Anterior: 0006
Fecha: 2026-11-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "planes_fortalecimiento",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("estudiante_id", sa.Uuid(), nullable=False),
        sa.Column("huella", sa.String(length=64), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("proveedor", sa.String(length=20), nullable=False),
        sa.Column("modelo", sa.String(length=120), nullable=False),
        sa.Column("version_prompt", sa.String(length=60), nullable=False),
        sa.Column("tokens_entrada", sa.Integer(), nullable=False),
        sa.Column("tokens_salida", sa.Integer(), nullable=False),
        sa.Column("costo_usd", sa.Float(), nullable=False),
        sa.Column("fecha", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["estudiante_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("estudiante_id", "huella", name="uq_plan_estudiante_huella"),
    )
    op.create_index(
        "ix_planes_fortalecimiento_estudiante_id", "planes_fortalecimiento", ["estudiante_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_planes_fortalecimiento_estudiante_id", table_name="planes_fortalecimiento")
    op.drop_table("planes_fortalecimiento")
