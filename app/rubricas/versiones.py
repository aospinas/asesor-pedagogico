"""Versiones de la rúbrica (RF-05, RF-06).

- Cada cambio crea una versión nueva; nunca se edita ni se borra una vieja (además
  de no haber rutas para eso, la base de datos lo impide con los eventos de abajo).
- La vigente es la de número más alto.
- Una versión con errores se guarda (el docente la corrige en el editor) pero no
  sirve para evaluar.
- Una versión que convirtió la IA (PDF, Word o texto) queda "por confirmar": no
  sirve para evaluar ni la ve el estudiante hasta que el docente la revisa y la
  guarda desde el editor, que crea una versión nueva confirmada (D-16).
"""

import uuid

from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import esquemas
from app.esquemas import OrigenRubrica, RubricaEstructura, validar_rubrica
from app.ia.cliente import Uso
from app.modelos import Rubrica, RubricaVersion

# Lo que convierte la IA lo tiene que confirmar el docente: la IA propone, el docente aprueba.
ORIGENES_POR_CONFIRMAR = frozenset({OrigenRubrica.PDF, OrigenRubrica.DOCX, OrigenRubrica.TEXTO})
_POR_CONFIRMAR = [o.value for o in ORIGENES_POR_CONFIRMAR]


class RubricaNoEvaluable(Exception):
    """El laboratorio no tiene rúbrica, o la vigente tiene errores o falta confirmarla."""


class VersionOcupada(Exception):
    """Otra persona guardó una versión al mismo tiempo."""


@event.listens_for(RubricaVersion, "before_update")
@event.listens_for(RubricaVersion, "before_delete")
def _inmutable(mapper, conexion, version) -> None:
    raise ValueError("Las versiones de la rúbrica no se editan ni se borran: se crea una nueva.")


def por_confirmar(version: RubricaVersion) -> bool:
    return version.origen in _POR_CONFIRMAR


def _rubrica_del_laboratorio(db: Session, laboratorio_id: uuid.UUID) -> Rubrica:
    """La rúbrica del laboratorio, creada si no existe y con la fila bloqueada.

    El bloqueo hace que dos guardados al mismo tiempo no saquen el mismo número
    (en PostgreSQL; la restricción única de la tabla es la segunda defensa).
    """
    consulta = select(Rubrica).where(Rubrica.laboratorio_id == laboratorio_id).with_for_update()
    rubrica = db.scalar(consulta)
    if rubrica is not None:
        return rubrica
    try:
        with db.begin_nested():
            db.add(Rubrica(laboratorio_id=laboratorio_id))
    except IntegrityError:  # otro la creó al mismo tiempo
        pass
    return db.scalars(consulta.execution_options(populate_existing=True)).one()


def guardar_version(
    db: Session,
    laboratorio_id: uuid.UUID,
    estructura: RubricaEstructura,
    *,
    origen: OrigenRubrica | str,
    creada_por: uuid.UUID,
    archivo_sha256: str | None = None,
    prompt_version: str | None = None,
    uso: Uso | None = None,
) -> RubricaVersion:
    """Agrega la versión siguiente. No hace commit: va en la transacción de quien la llama."""
    rubrica = _rubrica_del_laboratorio(db, laboratorio_id)
    ultimo = db.scalar(select(func.max(RubricaVersion.numero)).where(RubricaVersion.rubrica_id == rubrica.id))
    errores = validar_rubrica(estructura)
    version = RubricaVersion(
        rubrica_id=rubrica.id,
        numero=(ultimo or 0) + 1,
        estructura=estructura.model_dump(mode="json"),
        valida=not errores,
        errores=errores,
        origen=OrigenRubrica(origen).value,
        archivo_sha256=archivo_sha256,
        prompt_version=prompt_version,
        modelo=uso.modelo if uso else None,
        tokens_entrada=uso.entrada if uso else None,
        tokens_salida=uso.salida if uso else None,
        creada_por=creada_por,
    )
    try:
        with db.begin_nested():
            db.add(version)
    except IntegrityError:  # el mismo número al mismo tiempo (sin bloqueo de fila, como en SQLite)
        raise VersionOcupada from None
    return version


def _versiones(laboratorio_id: uuid.UUID):
    return (
        select(RubricaVersion)
        .join(Rubrica, Rubrica.id == RubricaVersion.rubrica_id)
        .where(Rubrica.laboratorio_id == laboratorio_id)
        .order_by(RubricaVersion.numero.desc())
    )


def vigente(db: Session, laboratorio_id: uuid.UUID) -> RubricaVersion | None:
    return db.scalars(_versiones(laboratorio_id).limit(1)).first()


def ultima_lista(db: Session, laboratorio_id: uuid.UUID) -> RubricaVersion | None:
    """La última versión válida y confirmada por el docente: la que ve el estudiante."""
    consulta = _versiones(laboratorio_id).where(
        RubricaVersion.valida.is_(True), RubricaVersion.origen.not_in(_POR_CONFIRMAR)
    )
    return db.scalars(consulta.limit(1)).first()


def todas(db: Session, laboratorio_id: uuid.UUID) -> list[RubricaVersion]:
    return list(db.scalars(_versiones(laboratorio_id)))


def version_evaluable(db: Session, laboratorio_id: uuid.UUID) -> RubricaVersion:
    """La versión con la que se puede evaluar (RF-05). Si la vigente no está lista, no hay evaluación."""
    version = vigente(db, laboratorio_id)
    if version is None:
        raise RubricaNoEvaluable("El laboratorio no tiene rúbrica.")
    if not version.valida:
        raise RubricaNoEvaluable("La rúbrica vigente tiene errores: corrígela antes de evaluar.")
    if por_confirmar(version):
        raise RubricaNoEvaluable("La rúbrica la convirtió la IA: revísala y guárdala antes de evaluar.")
    return version


def a_esquema(version: RubricaVersion) -> esquemas.RubricaVersion:
    return esquemas.RubricaVersion(
        id=version.id,
        rubrica_id=version.rubrica_id,
        numero=version.numero,
        estructura=RubricaEstructura.model_validate(version.estructura),
        valida=version.valida,
        errores=version.errores,
        origen=OrigenRubrica(version.origen),
        por_confirmar=por_confirmar(version),
        prompt_version=version.prompt_version,
        creada_por=version.creada_por,
        fecha=version.fecha,
    )


def a_publica(version: RubricaVersion) -> esquemas.RubricaPublica:
    """Lo que ve el estudiante: sin errores, sin quién la hizo ni de dónde salió."""
    return esquemas.RubricaPublica(
        numero=version.numero,
        estructura=RubricaEstructura.model_validate(version.estructura),
        fecha=version.fecha,
    )
