"""Revisión docente: ajustar, aprobar, publicar y ver la traza (RF-14, RF-15, CU-05).

La nota no se escribe a mano: cada cambio de nivel vuelve a pasar por
`calcular_nota`. El estudiante solo ve la evaluación cuando está publicada.
"""

import uuid

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import seguridad
from app.api.entregas import LIMITE_CONSULTAS, es_estudiante, negar_ajeno
from app.api.evaluaciones import NO_EXISTE, a_esquema, motivos
from app.api.seguridad import Actual, Db, limitador, ruta
from app.auditoria.registro import registrar
from app.esquemas import (
    AccionRevision,
    AjusteNivel,
    AjusteRetroalimentacion,
    CriterioPublicado,
    EstadoEvaluacion,
    Evaluacion,
    EvaluacionPublicada,
    EvaluacionResumen,
    Evidencia,
    EvidenciaArchivo,
    RevisionDocente,
    RubricaEstructura,
    TipoEvidencia,
    TipoVerificacion,
    TrazaEvaluacion,
    VerificacionCodigo,
)
from app.evaluador.nota import ErrorDeNota, calcular_nota
from app.modelos import Auditoria, Entrega, EvaluacionCriterio, RubricaVersion, VerificacionCodigoFila
from app.modelos import Evaluacion as EvaluacionFila
from app.modelos import Evidencia as EvidenciaFila

router = APIRouter()

EN_PROCESO = "La evaluación todavía está en proceso."
YA_CERRADA = "Esta evaluación ya no se puede cambiar."
YA_APROBADA = "Esta evaluación ya está aprobada."
YA_PUBLICADA = "Esta evaluación ya está publicada."
FALTA_NIVEL = "Falta el nivel de un criterio. Elige uno antes de aprobar."
ANTES_DE_PUBLICAR = "Aprueba la evaluación antes de publicarla."
CRITERIO_NO = "Ese criterio no está en esta evaluación."
NIVEL_NO = "Ese nivel no existe en ese criterio."

_ABIERTAS = {EstadoEvaluacion.EN_REVISION.value, EstadoEvaluacion.REVISION_MANUAL.value}
_EN_BANDEJA = _ABIERTAS | {EstadoEvaluacion.APROBADA.value}
_ACCIONES = {accion.value for accion in AccionRevision}


def _bloquear(db: Session, evaluacion_id: uuid.UUID) -> EvaluacionFila:
    fila = db.scalar(select(EvaluacionFila).where(EvaluacionFila.id == evaluacion_id).with_for_update())
    if fila is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_EXISTE)
    return fila


def _criterios(db: Session, evaluacion_id: uuid.UUID) -> list[EvaluacionCriterio]:
    return list(
        db.scalars(
            select(EvaluacionCriterio)
            .where(EvaluacionCriterio.evaluacion_id == evaluacion_id)
            .order_by(EvaluacionCriterio.orden, EvaluacionCriterio.id)
        )
    )


def _rubrica(db: Session, evaluacion: EvaluacionFila) -> RubricaEstructura:
    version = db.get(RubricaVersion, evaluacion.rubrica_version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_EXISTE)
    return RubricaEstructura.model_validate(version.estructura)


def _exigir_abierta(evaluacion: EvaluacionFila) -> None:
    if evaluacion.estado == EstadoEvaluacion.EN_PROCESO.value:
        raise HTTPException(status.HTTP_409_CONFLICT, EN_PROCESO)
    if evaluacion.estado == EstadoEvaluacion.APROBADA.value:
        raise HTTPException(status.HTTP_409_CONFLICT, YA_APROBADA)
    if evaluacion.estado == EstadoEvaluacion.PUBLICADA.value:
        raise HTTPException(status.HTTP_409_CONFLICT, YA_PUBLICADA)
    if evaluacion.estado not in _ABIERTAS:
        raise HTTPException(status.HTTP_409_CONFLICT, YA_CERRADA)


def _fila_criterio(criterios: list[EvaluacionCriterio], criterio_id: str) -> EvaluacionCriterio:
    fila = next((c for c in criterios if c.criterio_id == criterio_id), None)
    if fila is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, CRITERIO_NO)
    return fila


