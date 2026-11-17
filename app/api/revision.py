"""Revisión del docente, traza y lo que ve el estudiante (RF-14, RF-15, RNF-08, RNF-09, CU-05).

La IA propone, el backend calcula, el docente aprueba:
- el docente cambia niveles (con justificación) y la nota se recalcula con `calcular_nota`;
- edita la retroalimentación, aprueba (se fija la nota final) y publica;
- solo lo publicado lo ve el estudiante, y solo lo suyo (lo ajeno responde 404).

Cada acción queda en `revisiones_docente` (la traza) y en la auditoría, en la misma
transacción. La fila de la evaluación se bloquea mientras se cambia: dos acciones a la vez
no se pisan (en PostgreSQL).
"""

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import select

from app.api import seguridad
from app.api.entregas import LISTA_POR_DEFECTO, Desde, Limite, es_estudiante, negar_ajeno
from app.api.evaluaciones import a_esquema, motivos, verificaciones_de
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
    EvidenciaArchivo,
    ProveedorIA,
    RevisionDocente,
    RubricaEstructura,
    TipoEvidencia,
    TrazaEvaluacion,
)
from app.esquemas import Evidencia as Cita
from app.evaluador import motor, revision
from app.modelos import Entrega, EvaluacionCriterio, Evidencia, RevisionDocenteFila, RubricaVersion
from app.modelos import Evaluacion as EvaluacionFila

router = APIRouter()

LIMITE_CAMBIOS = "60/minute"
LIMITE_CONSULTAS = "120/minute"

NO_EXISTE = "Esa evaluación no existe."
EN_PROCESO = "La evaluación todavía se está haciendo. Espera a que termine."
YA_APROBADA = "La evaluación ya fue aprobada: ya no se puede cambiar."
NO_EN_RUBRICA = "Ese criterio o ese nivel no está en la rúbrica de esta evaluación."
FALTAN_NIVELES = "Faltan niveles: califica a mano los criterios sin propuesta antes de aprobar."
SIN_APROBAR = "Primero hay que aprobar la evaluación."
YA_PUBLICADA = "La evaluación ya está publicada."

PENDIENTES = (EstadoEvaluacion.EN_REVISION.value, EstadoEvaluacion.REVISION_MANUAL.value)


# ---------- Ayudas ----------


def _bloquear(db: Db, evaluacion_id: uuid.UUID) -> EvaluacionFila:
    """La evaluación, con su fila bloqueada hasta el commit (en PostgreSQL)."""
    evaluacion = db.scalar(select(EvaluacionFila).where(EvaluacionFila.id == evaluacion_id).with_for_update())
    if evaluacion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_EXISTE)
    return evaluacion


def _se_puede_cambiar(evaluacion: EvaluacionFila) -> None:
    if evaluacion.estado == EstadoEvaluacion.EN_PROCESO.value:
        raise HTTPException(status.HTTP_409_CONFLICT, EN_PROCESO)
    if evaluacion.estado not in PENDIENTES:
        raise HTTPException(status.HTTP_409_CONFLICT, YA_APROBADA)


def _rubrica(db: Db, evaluacion: EvaluacionFila) -> RubricaEstructura:
    version = db.get(RubricaVersion, evaluacion.rubrica_version_id)
    return RubricaEstructura.model_validate(version.estructura)


def _criterio(rubrica: RubricaEstructura, criterio_id: str):
    criterio = next((c for c in rubrica.criterios if c.id == criterio_id), None)
    if criterio is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NO_EN_RUBRICA)
    return criterio


def _anotar(
    db: Db,
    request: Request,
    actual,
    evaluacion: EvaluacionFila,
    accion: AccionRevision,
    accion_auditoria: str,
    detalle: dict,
    *,
    criterio_id: str | None = None,
    anterior: str | None = None,
    nuevo: str | None = None,
    justificacion: str | None = None,
) -> None:
    """La traza (revisiones_docente) y la auditoría, en la misma transacción que el cambio."""
    db.add(
        RevisionDocenteFila(
            evaluacion_id=evaluacion.id,
            docente_id=actual.id,
            accion=accion.value,
            criterio_id=criterio_id,
            valor_anterior=anterior,
            valor_nuevo=nuevo,
            justificacion=justificacion,
        )
    )
    registrar(
        db,
        usuario_id=actual.id,
        accion=accion_auditoria,
        entidad="evaluacion",
        entidad_id=evaluacion.id,
        detalle=detalle,
        ip=seguridad.ip_de(request),
    )


