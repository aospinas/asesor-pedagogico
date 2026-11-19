"""Tablero del docente (D-24): métricas reales del curso, calculadas por el backend."""

from fastapi import APIRouter, Request

from app.api import seguridad
from app.api.seguridad import Db, limitador, ruta
from app.esquemas import Tablero
from app.informes import tablero

router = APIRouter()


@ruta(router, "GET", "/api/tablero", response_model=Tablero)
@limitador.limit("20/minute", key_func=seguridad.clave_de_usuario)
def ver_tablero(request: Request, db: Db) -> Tablero:
    return tablero.calcular(db)
