"""Usuarios, intentos de sesión y auditoría (módulo auth)

Revisión: 0001
Anterior: ninguna
Fecha: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usuarios",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("correo", sa.String(length=254), nullable=False),
        sa.Column("hash_contrasena", sa.String(length=100), nullable=False),
        sa.Column("rol", sa.String(length=20), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column("foto_url", sa.String(length=500), nullable=True),
        sa.Column("debe_cambiar_contrasena", sa.Boolean(), nullable=False),
        sa.Column("version_sesion", sa.Integer(), nullable=False),
        sa.Column("creado", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usuarios_correo", "usuarios", ["correo"], unique=True)

    op.create_table(
        "intentos_sesion",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("correo", sa.String(length=254), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=False),
        sa.Column("intentos", sa.Integer(), nullable=False),
        sa.Column("bloqueado_hasta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actualizado", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("correo", "ip", name="uq_intentos_sesion_correo_ip"),
    )
    op.create_index("ix_intentos_sesion_actualizado", "intentos_sesion", ["actualizado"], unique=False)

    op.create_table(
        "auditoria",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("usuario_id", sa.Uuid(), nullable=True),
        sa.Column("accion", sa.String(length=60), nullable=False),
        sa.Column("entidad", sa.String(length=60), nullable=False),
        sa.Column("entidad_id", sa.String(length=60), nullable=True),
        sa.Column("detalle", sa.JSON(), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("fecha", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auditoria_usuario_id", "auditoria", ["usuario_id"], unique=False)
    op.create_index("ix_auditoria_fecha", "auditoria", ["fecha"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_auditoria_fecha", table_name="auditoria")
    op.drop_index("ix_auditoria_usuario_id", table_name="auditoria")
    op.drop_table("auditoria")
    op.drop_index("ix_intentos_sesion_actualizado", table_name="intentos_sesion")
    op.drop_table("intentos_sesion")
    op.drop_index("ix_usuarios_correo", table_name="usuarios")
    op.drop_table("usuarios")
