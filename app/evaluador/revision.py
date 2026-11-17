"""Reglas de la revisión del docente (RF-14, SRS sección 6, D-21).

- El nivel que cuenta es el del docente si lo cambió (`nivel_final`) y si no, el de la IA.
- La nota SIEMPRE sale de `calcular_nota` con esos niveles: el docente nunca la escribe.
- Una evaluación en "revisión manual" pasa a "en revisión" cuando todos los criterios tienen
  nivel (el docente calificó a mano lo que la IA no pudo).
- La prioridad en la bandeja es el número de motivos (cita no encontrada, alerta de inyección,
  sin propuesta); se guarda en la evaluación para ordenar y paginar en la base.
"""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.seguridad import ahora
from app.esquemas import Criterio, EstadoEvaluacion, MotivoPrioridad, RubricaEstructura
from app.evaluador.nota import ErrorDeNota, calcular_nota
from app.modelos import Evaluacion, EvaluacionCriterio


def nivel_efectivo(fila: EvaluacionCriterio | None) -> str | None:
    if fila is None:
        return None
    return fila.nivel_final or fila.nivel_ia


def motivos(
    alerta_inyeccion: bool, criterios: Iterable[EvaluacionCriterio], terminada: bool
) -> list[MotivoPrioridad]:
    """Por qué esta evaluación va primero en la bandeja (SRS sección 6)."""
    criterios = list(criterios)
    lista = []
    if any(e.get("encontrada") is False for c in criterios for e in c.evidencias):
        lista.append(MotivoPrioridad.CITA_NO_ENCONTRADA)
    if alerta_inyeccion:
        lista.append(MotivoPrioridad.ALERTA_INYECCION)
    if terminada and any(nivel_efectivo(c) is None for c in criterios):
        lista.append(MotivoPrioridad.SIN_PROPUESTA)
    return lista


def filas_por_criterio(db: Session, evaluacion: Evaluacion) -> dict[str, EvaluacionCriterio]:
    filas = db.scalars(select(EvaluacionCriterio).where(EvaluacionCriterio.evaluacion_id == evaluacion.id))
    return {f.criterio_id: f for f in filas}


def fila_del_criterio(
    db: Session, evaluacion: Evaluacion, rubrica: RubricaEstructura, criterio: Criterio
) -> EvaluacionCriterio:
    """La fila del criterio. Si el motor no alcanzó a crearla (se cortó a mitad), se crea
    vacía: así el docente puede calificar a mano todos los criterios."""
    fila = filas_por_criterio(db, evaluacion).get(criterio.id)
    if fila is None:
        orden = [c.id for c in rubrica.criterios].index(criterio.id)
        fila = EvaluacionCriterio(
            evaluacion_id=evaluacion.id,
            criterio_id=criterio.id,
            orden=orden,
            justificacion="",
            evidencias=[],
            fortalezas=[],
            debilidades=[],
            recomendaciones=[],
            intentos=0,
        )
        db.add(fila)
        db.flush()
    return fila


def niveles_efectivos(
    db: Session, evaluacion: Evaluacion, rubrica: RubricaEstructura
) -> dict[str, str | None]:
    filas = filas_por_criterio(db, evaluacion)
    return {c.id: nivel_efectivo(filas.get(c.id)) for c in rubrica.criterios}


def nota_con(rubrica: RubricaEstructura, niveles: dict[str, str | None]) -> float | None:
    """La nota con estos niveles, o None si falta alguno (o la rúbrica no cuadra)."""
    if not all(niveles.values()):
        return None
    try:
        return calcular_nota(rubrica, niveles)  # type: ignore[arg-type]
    except ErrorDeNota:
        return None


def recalcular(db: Session, evaluacion: Evaluacion, rubrica: RubricaEstructura) -> None:
    """Después de un cambio del docente: nota preliminar, estado y prioridad."""
    db.flush()
    nota = nota_con(rubrica, niveles_efectivos(db, evaluacion, rubrica))
    evaluacion.nota_preliminar = nota
    if evaluacion.estado == EstadoEvaluacion.REVISION_MANUAL.value and nota is not None:
        evaluacion.estado = EstadoEvaluacion.EN_REVISION.value
    filas = filas_por_criterio(db, evaluacion).values()
    evaluacion.prioridad = len(motivos(evaluacion.alerta_inyeccion, filas, terminada=True))
    evaluacion.actualizada = ahora()