def _recalcular(db: Session, evaluacion: EvaluacionFila, criterios: list[EvaluacionCriterio]) -> None:
    """Pone la nota final si todos los criterios tienen nivel. Si falta uno, queda en revisión manual."""
    rubrica = _rubrica(db, evaluacion)
    elegidos: dict[str, str] = {}
    for criterio in criterios:
        nivel = criterio.nivel_final or criterio.nivel_ia
        if not nivel:
            evaluacion.nota_final = None
            evaluacion.estado = EstadoEvaluacion.REVISION_MANUAL.value
            evaluacion.actualizada = seguridad.ahora()
            return
        elegidos[criterio.criterio_id] = nivel
    try:
        evaluacion.nota_final = calcular_nota(rubrica, elegidos)
    except ErrorDeNota:
        evaluacion.nota_final = None
        evaluacion.estado = EstadoEvaluacion.REVISION_MANUAL.value
        evaluacion.actualizada = seguridad.ahora()
        return
    if evaluacion.estado == EstadoEvaluacion.REVISION_MANUAL.value:
        evaluacion.estado = EstadoEvaluacion.EN_REVISION.value
    evaluacion.actualizada = seguridad.ahora()


def _anotar(
    db: Session,
    request: Request,
    actual: Actual,
    evaluacion: EvaluacionFila,
    accion: AccionRevision,
    *,
    criterio_id: str | None = None,
    valor_anterior: str | None = None,
    valor_nuevo: str | None = None,
    justificacion: str | None = None,
) -> None:
    registrar(
        db,
        usuario_id=actual.id,
        accion=accion.value,
        entidad="evaluacion",
        entidad_id=evaluacion.id,
        detalle={
            "criterio_id": criterio_id,
            "valor_anterior": valor_anterior,
            "valor_nuevo": valor_nuevo,
            "justificacion": justificacion,
        },
        ip=seguridad.ip_de(request),
    )


def _cadena(valor: object) -> str | None:
    return valor if isinstance(valor, str) else None


def _revisiones(db: Session, evaluacion_id: uuid.UUID) -> list[RevisionDocente]:
    filas = db.scalars(
        select(Auditoria)
        .where(
            Auditoria.entidad == "evaluacion",
            Auditoria.entidad_id == str(evaluacion_id),
            Auditoria.accion.in_(_ACCIONES),
        )
        .order_by(Auditoria.fecha, Auditoria.id)
    )
    lista = []
    for fila in filas:
        if fila.usuario_id is None:
            continue
        detalle = fila.detalle or {}
        lista.append(
            RevisionDocente(
                id=fila.id,
                evaluacion_id=evaluacion_id,
                docente_id=fila.usuario_id,
                accion=AccionRevision(fila.accion),
                criterio_id=_cadena(detalle.get("criterio_id")),
                valor_anterior=_cadena(detalle.get("valor_anterior")),
                valor_nuevo=_cadena(detalle.get("valor_nuevo")),
                justificacion=_cadena(detalle.get("justificacion")),
                fecha=seguridad.con_zona(fila.fecha),
            )
        )
    return lista


