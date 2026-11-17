"""Configuración de Alembic. La dirección de la base sale de DATABASE_URL (app/config.py)."""

from alembic import context
from sqlalchemy import create_engine, pool

import app.modelos  # noqa: F401  (registra las tablas en Base.metadata)
from app.config import ajustes
from app.db import Base

target_metadata = Base.metadata


def _migrar(conexion) -> None:
    context.configure(connection=conexion, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def en_linea() -> None:
    # Las pruebas pasan su propia conexión; en uso normal se abre una con DATABASE_URL.
    conexion = context.config.attributes.get("connection")
    if conexion is not None:
        _migrar(conexion)
        return
    direccion = ajustes().database_url
    if not direccion:
        raise RuntimeError("Falta la variable DATABASE_URL.")
    motor = create_engine(direccion, poolclass=pool.NullPool)
    with motor.connect() as conexion:
        _migrar(conexion)


if context.is_offline_mode():
    raise RuntimeError("Las migraciones se corren conectadas a la base (sin --sql).")
en_linea()
