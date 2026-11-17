"""Cohortes, laboratorios y rúbricas con versiones (módulo rúbricas)

Revisión: 0002
Anterior: 0001
Fecha: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cohortes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("nombre", sa.String(length=80), nullable=False),
        sa.Column("periodo", sa.String(length=40), nullable=False),
        sa.Column("creado", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nombre", "periodo", name="uq_cohortes_nombre_periodo"),
    )

    op.create_table(
        "laboratorios",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("cohorte_id", sa.Uuid(), nullable=False),
        sa.Column("titulo", sa.String(length=160), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=False),
        sa.Column("objetivos", sa.Text(), nullable=False),
        sa.Column("temas_ia", sa.JSON(), nullable=False),
        sa.Column("creado", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["cohorte_id"], ["cohortes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_laboratorios_cohorte_id", "laboratorios", ["cohorte_id"], unique=False)

    op.create_table(
        "rubricas",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("laboratorio_id", sa.Uuid(), nullable=False),
        sa.Column("creado", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["laboratorio_id"], ["laboratorios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("laboratorio_id"),
    )

    op.create_table(
        "rubrica_versiones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rubrica_id", sa.Uuid(), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column("estructura", sa.JSON(), nullable=False),
        sa.Column("valida", sa.Boolean(), nullable=False),
        sa.Column("errores", sa.JSON(), nullable=False),
        sa.Column("origen", sa.String(length=10), nullable=False),
        sa.Column("archivo_sha256", sa.String(length=64), nullable=True),
        sa.Column("prompt_version", sa.String(length=60), nullable=True),
        sa.Column("modelo", sa.String(length=120), nullable=True),
        sa.Column("tokens_entrada", sa.Integer(), nullable=True),
        sa.Column("tokens_salida", sa.Integer(), nullable=True),
        sa.Column("creada_por", sa.Uuid(), nullable=False),
        sa.Column("fecha", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creada_por"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["rubrica_id"], ["rubricas.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rubrica_id", "numero", name="uq_rubrica_versiones_numero"),
    )
    op.create_index("ix_rubrica_versiones_rubrica_id", "rubrica_versiones", ["rubrica_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_rubrica_versiones_rubrica_id", table_name="rubrica_versiones")
    op.drop_table("rubrica_versiones")
    op.drop_table("rubricas")
    op.drop_index("ix_laboratorios_cohorte_id", table_name="laboratorios")
    op.drop_table("laboratorios")
    op.drop_table("cohortes")