@ruta(router, "GET", "/api/evaluaciones", response_model=list[EvaluacionResumen])
@limitador.limit(LIMITE_CONSULTAS, key_func=seguridad.clave_de_usuario)
def bandeja(
    request: Request,
    db: Db,
    desde: int = Query(default=0, ge=0),
    limite: int = Query(default=50, ge=1, le=100),
) -> list[EvaluacionResumen]:
    """Evaluaciones que el docente todavía tiene que revisar o publicar. Las urgentes van primero."""
    del request
    filas = db.execute(
        select(EvaluacionFila, Entrega)
        .join(Entrega, Entrega.id == EvaluacionFila.entrega_id)
        .where(EvaluacionFila.estado.in_(_EN_BANDEJA))
    ).all()
    ids = [evaluacion.id for evaluacion, _entrega in filas]
    por_evaluacion: dict[uuid.UUID, list[EvaluacionCriterio]] = {i: [] for i in ids}
    if ids:
        for criterio in db.scalars(
            select(EvaluacionCriterio).where(EvaluacionCriterio.evaluacion_id.in_(ids))
        ):
            por_evaluacion[criterio.evaluacion_id].append(criterio)

    def orden(par: tuple[EvaluacionFila, Entrega]) -> tuple:
        evaluacion, _entrega = par
        criterios = por_evaluacion[evaluacion.id]
        urgente = 0 if motivos(evaluacion, criterios) else 1
        pendiente = 0 if evaluacion.estado != EstadoEvaluacion.APROBADA.value else 1
        fecha = seguridad.con_zona(evaluacion.fecha)
        return (urgente, pendiente, -fecha.timestamp(), str(evaluacion.id))

    pagina = sorted(filas, key=orden)[desde : desde + limite]
    return [
        EvaluacionResumen(
            id=evaluacion.id,
            entrega_id=evaluacion.entrega_id,
            laboratorio_id=entrega.laboratorio_id,
            estudiante_id=entrega.estudiante_id,
            estado=EstadoEvaluacion(evaluacion.estado),
            nota_preliminar=evaluacion.nota_preliminar,
            motivos=motivos(evaluacion, por_evaluacion[evaluacion.id]),
            fecha=seguridad.con_zona(evaluacion.fecha),
        )
        for evaluacion, entrega in pagina
    ]


@ruta(router, "POST", "/api/evaluaciones/{evaluacion_id}/ajustes", response_model=Evaluacion)
@limitador.limit("30/minute", key_func=seguridad.clave_de_usuario)
def ajustar_nivel(
    request: Request,
    evaluacion_id: uuid.UUID,
    datos: AjusteNivel,
    actual: Actual,
    db: Db,
) -> Evaluacion:
    evaluacion = _bloquear(db, evaluacion_id)
    _exigir_abierta(evaluacion)
    rubrica = _rubrica(db, evaluacion)
    de_la_rubrica = next((c for c in rubrica.criterios if c.id == datos.criterio_id), None)
    if de_la_rubrica is None or not any(n.id == datos.nivel_id for n in de_la_rubrica.niveles):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            CRITERIO_NO if de_la_rubrica is None else NIVEL_NO,
        )
    criterios = _criterios(db, evaluacion.id)
    fila = _fila_criterio(criterios, datos.criterio_id)
    anterior = fila.nivel_final or fila.nivel_ia
    fila.nivel_final = datos.nivel_id
    fila.justificacion = datos.justificacion
    _recalcular(db, evaluacion, criterios)
    _anotar(
        db,
        request,
        actual,
        evaluacion,
        AccionRevision.AJUSTAR_NIVEL,
        criterio_id=datos.criterio_id,
        valor_anterior=anterior,
        valor_nuevo=datos.nivel_id,
        justificacion=datos.justificacion,
    )
    db.commit()
    return a_esquema(db, evaluacion)


@ruta(
    router,
    "PATCH",
    "/api/evaluaciones/{evaluacion_id}/retroalimentacion",
    response_model=Evaluacion,
)
@limitador.limit("30/minute", key_func=seguridad.clave_de_usuario)
def editar_retroalimentacion(
    request: Request,
    evaluacion_id: uuid.UUID,
    datos: AjusteRetroalimentacion,
    actual: Actual,
    db: Db,
) -> Evaluacion:
    evaluacion = _bloquear(db, evaluacion_id)
    _exigir_abierta(evaluacion)
    criterios = _criterios(db, evaluacion.id)
    fila = _fila_criterio(criterios, datos.criterio_id)
    anterior = " | ".join([*fila.fortalezas, *fila.debilidades, *fila.recomendaciones])[:2000]
    fila.fortalezas = datos.fortalezas
    fila.debilidades = datos.debilidades
    fila.recomendaciones = datos.recomendaciones
    nuevo = " | ".join([*datos.fortalezas, *datos.debilidades, *datos.recomendaciones])[:2000]
    evaluacion.actualizada = seguridad.ahora()
    _anotar(
        db,
        request,
        actual,
        evaluacion,
        AccionRevision.EDITAR_RETROALIMENTACION,
        criterio_id=datos.criterio_id,
        valor_anterior=anterior or None,
        valor_nuevo=nuevo or None,
    )
    db.commit()
    return a_esquema(db, evaluacion)


