"""Lanzar una evaluación con IA y verla (RF-11 a RF-13, CU-04). Solo el docente.

La evaluación corre en segundo plano (app/evaluador/motor.py): esta ruta la crea en estado
"En proceso" y responde enseguida (202). El docente la vuelve a pedir para ver el avance.
"""

import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import seguridad
from app.api.entregas import AlmacenDep
from app.api.seguridad import Actual, Db, limitador, ruta
from app.auditoria.registro import registrar
from app.db import motor as motor_db
from app.esquemas import (
    ConfigIA,
    CriterioEvaluado,
    EstadoEvaluacion,
    Evaluacion,
    EvidenciaVerificada,
    MotivoPrioridad,
    ProveedorIA,
    TipoVerificacion,
    VerificacionCodigo,
)
from app.evaluador import github, motor, revision
from app.ia import cliente
from app.ia.cliente import ErrorIA
from app.modelos import Entrega, EvaluacionCriterio, VerificacionCodigoFila
from app.modelos import Evaluacion as EvaluacionFila

router = APIRouter()

EVALUACIONES_POR_HORA = 20
LIMITE_POR_MINUTO = "10/minute"

NO_EXISTE = "Esa evaluación no existe."
ENTREGA_NO_EXISTE = "Esa entrega no existe."
YA_EN_PROCESO = "Esta entrega ya se está evaluando. Espera a que termine."
MUCHAS = f"Ya lanzaste {EVALUACIONES_POR_HORA} evaluaciones en la última hora. Espera un rato."
IA_NO_CONFIGURADA = "La IA no está configurada. Pídele al administrador que la configure."
COLA_LLENA = "Hay muchas evaluaciones esperando turno. Intenta de nuevo en unos minutos."
MUCHAS_EN_COLA = f"Ya tienes {motor.MAXIMO_POR_DOCENTE} evaluaciones esperando turno. Espera a que terminen."


# ---------- Dependencias (las pruebas las cambian) ----------


def obtener_fabrica():
    """Cómo abrir una sesión de base nueva en segundo plano (la de la petición ya se cerró)."""
    return lambda: Session(motor_db(), expire_on_commit=False)


def obtener_ia() -> motor.PedirJson:
    return cliente.pedir_json


def obtener_bajar_github():
    return github.bajar_zip


def obtener_verificar():
    """El sandbox (RF-10). Las pruebas lo cambian: el de verdad necesita Docker o Linux."""
    from app.sandbox import verificar

    return verificar


def obtener_config(db: Db) -> ConfigIA:
    try:
        return cliente.configuracion(db)
    except ErrorIA:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, IA_NO_CONFIGURADA) from None


# ---------- Respuesta ----------


def motivos(evaluacion: EvaluacionFila, criterios: list[EvaluacionCriterio]) -> list[MotivoPrioridad]:
    """Por qué esta evaluación va primero en la bandeja (SRS sección 6)."""
    terminada = evaluacion.estado != EstadoEvaluacion.EN_PROCESO.value
    return revision.motivos(evaluacion.alerta_inyeccion, criterios, terminada)


def verificaciones_de(db: Db, evaluacion: EvaluacionFila) -> list[VerificacionCodigo]:
    return [
        VerificacionCodigo(
            tipo=TipoVerificacion(f.tipo),
            comando=f.comando,
            codigo_salida=f.codigo_salida,
            salida=f.salida,
            duracion_ms=f.duracion_ms,
            tiempo_agotado=f.tiempo_agotado,
        )
        for f in db.scalars(
            select(VerificacionCodigoFila)
            .where(VerificacionCodigoFila.evaluacion_id == evaluacion.id)
            .order_by(VerificacionCodigoFila.orden)
        )
    ]


def a_esquema(db: Db, evaluacion: EvaluacionFila) -> Evaluacion:
    criterios = list(
        db.scalars(
            select(EvaluacionCriterio)
            .where(EvaluacionCriterio.evaluacion_id == evaluacion.id)
            .order_by(EvaluacionCriterio.orden)
        )
    )
    return Evaluacion(
        id=evaluacion.id,
        entrega_id=evaluacion.entrega_id,
        rubrica_version_id=evaluacion.rubrica_version_id,
        estado=EstadoEvaluacion(evaluacion.estado),
        proveedor=ProveedorIA(evaluacion.proveedor),
        modelo=evaluacion.modelo,
        version_prompt=evaluacion.version_prompt,
        criterios=[
            CriterioEvaluado(
                criterio_id=c.criterio_id,
                nivel_ia=c.nivel_ia,
                nivel_final=c.nivel_final,
                justificacion=c.justificacion,
                evidencias=[EvidenciaVerificada.model_validate(e) for e in c.evidencias],
                fortalezas=c.fortalezas,
                debilidades=c.debilidades,
                recomendaciones=c.recomendaciones,
            )
            for c in criterios
        ],
        verificaciones=verificaciones_de(db, evaluacion),
        nota_preliminar=evaluacion.nota_preliminar,
        nota_final=evaluacion.nota_final,
        tokens_entrada=evaluacion.tokens_entrada,
        tokens_salida=evaluacion.tokens_salida,
        costo_usd=evaluacion.costo_usd,
        alerta_inyeccion=evaluacion.alerta_inyeccion,
        fecha=evaluacion.fecha,
        aprobada_por=evaluacion.aprobada_por,
        fecha_aprobacion=evaluacion.fecha_aprobacion,
        fecha_publicacion=evaluacion.fecha_publicacion,
        motivos=motivos(evaluacion, criterios),
        aviso=evaluacion.aviso,
    )


