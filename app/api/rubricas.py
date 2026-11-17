"""Rúbrica de un laboratorio: cargar, corregir y ver versiones (RF-04, RF-05, RF-06)."""

import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import func, select

from app.api import seguridad
from app.api.laboratorios import buscar_laboratorio
from app.api.seguridad import Actual, Db, ruta
from app.auditoria.registro import registrar
from app.esquemas import OrigenRubrica, Rol, RubricaEstructura, RubricaPublica, RubricaVersion
from app.ia import cliente
from app.ia.cliente import ErrorIA
from app.mensajes import explicar
from app.modelos import Auditoria
from app.rubricas import extraer, interpretar, versiones

router = APIRouter()

SIN_RUBRICA = "Este laboratorio todavía no tiene rúbrica."
SIN_RUBRICA_LISTA = "Este laboratorio todavía no tiene una rúbrica lista."
IA_NO_CONFIGURADA = "La IA no está configurada. Mientras tanto, sube la rúbrica en JSON."
IA_FALLO = "La IA no pudo convertir la rúbrica. Intenta de nuevo o súbela en JSON."
VERSION_OCUPADA = "Otra persona guardó la rúbrica al mismo tiempo. Recarga e intenta de nuevo."

# OWASP LLM10: cada conversión gasta tokens. Se cuentan los pedidos a la IA de la última hora.
CONVERSIONES_POR_HORA = 10
MUCHAS_CONVERSIONES = (
    f"Ya convertiste {CONVERSIONES_POR_HORA} rúbricas con IA en la última hora. Espera un rato."
)


def obtener_ia() -> interpretar.PedirJson:
    """La función que habla con la IA. Las pruebas la cambian por una simulada."""
    return cliente.pedir_json


IA = Annotated[interpretar.PedirJson, Depends(obtener_ia)]


def _conversiones_recientes(db: Db, usuario_id: uuid.UUID) -> int:
    desde = seguridad.ahora() - timedelta(hours=1)
    return db.scalar(
        select(func.count())
        .select_from(Auditoria)
        .where(
            Auditoria.usuario_id == usuario_id,
            Auditoria.accion == "rubrica_ia_pedida",
            Auditoria.fecha >= desde,
        )
    )


@ruta(
    router,
    "GET",
    "/api/laboratorios/{laboratorio_id}/rubrica",
    response_model=RubricaVersion | RubricaPublica,
)
def ver_rubrica(laboratorio_id: uuid.UUID, actual: Actual, db: Db) -> RubricaVersion | RubricaPublica:
    buscar_laboratorio(db, laboratorio_id)
    if actual.rol == Rol.ESTUDIANTE.value:
        # El estudiante no ve borradores: solo la última versión válida y confirmada.
        version = versiones.ultima_lista(db, laboratorio_id)
        if version is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, SIN_RUBRICA_LISTA)
        return versiones.a_publica(version)
    version = versiones.vigente(db, laboratorio_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, SIN_RUBRICA)
    return versiones.a_esquema(version)


def _guardar(db: Db, laboratorio_id: uuid.UUID, estructura: RubricaEstructura, **datos):
    try:
        return versiones.guardar_version(db, laboratorio_id, estructura, **datos)
    except versiones.VersionOcupada:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, VERSION_OCUPADA) from None