@ruta(router, "POST", "/api/evaluaciones/{evaluacion_id}/aprobar", response_model=Evaluacion)
@limitador.limit("30/minute", key_func=seguridad.clave_de_usuario)
def aprobar(request: Request, evaluacion_id: uuid.UUID, actual: Actual, db: Db) -> Evaluacion:
    evaluacion = _bloquear(db, evaluacion_id)
    _exigir_abierta(evaluacion)
    criterios = _criterios(db, evaluacion.id)
    if any((c.nivel_final or c.nivel_ia) is None for c in criterios):
        raise HTTPException(status.HTTP_409_CONFLICT, FALTA_NIVEL)
    for criterio in criterios:
        if criterio.nivel_final is None:
            criterio.nivel_final = criterio.nivel_ia
    anterior = evaluacion.estado
    _recalcular(db, evaluacion, criterios)
    if evaluacion.nota_final is None:
        raise HTTPException(status.HTTP_409_CONFLICT, FALTA_NIVEL)
    evaluacion.estado = EstadoEvaluacion.APROBADA.value
    evaluacion.aprobada_por = actual.id
    evaluacion.fecha_aprobacion = seguridad.ahora()
    evaluacion.actualizada = evaluacion.fecha_aprobacion
    _anotar(
        db,
        request,
        actual,
        evaluacion,
        AccionRevision.APROBAR,
        valor_anterior=anterior,
        valor_nuevo=EstadoEvaluacion.APROBADA.value,
    )
    db.commit()
    return a_esquema(db, evaluacion)


@ruta(router, "POST", "/api/evaluaciones/{evaluacion_id}/publicar", response_model=Evaluacion)
@limitador.limit("30/minute", key_func=seguridad.clave_de_usuario)
def publicar(request: Request, evaluacion_id: uuid.UUID, actual: Actual, db: Db) -> Evaluacion:
    evaluacion = _bloquear(db, evaluacion_id)
    if evaluacion.estado == EstadoEvaluacion.PUBLICADA.value:
        raise HTTPException(status.HTTP_409_CONFLICT, YA_PUBLICADA)
    if evaluacion.estado != EstadoEvaluacion.APROBADA.value:
        raise HTTPException(status.HTTP_409_CONFLICT, ANTES_DE_PUBLICAR)
    if evaluacion.nota_final is None:
        raise HTTPException(status.HTTP_409_CONFLICT, FALTA_NIVEL)
    evaluacion.estado = EstadoEvaluacion.PUBLICADA.value
    evaluacion.fecha_publicacion = seguridad.ahora()
    evaluacion.actualizada = evaluacion.fecha_publicacion
    _anotar(
        db,
        request,
        actual,
        evaluacion,
        AccionRevision.PUBLICAR,
        valor_anterior=EstadoEvaluacion.APROBADA.value,
        valor_nuevo=EstadoEvaluacion.PUBLICADA.value,
    )
    db.commit()
    return a_esquema(db, evaluacion)