def _retro(fila: EvaluacionCriterio) -> str:
    datos = {
        "fortalezas": fila.fortalezas,
        "debilidades": fila.debilidades,
        "recomendaciones": fila.recomendaciones,
    }
    return json.dumps(datos, ensure_ascii=False)


# ---------- Bandeja ----------


@ruta(router, "GET", "/api/evaluaciones", response_model=list[EvaluacionResumen])
@limitador.limit(LIMITE_CONSULTAS, key_func=seguridad.clave_de_usuario)
def bandeja(
    request: Request,
    db: Db,
    estado: Annotated[EstadoEvaluacion | None, Query(description="Sin estado: las pendientes")] = None,
    laboratorio_id: uuid.UUID | None = None,
    desde: Desde = 0,
    limite: Limite = LISTA_POR_DEFECTO,
) -> list[EvaluacionResumen]:
    """Primero las que tienen motivos (cita no encontrada, alerta de inyección, sin propuesta)."""
    motor.recuperar_colgadas(db)
    consulta = select(EvaluacionFila, Entrega.laboratorio_id, Entrega.estudiante_id).join(
        Entrega, Entrega.id == EvaluacionFila.entrega_id
    )
    if estado is None:
        consulta = consulta.where(EvaluacionFila.estado.in_(PENDIENTES))
    else:
        consulta = consulta.where(EvaluacionFila.estado == estado.value)
    if laboratorio_id is not None:
        consulta = consulta.where(Entrega.laboratorio_id == laboratorio_id)
    filas = db.execute(
        consulta.order_by(
            EvaluacionFila.prioridad.desc(), EvaluacionFila.fecha.desc(), EvaluacionFila.id.desc()
        )
        .offset(desde)
        .limit(limite)
    ).all()
    ids = [f[0].id for f in filas]
    rubricas: dict = {}  # cada versión de rúbrica se lee una sola vez por página
    criterios: dict[uuid.UUID, list[EvaluacionCriterio]] = {i: [] for i in ids}
    if ids:
        for c in db.scalars(select(EvaluacionCriterio).where(EvaluacionCriterio.evaluacion_id.in_(ids))):
            criterios[c.evaluacion_id].append(c)
    return [
        EvaluacionResumen(
            id=ev.id,
            entrega_id=ev.entrega_id,
            laboratorio_id=laboratorio,
            estudiante_id=estudiante,
            estado=EstadoEvaluacion(ev.estado),
            nota_preliminar=ev.nota_preliminar,
            motivos=motivos(db, ev, criterios[ev.id], rubricas),
            fecha=ev.fecha,
        )
        for ev, laboratorio, estudiante in filas
    ]


# ---------- Cambios del docente ----------


@ruta(router, "POST", "/api/evaluaciones/{evaluacion_id}/ajustes", response_model=Evaluacion)
@limitador.limit(LIMITE_CAMBIOS, key_func=seguridad.clave_de_usuario)
def ajustar_nivel(
    request: Request, evaluacion_id: uuid.UUID, datos: AjusteNivel, actual: Actual, db: Db
) -> Evaluacion:
    """Cambia el nivel de un criterio; la nota se recalcula sola (nunca se escribe a mano)."""
    evaluacion = _bloquear(db, evaluacion_id)
    _se_puede_cambiar(evaluacion)
    rubrica = _rubrica(db, evaluacion)
    criterio = _criterio(rubrica, datos.criterio_id)
    if datos.nivel_id not in {n.id for n in criterio.niveles}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NO_EN_RUBRICA)
    fila = revision.fila_del_criterio(db, evaluacion, rubrica, criterio)
    anterior = revision.nivel_efectivo(fila)
    fila.nivel_final = datos.nivel_id
    revision.recalcular(db, evaluacion, rubrica)
    _anotar(
        db,
        request,
        actual,
        evaluacion,
        AccionRevision.AJUSTAR_NIVEL,
        "evaluacion_ajustada",
        {"criterio_id": criterio.id, "anterior": anterior, "nuevo": datos.nivel_id},
        criterio_id=criterio.id,
        anterior=anterior,
        nuevo=datos.nivel_id,
        justificacion=datos.justificacion,
    )
    db.commit()
    return a_esquema(db, evaluacion)


