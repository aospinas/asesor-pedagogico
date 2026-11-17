"""Conexión a la base de datos.

La conexión se abre la primera vez que se usa, no al importar la app: así
`/salud` responde aunque la base se duerma o se pause con la app ya arriba.
(Al arrancar el contenedor sí se necesita la base, para las migraciones: ver D-14.)
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

from app.config import ajustes


class Base(DeclarativeBase):
    pass


class BaseNoDisponible(RuntimeError):
    """La base de datos no está configurada."""


@lru_cache
def motor() -> Engine:
    direccion = ajustes().database_url
    if not direccion:
        raise BaseNoDisponible("Falta la variable DATABASE_URL.")
    # hide_parameters: si una consulta falla, los datos (por ejemplo el hash de una
    # contraseña) no quedan escritos en los registros del servidor.
    # connect_timeout: si la base no contesta, se sabe en 10 s y no se queda esperando (por
    # ejemplo al apagar el servidor, cuando el evaluador cierra lo que quedó en cola; D-19).
    extra = {"connect_args": {"connect_timeout": 10}} if direccion.startswith("postgresql") else {}
    return create_engine(direccion, pool_pre_ping=True, hide_parameters=True, **extra)


def obtener_db() -> Iterator[Session]:
    with Session(motor(), expire_on_commit=False) as sesion:
        yield sesion