@ruta(router, "GET", "/api/evaluaciones/{evaluacion_id}/traza", response_model=TrazaEvaluacion)
@limitador.limit(LIMITE_CONSULTAS, key_func=seguridad.clave_de_usuario)
def ver_traza(request: Request, evaluacion_id: uuid.UUID, db: Db) -> TrazaEvaluacion:
    del request
    evaluacion = db.get(EvaluacionFila, evaluacion_id)
    if evaluacion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_EXISTE)
    evidencias = db.scalars(
        select(EvidenciaFila)
        .where(EvidenciaFila.entrega_id == evaluacion.entrega_id)
        .order_by(EvidenciaFila.id)
    )
    verificaciones = db.scalars(
        select(VerificacionCodigoFila)
        .where(VerificacionCodigoFila.evaluacion_id == evaluacion.id)
        .order_by(VerificacionCodigoFila.orden)
    )
    return TrazaEvaluacion(
        evaluacion_id=evaluacion.id,
        rubrica_version_id=evaluacion.rubrica_version_id,
        proveedor=evaluacion.proveedor,
        modelo=evaluacion.modelo,
        version_prompt=evaluacion.version_prompt,
        evidencias=[
            EvidenciaArchivo(
                id=e.id,
                entrega_id=e.entrega_id,
                tipo=TipoEvidencia(e.tipo),
                nombre=e.nombre,
                sha256=e.sha256,
                tamano_bytes=e.tamano_bytes,
                resumen=e.resumen,
            )
            for e in evidencias
        ],
        verificaciones=[
            VerificacionCodigo(
                tipo=TipoVerificacion(v.tipo),
                comando=v.comando,
                codigo_salida=v.codigo_salida,
                salida=v.salida,
                duracion_ms=v.duracion_ms,
                tiempo_agotado=v.tiempo_agotado,
            )
            for v in verificaciones
        ],
        tokens_entrada=evaluacion.tokens_entrada,
        tokens_salida=evaluacion.tokens_salida,
        alerta_inyeccion=evaluacion.alerta_inyeccion,
        fecha=seguridad.con_zona(evaluacion.fecha),
        aprobada_por=evaluacion.aprobada_por,
        fecha_aprobacion=seguridad.con_zona(evaluacion.fecha_aprobacion),
        fecha_publicacion=seguridad.con_zona(evaluacion.fecha_publicacion),
        revisiones=_revisiones(db, evaluacion.id),
    )


def _cita(dato: dict) -> Evidencia | None:
    try:
        return Evidencia.model_validate(
            {
                "archivo": dato.get("archivo"),
                "ubicacion": dato.get("ubicacion"),
                "fragmento": dato.get("fragmento"),
            }
        )
    except ValueError:
        return None


@ruta(
    router,
    "GET",
    "/api/evaluaciones/{evaluacion_id}/publicada",
    response_model=EvaluacionPublicada,
)
@limitador.limit(LIMITE_CONSULTAS, key_func=seguridad.clave_de_usuario)
def ver_publicada(request: Request, evaluacion_id: uuid.UUID, actual: Actual, db: Db) -> EvaluacionPublicada:
    evaluacion = db.get(EvaluacionFila, evaluacion_id)
    entrega = db.get(Entrega, evaluacion.entrega_id) if evaluacion is not None else None
    if evaluacion is None or entrega is None or evaluacion.estado != EstadoEvaluacion.PUBLICADA.value:
        if es_estudiante(actual) and entrega is not None and entrega.estudiante_id != actual.id:
            negar_ajeno(db, request, actual.id, "evaluacion", evaluacion_id)
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_EXISTE)
    if es_estudiante(actual) and entrega.estudiante_id != actual.id:
        negar_ajeno(db, request, actual.id, "evaluacion", evaluacion_id)
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_EXISTE)
    if evaluacion.nota_final is None or evaluacion.fecha_publicacion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_EXISTE)
    criterios = _criterios(db, evaluacion.id)
    publicados = []
    for criterio in criterios:
        nivel = criterio.nivel_final or criterio.nivel_ia
        if not nivel:
            raise HTTPException(status.HTTP_404_NOT_FOUND, NO_EXISTE)
        citas = [cita for dato in criterio.evidencias if (cita := _cita(dato)) is not None]
        publicados.append(
            CriterioPublicado(
                criterio_id=criterio.criterio_id,
                nivel_id=nivel,
                justificacion=criterio.justificacion,
                evidencias=citas,
                fortalezas=criterio.fortalezas,
                debilidades=criterio.debilidades,
                recomendaciones=criterio.recomendaciones,
            )
        )
    return EvaluacionPublicada(
        id=evaluacion.id,
        entrega_id=evaluacion.entrega_id,
        laboratorio_id=entrega.laboratorio_id,
        nota_final=evaluacion.nota_final,
        criterios=publicados,
        fecha_publicacion=seguridad.con_zona(evaluacion.fecha_publicacion),
    )
