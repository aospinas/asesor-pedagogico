"""Revisión del docente: tabla revisiones_docente y prioridad en la bandeja (módulo revisión)

Revisión: 0006
Anterior: 0005
Fecha: 2026-11-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "revisiones_docente",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("evaluacion_id", sa.Uuid(), nullable=False),
        sa.Column("docente_id", sa.Uuid(), nullable=False),
        sa.Column("accion", sa.String(length=30), nullable=False),
        sa.Column("criterio_id", sa.String(length=40), nullable=True),
        sa.Column("valor_anterior", sa.Text(), nullable=True),
        sa.Column("valor_nuevo", sa.Text(), nullable=True),
        sa.Column("justificacion", sa.Text(), nullable=True),
        sa.Column("fecha", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["docente_id"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["evaluacion_id"], ["evaluaciones.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_revisiones_docente_evaluacion_id", "revisiones_docente", ["evaluacion_id"], unique=False
    )
    # Las evaluaciones que ya existen quedan con prioridad 0; se recalcula al ajustarlas.
    op.add_column("evaluaciones", sa.Column("prioridad", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_evaluaciones_prioridad", "evaluaciones", ["prioridad"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_evaluaciones_prioridad", table_name="evaluaciones")
    op.drop_column("evaluaciones", "prioridad")
    op.drop_index("ix_revisiones_docente_evaluacion_id", table_name="revisiones_docente")
    op.drop_table("revisiones_docente")
