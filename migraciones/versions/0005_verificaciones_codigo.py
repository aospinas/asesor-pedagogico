"""Resultados del sandbox por evaluación (sandbox conectado al evaluador)

Revisión: 0005
Anterior: 0004
Fecha: 2026-11-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "verificaciones_codigo",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("evaluacion_id", sa.Uuid(), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("comando", sa.String(length=500), nullable=False),
        sa.Column("codigo_salida", sa.Integer(), nullable=True),
        sa.Column("salida", sa.Text(), nullable=False),
        sa.Column("duracion_ms", sa.Integer(), nullable=False),
        sa.Column("tiempo_agotado", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["evaluacion_id"], ["evaluaciones.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_verificaciones_codigo_evaluacion_id", "verificaciones_codigo", ["evaluacion_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_verificaciones_codigo_evaluacion_id", table_name="verificaciones_codigo")
    op.drop_table("verificaciones_codigo")