# ---------- Rutas ----------


@ruta(
    router,
    "POST",
    "/api/entregas/{entrega_id}/evaluaciones",
    response_model=Evaluacion,
    status_code=status.HTTP_202_ACCEPTED,
)
@limitador.limit(LIMITE_POR_MINUTO, key_func=seguridad.clave_de_usuario)
def lanzar_evaluacion(
    request: Request,
    entrega_id: uuid.UUID,
    actual: Actual,
    db: Db,
    almacen: AlmacenDep,
    config: Annotated[ConfigIA, Depends(obtener_config)],
    fabrica: Annotated[object, Depends(obtener_fabrica)],
    pedir: Annotated[object, Depends(obtener_ia)],
    bajar_github: Annotated[object, Depends(obtener_bajar_github)],
    verificar: Annotated[object, Depends(obtener_verificar)],
) -> Evaluacion:
    motor.recuperar_colgadas(db)
    # La fila de la entrega queda bloqueada hasta el commit: dos docentes que pulsan
    # "Evaluar" al mismo tiempo no crean dos evaluaciones en proceso (en PostgreSQL).
    entrega = db.scalar(select(Entrega).where(Entrega.id == entrega_id).with_for_update(key_share=True))
    if entrega is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, ENTREGA_NO_EXISTE)
    en_proceso = db.scalar(
        select(EvaluacionFila.id).where(
            EvaluacionFila.entrega_id == entrega_id,
            EvaluacionFila.estado == EstadoEvaluacion.EN_PROCESO.value,
        )
    )
    if en_proceso is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, YA_EN_PROCESO)
    recientes = db.scalar(
        select(func.count())
        .select_from(EvaluacionFila)
        .where(
            EvaluacionFila.lanzada_por == actual.id,
            EvaluacionFila.fecha >= seguridad.ahora() - timedelta(hours=1),
        )
    )
    if recientes >= EVALUACIONES_POR_HORA:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, MUCHAS)

    evaluacion = EvaluacionFila(
        entrega_id=entrega.id,
        rubrica_version_id=entrega.rubrica_version_id,  # la versión a la que quedó amarrada (F2)
        lanzada_por=actual.id,
        estado=EstadoEvaluacion.EN_PROCESO.value,
        proveedor=config.proveedor.value,
        modelo=config.modelo,
        version_prompt=motor.VERSION_PROMPT,
    )
    db.add(evaluacion)
    db.flush()
    # Revisar y apartar el lugar en la cola en un solo paso (OWASP LLM10)
    tope = motor.reservar(evaluacion.id, actual.id)
    if tope is not None:
        db.rollback()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, COLA_LLENA if tope == "cola" else MUCHAS_EN_COLA
        )
    registrar(
        db,
        usuario_id=actual.id,
        accion="evaluacion_lanzada",
        entidad="evaluacion",
        entidad_id=evaluacion.id,
        detalle={"entrega_id": str(entrega.id), "proveedor": config.proveedor.value, "modelo": config.modelo},
        ip=seguridad.ip_de(request),
    )
    try:
        db.commit()
    except Exception:
        motor.liberar(evaluacion.id)
        raise
    try:
        return a_esquema(db, evaluacion)
    finally:
        # Corre en el grupo de hilos del evaluador, no en el de las rutas (OWASP LLM10). En el
        # finally: si armar la respuesta falla, igual se encola y el lugar no queda apartado.
        motor.encolar(
            evaluacion.id,
            motor.Contexto(
                fabrica=fabrica,
                pedir=pedir,
                almacen=almacen,
                config=config,
                bajar_github=bajar_github,
                verificar=verificar,
            ),
        )


@ruta(router, "GET", "/api/evaluaciones/{evaluacion_id}", response_model=Evaluacion)
def ver_evaluacion(evaluacion_id: uuid.UUID, db: Db) -> Evaluacion:
    motor.recuperar_colgadas(db)
    evaluacion = db.get(EvaluacionFila, evaluacion_id)
    if evaluacion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_EXISTE)
    return a_esquema(db, evaluacion)
