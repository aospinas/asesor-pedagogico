"""Tablero del docente (D-24): métricas reales del curso, calculadas por el backend."""

from fastapi import APIRouter, Request

from app.api import seguridad
from app.api.seguridad import Actual, Db, limitador, ruta
from app.esquemas import MiTablero, Tablero
from app.informes import mi_tablero, tablero

router = APIRouter()


@ruta(router, "GET", "/api/mi-tablero", response_model=MiTablero)
@limitador.limit("20/minute", key_func=seguridad.clave_de_usuario)
def ver_mi_tablero(request: Request, actual: Actual, db: Db) -> MiTablero:
    """Siempre el del usuario de la sesión: no recibe id, así nadie pide el de otro (D-25)."""
    return mi_tablero.calcular(db, actual.id)


@ruta(router, "GET", "/api/tablero", response_model=Tablero)
@limitador.limit("20/minute", key_func=seguridad.clave_de_usuario)
def ver_tablero(request: Request, db: Db) -> Tablero:
    return tablero.calcular(db)