@ruta(router, "PATCH", "/api/evaluaciones/{evaluacion_id}/retroalimentacion", response_model=Evaluacion)
@limitador.limit(LIMITE_CAMBIOS, key_func=seguridad.clave_de_usuario)
def editar_retroalimentacion(
    request: Request, evaluacion_id: uuid.UUID, datos: AjusteRetroalimentacion, actual: Actual, db: Db
) -> Evaluacion:
    evaluacion = _bloquear(db, evaluacion_id)
    _se_puede_cambiar(evaluacion)
    rubrica = _rubrica(db, evaluacion)
    criterio = _criterio(rubrica, datos.criterio_id)
    fila = revision.fila_del_criterio(db, evaluacion, rubrica, criterio)
    anterior = _retro(fila)
    fila.fortalezas = list(datos.fortalezas)
    fila.debilidades = list(datos.debilidades)
    fila.recomendaciones = list(datos.recomendaciones)
    evaluacion.actualizada = seguridad.ahora()
    _anotar(
        db,
        request,
        actual,
        evaluacion,
        AccionRevision.EDITAR_RETROALIMENTACION,
        "retroalimentacion_editada",
        {"criterio_id": criterio.id, "anterior": json.loads(anterior), "nuevo": json.loads(_retro(fila))},
        criterio_id=criterio.id,
        anterior=anterior,
        nuevo=_retro(fila),
    )
    db.commit()
    return a_esquema(db, evaluacion)


@ruta(router, "POST", "/api/evaluaciones/{evaluacion_id}/aprobar", response_model=Evaluacion)
@limitador.limit(LIMITE_CAMBIOS, key_func=seguridad.clave_de_usuario)
def aprobar(request: Request, evaluacion_id: uuid.UUID, actual: Actual, db: Db) -> Evaluacion:
    """Fija la nota final con los niveles finales. Desde aquí ya no se cambia nada."""
    evaluacion = _bloquear(db, evaluacion_id)
    _se_puede_cambiar(evaluacion)
    rubrica = _rubrica(db, evaluacion)
    niveles = revision.niveles_efectivos(db, evaluacion, rubrica)
    nota = revision.nota_con(rubrica, niveles)
    if evaluacion.estado != EstadoEvaluacion.EN_REVISION.value or nota is None:
        raise HTTPException(status.HTTP_409_CONFLICT, FALTAN_NIVELES)
    for criterio in rubrica.criterios:  # el nivel que vale queda escrito en cada criterio
        revision.fila_del_criterio(db, evaluacion, rubrica, criterio).nivel_final = niveles[criterio.id]
    ahora = seguridad.ahora()
    evaluacion.nota_preliminar = nota
    evaluacion.nota_final = nota
    evaluacion.estado = EstadoEvaluacion.APROBADA.value
    evaluacion.aprobada_por = actual.id
    evaluacion.fecha_aprobacion = ahora
    evaluacion.actualizada = ahora
    _anotar(
        db,
        request,
        actual,
        evaluacion,
        AccionRevision.APROBAR,
        "evaluacion_aprobada",
        {"nota_final": nota},
        nuevo=str(nota),
    )
    db.commit()
    return a_esquema(db, evaluacion)


@ruta(router, "POST", "/api/evaluaciones/{evaluacion_id}/publicar", response_model=Evaluacion)
@limitador.limit(LIMITE_CAMBIOS, key_func=seguridad.clave_de_usuario)
def publicar(request: Request, evaluacion_id: uuid.UUID, actual: Actual, db: Db) -> Evaluacion:
    """Desde aquí la ve el estudiante (RNF-09)."""
    evaluacion = _bloquear(db, evaluacion_id)
    if evaluacion.estado == EstadoEvaluacion.PUBLICADA.value:
        raise HTTPException(status.HTTP_409_CONFLICT, YA_PUBLICADA)
    if evaluacion.estado != EstadoEvaluacion.APROBADA.value:
        raise HTTPException(status.HTTP_409_CONFLICT, SIN_APROBAR)
    ahora = seguridad.ahora()
    evaluacion.estado = EstadoEvaluacion.PUBLICADA.value
    evaluacion.fecha_publicacion = ahora
    evaluacion.actualizada = ahora
    _anotar(db, request, actual, evaluacion, AccionRevision.PUBLICAR, "evaluacion_publicada", {})
    db.commit()
    return a_esquema(db, evaluacion)


# ---------- Traza (RF-15, RNF-08) ----------


