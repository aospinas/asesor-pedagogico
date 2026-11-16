"""Las migraciones crean exactamente las tablas de app/modelos.py."""

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.db import Base

RAIZ = Path(__file__).parent.parent


def configuracion(conexion) -> Config:
    config = Config(str(RAIZ / "alembic.ini"))
    config.set_main_option("script_location", str(RAIZ / "migraciones"))
    config.attributes["connection"] = conexion
    return config


def test_la_migracion_deja_la_base_igual_a_los_modelos():
    motor = create_engine("sqlite+pysqlite:///:memory:")
    with motor.connect() as conexion:
        command.upgrade(configuracion(conexion), "head")
        assert set(inspect(conexion).get_table_names()) >= {"usuarios", "intentos_sesion", "auditoria"}
        diferencias = compare_metadata(MigrationContext.configure(conexion), Base.metadata)
        assert diferencias == [], "Falta una migración: alembic revision --autogenerate"


def test_la_migracion_se_puede_deshacer():
    motor = create_engine("sqlite+pysqlite:///:memory:")
    with motor.connect() as conexion:
        command.upgrade(configuracion(conexion), "head")
        command.downgrade(configuracion(conexion), "base")
        assert set(inspect(conexion).get_table_names()) <= {"alembic_version"}
