"""Informe integrado y mapa mental (RF-16, RF-17, CU-06, CU-07; D-22).

- El estudiante solo ve lo suyo (lo ajeno responde 404 y queda en la auditoría); el docente,
  el de cualquier estudiante. Solo cuentan evaluaciones publicadas (RNF-09).
- Los números los calcula el backend (app/informes/calculo.py); la IA solo redacta el plan,
  que se guarda y solo se vuelve a pedir si cambian los datos (app/informes/plan.py).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api import seguridad
from app.api.entregas import es_estudiante, negar_ajeno
from app.api.seguridad import Actual, Db, limitador, ruta
from app.esquemas import Informe, MapaMental, Rol
from app.ia import cliente
from app.ia.cliente import ErrorIA
from app.informes import calculo, mapa, pdf, plan
from app.modelos import Usuario

router = APIRouter()

NO_EXISTE = "Ese estudiante no existe."
LIMITE_CONSULTAS = "20/minute"
LIMITE_PDF = "5/minute"


def obtener_plan_ia(db: Db):
    """(pedir_json, config) para redactar el plan, o (None, None) si la IA no está configurada:
    el informe sale igual, sin plan. Las pruebas cambian esta dependencia."""
    try:
        return cliente.pedir_json, cliente.configuracion(db)
    except ErrorIA:
        return None, None


PlanIA = Annotated[tuple, Depends(obtener_plan_ia)]


def _estudiante_visible(db: Db, request: Request, actual, estudiante_id: uuid.UUID) -> Usuario:
    if es_estudiante(actual) and estudiante_id != actual.id:
        negar_ajeno(db, request, actual.id, "informe", estudiante_id)
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_EXISTE)
    estudiante = db.get(Usuario, estudiante_id)
    if estudiante is None or estudiante.rol != Rol.ESTUDIANTE.value:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_EXISTE)
    return estudiante


def _armar(db: Db, estudiante: Usuario, plan_ia: tuple, *, generar: bool) -> tuple[Informe, calculo.Datos]:
    """`generar`: solo el informe le pide el plan a la IA; el mapa y el PDF usan el guardado."""
    datos = calculo.calcular(db, estudiante.id)
    pedir, config = plan_ia
    redactado = plan.obtener(db, estudiante.id, datos, pedir, config, generar=generar)
    informe = Informe(
        estudiante_id=estudiante.id,
        nombre_estudiante=estudiante.nombre,
        laboratorios=datos.laboratorios,
        promedio_general=datos.promedio_general,
        cohortes=datos.cohortes,
        competencias=datos.competencias,
        temas=datos.temas,
        brechas=datos.brechas,
        plan=redactado,
        generado=seguridad.ahora(),
    )
    return informe, datos


@ruta(router, "GET", "/api/informe/{estudiante_id}", response_model=Informe)
@limitador.limit(LIMITE_CONSULTAS, key_func=seguridad.clave_de_usuario)
def ver_informe(
    request: Request, estudiante_id: uuid.UUID, actual: Actual, db: Db, plan_ia: PlanIA
) -> Informe:
    estudiante = _estudiante_visible(db, request, actual, estudiante_id)
    return _armar(db, estudiante, plan_ia, generar=True)[0]


@ruta(router, "GET", "/api/informe/{estudiante_id}/pdf")
@limitador.limit(LIMITE_PDF, key_func=seguridad.clave_de_usuario)
def descargar_informe(
    request: Request, estudiante_id: uuid.UUID, actual: Actual, db: Db, plan_ia: PlanIA
) -> Response:
    estudiante = _estudiante_visible(db, request, actual, estudiante_id)
    if not pdf.disponible():  # antes de armar nada: así no se gasta nada si no se puede
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, pdf.NO_DISPONIBLE)
    informe, _ = _armar(db, estudiante, plan_ia, generar=False)
    try:
        contenido = pdf.generar(informe)
    except pdf.PDFNoDisponible as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from None
    return Response(
        content=contenido,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="informe-integrado.pdf"'},
    )


@ruta(router, "GET", "/api/mapa/{estudiante_id}", response_model=MapaMental)
@limitador.limit(LIMITE_CONSULTAS, key_func=seguridad.clave_de_usuario)
def ver_mapa(
    request: Request, estudiante_id: uuid.UUID, actual: Actual, db: Db, plan_ia: PlanIA
) -> MapaMental:
    estudiante = _estudiante_visible(db, request, actual, estudiante_id)
    informe, datos = _armar(db, estudiante, plan_ia, generar=False)
    return mapa.armar(estudiante.id, datos, informe.plan)