@ruta(router, "GET", "/api/evaluaciones/{evaluacion_id}/traza", response_model=TrazaEvaluacion)
@limitador.limit(LIMITE_CONSULTAS, key_func=seguridad.clave_de_usuario)
def ver_traza(request: Request, evaluacion_id: uuid.UUID, db: Db) -> TrazaEvaluacion:
    evaluacion = db.get(EvaluacionFila, evaluacion_id)
    if evaluacion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_EXISTE)
    # Sin texto_extraido (columna diferida, puede pesar megas): solo lo que pide la traza
    evidencias = db.execute(
        select(
            Evidencia.id,
            Evidencia.entrega_id,
            Evidencia.tipo,
            Evidencia.nombre,
            Evidencia.sha256,
            Evidencia.tamano_bytes,
            Evidencia.resumen,
        )
        .where(Evidencia.entrega_id == evaluacion.entrega_id)
        .order_by(Evidencia.fecha, Evidencia.id)
    ).all()
    revisiones = db.scalars(
        select(RevisionDocenteFila)
        .where(RevisionDocenteFila.evaluacion_id == evaluacion.id)
        .order_by(RevisionDocenteFila.fecha, RevisionDocenteFila.id)
    )
    return TrazaEvaluacion(
        evaluacion_id=evaluacion.id,
        rubrica_version_id=evaluacion.rubrica_version_id,
        proveedor=ProveedorIA(evaluacion.proveedor),
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
        verificaciones=verificaciones_de(db, evaluacion),
        tokens_entrada=evaluacion.tokens_entrada,
        tokens_salida=evaluacion.tokens_salida,
        alerta_inyeccion=evaluacion.alerta_inyeccion,
        fecha=evaluacion.fecha,
        aprobada_por=evaluacion.aprobada_por,
        fecha_aprobacion=evaluacion.fecha_aprobacion,
        fecha_publicacion=evaluacion.fecha_publicacion,
        revisiones=[
            RevisionDocente(
                id=r.id,
                evaluacion_id=r.evaluacion_id,
                docente_id=r.docente_id,
                accion=AccionRevision(r.accion),
                criterio_id=r.criterio_id,
                valor_anterior=r.valor_anterior,
                valor_nuevo=r.valor_nuevo,
                justificacion=r.justificacion,
                fecha=r.fecha,
            )
            for r in revisiones
        ],
    )


# ---------- Lo que ve el estudiante (RNF-09) ----------


@ruta(router, "GET", "/api/evaluaciones/{evaluacion_id}/publicada", response_model=EvaluacionPublicada)
@limitador.limit(LIMITE_CONSULTAS, key_func=seguridad.clave_de_usuario)
def ver_publicada(request: Request, evaluacion_id: uuid.UUID, actual: Actual, db: Db) -> EvaluacionPublicada:
    """Solo la versión final y aprobada: sin borradores de la IA, citas no encontradas, alerta de
    inyección, sandbox ni costos. NO reusa a_esquema (que trae todo eso)."""
    evaluacion = db.get(EvaluacionFila, evaluacion_id)
    if evaluacion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_EXISTE)
    entrega = db.get(Entrega, evaluacion.entrega_id)
    if es_estudiante(actual) and entrega.estudiante_id != actual.id:
        negar_ajeno(db, request, actual.id, "evaluacion", evaluacion_id)
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_EXISTE)
    if evaluacion.estado != EstadoEvaluacion.PUBLICADA.value or evaluacion.nota_final is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_EXISTE)  # igual que si no existiera

    # La justificación que ve el estudiante: la del docente si cambió el nivel (la de la IA
    # defendía otro nivel); si no, la de la IA.
    ajustes = db.scalars(
        select(RevisionDocenteFila)
        .where(
            RevisionDocenteFila.evaluacion_id == evaluacion.id,
            RevisionDocenteFila.accion == AccionRevision.AJUSTAR_NIVEL.value,
        )
        .order_by(RevisionDocenteFila.fecha, RevisionDocenteFila.id)
    )
    del_docente = {a.criterio_id: a.justificacion for a in ajustes}
    filas = db.scalars(
        select(EvaluacionCriterio)
        .where(EvaluacionCriterio.evaluacion_id == evaluacion.id)
        .order_by(EvaluacionCriterio.orden)
    )
    return EvaluacionPublicada(
        id=evaluacion.id,
        entrega_id=evaluacion.entrega_id,
        laboratorio_id=entrega.laboratorio_id,
        nota_final=evaluacion.nota_final,
        criterios=[
            CriterioPublicado(
                criterio_id=f.criterio_id,
                nivel_id=f.nivel_final,
                justificacion=del_docente.get(f.criterio_id) or f.justificacion,
                # Solo las citas que se encontraron en el material (LLM09)
                evidencias=[
                    Cita(archivo=e["archivo"], ubicacion=e["ubicacion"], fragmento=e["fragmento"])
                    for e in f.evidencias
                    if e.get("encontrada") is True
                    and all(e.get(k) for k in ("archivo", "ubicacion", "fragmento"))
                ],
                fortalezas=f.fortalezas,
                debilidades=f.debilidades,
                recomendaciones=f.recomendaciones,
            )
            for f in filas
        ],
        fecha_publicacion=evaluacion.fecha_publicacion,
    )
