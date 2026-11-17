"""Entregas y evidencias (módulo entregas)

Revisión: 0003
Anterior: 0002
Fecha: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "entregas",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("estudiante_id", sa.Uuid(), nullable=False),
        sa.Column("laboratorio_id", sa.Uuid(), nullable=False),
        sa.Column("rubrica_version_id", sa.Uuid(), nullable=False),
        sa.Column("enlace_github", sa.String(length=200), nullable=True),
        sa.Column("sha256_informe", sa.String(length=64), nullable=False),
        sa.Column("fecha", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["estudiante_id"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["laboratorio_id"], ["laboratorios.id"]),
        sa.ForeignKeyConstraint(["rubrica_version_id"], ["rubrica_versiones.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("estudiante_id", "laboratorio_id", "sha256_informe", name="uq_entregas_informe"),
    )
    op.create_index("ix_entregas_estudiante_id", "entregas", ["estudiante_id"], unique=False)
    op.create_index("ix_entregas_laboratorio_id", "entregas", ["laboratorio_id"], unique=False)
    op.create_index("ix_entregas_fecha", "entregas", ["fecha"], unique=False)

    op.create_table(
        "evidencias",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("entrega_id", sa.Uuid(), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("nombre", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("tamano_bytes", sa.Integer(), nullable=False),
        sa.Column("tipo_mime", sa.String(length=100), nullable=False),
        sa.Column("ruta_storage", sa.String(length=300), nullable=False),
        sa.Column("texto_extraido", sa.JSON(), nullable=True),
        sa.Column("resumen", sa.String(length=300), nullable=True),
        sa.Column("fecha", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["entrega_id"], ["entregas.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidencias_entrega_id", "evidencias", ["entrega_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_evidencias_entrega_id", table_name="evidencias")
    op.drop_table("evidencias")
    op.drop_index("ix_entregas_fecha", table_name="entregas")
    op.drop_index("ix_entregas_laboratorio_id", table_name="entregas")
    op.drop_index("ix_entregas_estudiante_id", table_name="entregas")
    op.drop_table("entregas")
