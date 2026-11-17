"""Informe integrado: verlo y descargarlo en PDF (RF-16, CU-06)."""

import logging
import uuid

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response

from app.api import seguridad
from app.api.entregas import LIMITE_CONSULTAS, es_estudiante, negar_ajeno
from app.api.seguridad import Actual, Db, limitador, ruta
from app.esquemas import Informe, Rol
from app.informes.armar import armar_informe, pdf_informe
from app.informes.plan import redactar_plan
from app.modelos import Usuario

router = APIRouter()
registro = logging.getLogger("asesor")

NO_EXISTE = "Ese informe no existe."
PDF_NO_DISPONIBLE = "No se pudo crear el PDF. Intenta de nuevo en un momento."


def _estudiante(db: Db, request: Request, actual: Actual, estudiante_id: uuid.UUID) -> Usuario:
    if es_estudiante(actual) and estudiante_id != actual.id:
        negar_ajeno(db, request, actual.id, "informe", estudiante_id)
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_EXISTE)
    estudiante = db.get(Usuario, estudiante_id)
    if estudiante is None or estudiante.rol != Rol.ESTUDIANTE.value:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_EXISTE)
    return estudiante


def _informe(db: Db, estudiante: Usuario) -> Informe:
    base = armar_informe(db, estudiante)
    return base.model_copy(update={"plan": redactar_plan(base)})


@ruta(router, "GET", "/api/informe/{estudiante_id}", response_model=Informe)
@limitador.limit(LIMITE_CONSULTAS, key_func=seguridad.clave_de_usuario)
def ver_informe(request: Request, estudiante_id: uuid.UUID, actual: Actual, db: Db) -> Informe:
    return _informe(db, _estudiante(db, request, actual, estudiante_id))


@ruta(router, "GET", "/api/informe/{estudiante_id}/pdf")
@limitador.limit("10/minute", key_func=seguridad.clave_de_usuario)
def descargar_informe(request: Request, estudiante_id: uuid.UUID, actual: Actual, db: Db) -> Response:
    informe = _informe(db, _estudiante(db, request, actual, estudiante_id))
    try:
        pdf = pdf_informe(informe)
    except (OSError, RuntimeError) as error:
        registro.error("No se pudo generar el PDF del informe: %s", type(error).__name__)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, PDF_NO_DISPONIBLE) from None
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="informe.pdf"'},
    )
