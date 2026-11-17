"""Mapa mental de los temas de IA ya publicados (RF-17, CU-07)."""

import uuid

from fastapi import APIRouter, HTTPException, Request, status

from app.api import seguridad
from app.api.entregas import LIMITE_CONSULTAS, es_estudiante, negar_ajeno
from app.api.seguridad import Actual, Db, limitador, ruta
from app.esquemas import MapaMental, Rol
from app.informes.armar import armar_mapa
from app.modelos import Usuario

router = APIRouter()

NO_EXISTE = "Ese mapa no existe."


@ruta(router, "GET", "/api/mapa/{estudiante_id}", response_model=MapaMental)
@limitador.limit(LIMITE_CONSULTAS, key_func=seguridad.clave_de_usuario)
def ver_mapa(request: Request, estudiante_id: uuid.UUID, actual: Actual, db: Db) -> MapaMental:
    if es_estudiante(actual) and estudiante_id != actual.id:
        negar_ajeno(db, request, actual.id, "mapa", estudiante_id)
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_EXISTE)
    estudiante = db.get(Usuario, estudiante_id)
    if estudiante is None or estudiante.rol != Rol.ESTUDIANTE.value:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_EXISTE)
    return armar_mapa(db, estudiante.id)