@ruta(
    router,
    "POST",
    "/api/laboratorios/{laboratorio_id}/rubrica",
    response_model=RubricaVersion,
    status_code=status.HTTP_201_CREATED,
)
def cargar_rubrica(
    request: Request,
    laboratorio_id: uuid.UUID,
    actual: Actual,
    db: Db,
    ia: IA,
    archivo: Annotated[UploadFile, File(description="PDF, Word (.docx), texto o JSON")],
):
    usuario_id = actual.id
    ip = seguridad.ip_de(request)
    buscar_laboratorio(db, laboratorio_id)
    try:
        extraido = extraer.extraer_texto(archivo.file.read(extraer.MAXIMO_BYTES + 1))
    except extraer.ArchivoMuyGrande as error:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(error)) from None
    except extraer.ArchivoNoValido as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from None

    uso = None
    prompt_version = None
    if extraido.origen == OrigenRubrica.JSON:
        try:
            estructura = RubricaEstructura.model_validate_json(extraido.texto)
        except ValidationError as error:
            # Misma forma que los demás errores de datos (app/main.py)
            return JSONResponse(
                {
                    "detail": "El JSON no tiene el formato de una rúbrica.",
                    "errores": [explicar(e) for e in error.errors()][:20],
                },
                status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
    else:
        try:
            extraer.revisar_largo(extraido.texto)
        except extraer.RubricaMuyLarga as error:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from None
        if ia is cliente.pedir_json:  # sin IA configurada no se cuenta el intento: se avisa de una vez
            try:
                cliente.configuracion()
            except ErrorIA:
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, IA_NO_CONFIGURADA) from None
        if _conversiones_recientes(db, usuario_id) >= CONVERSIONES_POR_HORA:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, MUCHAS_CONVERSIONES)
        # Se anota el pedido y se cierra la transacción ANTES de esperar a la IA (hasta
        # un minuto): así no se queda ocupada una conexión de la base mientras tanto.
        registrar(
            db,
            usuario_id=usuario_id,
            accion="rubrica_ia_pedida",
            entidad="laboratorio",
            entidad_id=laboratorio_id,
            detalle={"origen": extraido.origen.value, "sha256": extraido.sha256},
            ip=ip,
        )
        db.commit()
        try:
            estructura, uso = interpretar.interpretar(extraido.texto, ia)
        except ErrorIA as error:
            if not error.configurada:
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, IA_NO_CONFIGURADA) from None
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, IA_FALLO) from None
        prompt_version = interpretar.VERSION_PROMPT

    version = _guardar(
        db,
        laboratorio_id,
        estructura,
        origen=extraido.origen,
        creada_por=usuario_id,
        archivo_sha256=extraido.sha256,
        prompt_version=prompt_version,
        uso=uso,
    )
    registrar(
        db,
        usuario_id=usuario_id,
        accion="rubrica_cargada",
        entidad="rubrica_version",
        entidad_id=version.id,
        detalle={
            "laboratorio_id": str(laboratorio_id),
            "numero": version.numero,
            "origen": version.origen,
            "valida": version.valida,
            "sha256": extraido.sha256,
            "prompt_version": prompt_version,
            "modelo": uso.modelo if uso else None,
            "tokens_entrada": uso.entrada if uso else None,
            "tokens_salida": uso.salida if uso else None,
        },
        ip=ip,
    )
    db.commit()
    return versiones.a_esquema(version)


@ruta(
    router,
    "PUT",
    "/api/laboratorios/{laboratorio_id}/rubrica",
    response_model=RubricaVersion,
    status_code=status.HTTP_201_CREATED,
)
def corregir_rubrica(
    request: Request, laboratorio_id: uuid.UUID, estructura: RubricaEstructura, actual: Actual, db: Db
) -> RubricaVersion:
    """El editor manda la rúbrica completa revisada: se guarda como versión nueva y confirmada."""
    buscar_laboratorio(db, laboratorio_id)
    version = _guardar(db, laboratorio_id, estructura, origen=OrigenRubrica.EDITOR, creada_por=actual.id)
    registrar(
        db,
        usuario_id=actual.id,
        accion="rubrica_corregida",
        entidad="rubrica_version",
        entidad_id=version.id,
        detalle={"laboratorio_id": str(laboratorio_id), "numero": version.numero, "valida": version.valida},
        ip=seguridad.ip_de(request),
    )
    db.commit()
    return versiones.a_esquema(version)


@ruta(
    router,
    "GET",
    "/api/laboratorios/{laboratorio_id}/rubrica/versiones",
    response_model=list[RubricaVersion],
)
def listar_versiones(laboratorio_id: uuid.UUID, db: Db) -> list[RubricaVersion]:
    buscar_laboratorio(db, laboratorio_id)
    return [versiones.a_esquema(v) for v in versiones.todas(db, laboratorio_id)]
