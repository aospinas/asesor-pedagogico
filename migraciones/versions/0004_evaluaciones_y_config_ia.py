"""Evaluaciones, criterios evaluados y configuración de IA (módulo evaluador)

Revisión: 0004
Anterior: 0003
Fecha: 2026-11-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evaluaciones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("entrega_id", sa.Uuid(), nullable=False),
        sa.Column("rubrica_version_id", sa.Uuid(), nullable=False),
        sa.Column("lanzada_por", sa.Uuid(), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column("proveedor", sa.String(length=20), nullable=False),
        sa.Column("modelo", sa.String(length=120), nullable=False),
        sa.Column("version_prompt", sa.String(length=60), nullable=False),
        sa.Column("nota_preliminar", sa.Float(), nullable=True),
        sa.Column("nota_final", sa.Float(), nullable=True),
        sa.Column("tokens_entrada", sa.Integer(), nullable=False),
        sa.Column("tokens_salida", sa.Integer(), nullable=False),
        sa.Column("costo_usd", sa.Float(), nullable=False),
        sa.Column("alerta_inyeccion", sa.Boolean(), nullable=False),
        sa.Column("reglas_inyeccion", sa.JSON(), nullable=False),
        sa.Column("aviso", sa.String(length=300), nullable=True),
        sa.Column("fecha", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actualizada", sa.DateTime(timezone=True), nullable=False),
        sa.Column("aprobada_por", sa.Uuid(), nullable=True),
        sa.Column("fecha_aprobacion", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fecha_publicacion", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["aprobada_por"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["entrega_id"], ["entregas.id"]),
        sa.ForeignKeyConstraint(["lanzada_por"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["rubrica_version_id"], ["rubrica_versiones.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evaluaciones_entrega_id", "evaluaciones", ["entrega_id"], unique=False)
    op.create_index("ix_evaluaciones_lanzada_por", "evaluaciones", ["lanzada_por"], unique=False)
    op.create_index("ix_evaluaciones_estado", "evaluaciones", ["estado"], unique=False)
    op.create_index("ix_evaluaciones_fecha", "evaluaciones", ["fecha"], unique=False)

    op.create_table(
        "evaluacion_criterios",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("evaluacion_id", sa.Uuid(), nullable=False),
        sa.Column("criterio_id", sa.String(length=40), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("nivel_ia", sa.String(length=40), nullable=True),
        sa.Column("nivel_final", sa.String(length=40), nullable=True),
        sa.Column("justificacion", sa.Text(), nullable=False),
        sa.Column("evidencias", sa.JSON(), nullable=False),
        sa.Column("fortalezas", sa.JSON(), nullable=False),
        sa.Column("debilidades", sa.JSON(), nullable=False),
        sa.Column("recomendaciones", sa.JSON(), nullable=False),
        sa.Column("intentos", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["evaluacion_id"], ["evaluaciones.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evaluacion_id", "criterio_id", name="uq_evaluacion_criterio"),
    )
    op.create_index(
        "ix_evaluacion_criterios_evaluacion_id", "evaluacion_criterios", ["evaluacion_id"], unique=False
    )

    op.create_table(
        "config_ia",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("proveedor", sa.String(length=20), nullable=False),
        sa.Column("modelo", sa.String(length=120), nullable=False),
        sa.Column("base_url", sa.String(length=300), nullable=False),
        sa.Column("precio_entrada_usd", sa.Float(), nullable=True),
        sa.Column("precio_salida_usd", sa.Float(), nullable=True),
        sa.Column("actualizado_por", sa.Uuid(), nullable=False),
        sa.Column("fecha", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actualizado_por"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_config_ia_fecha", "config_ia", ["fecha"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_config_ia_fecha", table_name="config_ia")
    op.drop_table("config_ia")
    op.drop_index("ix_evaluacion_criterios_evaluacion_id", table_name="evaluacion_criterios")
    op.drop_table("evaluacion_criterios")
    op.drop_index("ix_evaluaciones_fecha", table_name="evaluaciones")
    op.drop_index("ix_evaluaciones_estado", table_name="evaluaciones")
    op.drop_index("ix_evaluaciones_lanzada_por", table_name="evaluaciones")
    op.drop_index("ix_evaluaciones_entrega_id", table_name="evaluaciones")
    op.drop_table("evaluaciones")
