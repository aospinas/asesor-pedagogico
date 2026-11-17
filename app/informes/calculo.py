"""Los números del informe integrado (RF-16). Los calcula el backend, nunca la IA.

- Solo cuentan evaluaciones PUBLICADAS. Por cada laboratorio, la publicada más reciente.
- Promedios con Decimal y redondeo comercial a un decimal, como la nota (app/evaluador/nota.py).
- Nivel de dominio (SRS sección 9): 4,5 a 5,0 Alto; 3,5 a 4,4 Medio; 3,0 a 3,4 Básico;
  menos de 3,0 Por fortalecer.
- Temas: los de cada laboratorio (`temas_ia`). Se escriben "Categoría: tema"; sin dos puntos
  van a la categoría "Otros temas" (D-22).
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.esquemas import (
    DominioCompetencia,
    DominioTema,
    EstadoEvaluacion,
    NivelDominio,
    ResultadoCohorte,
    ResultadoLaboratorio,
    RubricaEstructura,
)
from app.modelos import Cohorte, Entrega, Evaluacion, EvaluacionCriterio, Laboratorio, RubricaVersion

OTROS_TEMAS = "Otros temas"


def nivel_de(nota: float) -> NivelDominio:
    """Con la nota ya redondeada a un decimal (así 4,45 → 4,5 cuenta como Alto)."""
    if nota >= 4.5:
        return NivelDominio.ALTO
    if nota >= 3.5:
        return NivelDominio.MEDIO
    if nota >= 3.0:
        return NivelDominio.BASICO
    return NivelDominio.POR_FORTALECER


def promedio(notas: list[float]) -> float | None:
    if not notas:
        return None
    total = sum((Decimal(str(n)) for n in notas), Decimal("0"))
    return float((total / len(notas)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def partir_tema(texto: str) -> tuple[str, str]:
    """'Agentes: uso de herramientas' → ('Agentes', 'uso de herramientas')."""
    if ":" in texto:
        categoria, tema = (p.strip() for p in texto.split(":", 1))
        if categoria and tema:
            return categoria, tema
    return OTROS_TEMAS, texto.strip()


@dataclass
class Publicada:
    """Una evaluación publicada que cuenta para el informe (la más reciente del laboratorio)."""

    evaluacion: Evaluacion
    laboratorio: Laboratorio
    cohorte: Cohorte
    criterios: list[EvaluacionCriterio] = field(default_factory=list)
    rubrica: "RubricaEstructura | None" = None


@dataclass
class Datos:
    laboratorios: list[ResultadoLaboratorio]
    promedio_general: float | None
    temas: list[DominioTema]
    brechas: list[str]
    publicadas: list[Publicada]
    cohortes: list[ResultadoCohorte] = field(default_factory=list)
    competencias: list[DominioCompetencia] = field(default_factory=list)


def coma(valor: float) -> str:
    """3.4 → "3,4" (como se escriben los decimales en Colombia)."""
    return f"{valor:.1f}".replace(".", ",")


def _rubrica(version: RubricaVersion | None) -> RubricaEstructura | None:
    try:
        return RubricaEstructura.model_validate(version.estructura) if version else None
    except ValidationError:
        return None


def publicadas_de(db: Session, estudiante_id: uuid.UUID) -> list[Publicada]:
    filas = db.execute(
        select(Evaluacion, Laboratorio, Cohorte)
        .join(Entrega, Entrega.id == Evaluacion.entrega_id)
        .join(Laboratorio, Laboratorio.id == Entrega.laboratorio_id)
        .join(Cohorte, Cohorte.id == Laboratorio.cohorte_id)
        .where(
            Entrega.estudiante_id == estudiante_id,
            Evaluacion.estado == EstadoEvaluacion.PUBLICADA.value,
            Evaluacion.nota_final.is_not(None),
        )
        .order_by(Evaluacion.fecha_publicacion.desc(), Evaluacion.id.desc())
    ).all()
    por_laboratorio: dict[uuid.UUID, Publicada] = {}
    for evaluacion, laboratorio, cohorte in filas:  # la primera es la más reciente
        por_laboratorio.setdefault(laboratorio.id, Publicada(evaluacion, laboratorio, cohorte))
    elegidas = list(por_laboratorio.values())
    if elegidas:
        ids = [p.evaluacion.id for p in elegidas]
        criterios = db.scalars(
            select(EvaluacionCriterio)
            .where(EvaluacionCriterio.evaluacion_id.in_(ids))
            .order_by(EvaluacionCriterio.orden)
        )
        por_evaluacion = {p.evaluacion.id: p for p in elegidas}
        for c in criterios:
            por_evaluacion[c.evaluacion_id].criterios.append(c)
        versiones = {
            v.id: v
            for v in db.scalars(
                select(RubricaVersion).where(
                    RubricaVersion.id.in_({p.evaluacion.rubrica_version_id for p in elegidas})
                )
            )
        }
        for p in elegidas:
            p.rubrica = _rubrica(versiones.get(p.evaluacion.rubrica_version_id))

    # Orden del informe: por fecha de publicación, de la más vieja a la más nueva (evolución)
    def cuando(p: Publicada) -> float:
        fecha = p.evaluacion.fecha_publicacion
        return fecha.timestamp() if isinstance(fecha, datetime) else 0.0

    return sorted(elegidas, key=lambda p: (cuando(p), str(p.laboratorio.id)))


def calcular(db: Session, estudiante_id: uuid.UUID) -> Datos:
    publicadas = publicadas_de(db, estudiante_id)
    laboratorios = [
        ResultadoLaboratorio(
            laboratorio_id=p.laboratorio.id,
            evaluacion_id=p.evaluacion.id,
            titulo=p.laboratorio.titulo,
            cohorte=p.cohorte.nombre,
            nota_final=p.evaluacion.nota_final,
            nivel=nivel_de(p.evaluacion.nota_final),
            fecha_publicacion=p.evaluacion.fecha_publicacion,
        )
        for p in publicadas
    ]
    # Dominio por tema: promedio de las notas de los laboratorios donde aparece el tema
    por_tema: dict[tuple[str, str], list[Publicada]] = {}
    for p in publicadas:
        for texto in dict.fromkeys(p.laboratorio.temas_ia or []):  # sin repetidos
            por_tema.setdefault(partir_tema(texto), []).append(p)
    temas = []
    for (categoria, tema), lista in sorted(
        por_tema.items(), key=lambda x: (x[0][0].casefold(), x[0][1].casefold())
    ):
        valor = promedio([p.evaluacion.nota_final for p in lista])
        temas.append(
            DominioTema(
                categoria=categoria,
                tema=tema,
                promedio=valor,
                nivel=nivel_de(valor),
                laboratorios=[p.laboratorio.id for p in lista],
            )
        )
    brechas = [
        f"{t.categoria}: {t.tema} ({t.nivel.value}, {coma(t.promedio)})"
        for t in temas
        if t.nivel in (NivelDominio.BASICO, NivelDominio.POR_FORTALECER)
    ]
    return Datos(
        laboratorios=laboratorios,
        promedio_general=promedio([r.nota_final for r in laboratorios]),
        temas=temas,
        brechas=brechas,
        publicadas=publicadas,
        cohortes=_por_cohorte(publicadas),
        competencias=_por_competencia(publicadas),
    )


def _por_cohorte(publicadas: list[Publicada]) -> list[ResultadoCohorte]:
    """Evolución entre cohortes: promedio de las notas de cada cohorte, en orden de aparición."""
    grupos: dict[str, list[Publicada]] = {}
    for p in publicadas:
        grupos.setdefault(p.cohorte.nombre, []).append(p)
    resultado = []
    for nombre, lista in grupos.items():
        valor = promedio([p.evaluacion.nota_final for p in lista])
        resultado.append(
            ResultadoCohorte(
                cohorte=nombre,
                promedio=valor,
                nivel=nivel_de(valor),
                laboratorios=[p.laboratorio.id for p in lista],
            )
        )
    return resultado


def _por_competencia(publicadas: list[Publicada]) -> list[DominioCompetencia]:
    """Cada criterio aporta su nivel final llevado a 0-5 (valor / valor máximo × 5) a su
    competencia; el dominio es el promedio. Con la rúbrica de la versión evaluada."""
    puntos: dict[str, list[float]] = {}
    labs: dict[str, list[uuid.UUID]] = {}
    for p in publicadas:
        if p.rubrica is None:
            continue
        criterios = {c.id: c for c in p.rubrica.criterios}
        for fila in p.criterios:
            criterio = criterios.get(fila.criterio_id)
            nivel_id = fila.nivel_final or fila.nivel_ia
            nivel = next((n for n in criterio.niveles if n.id == nivel_id), None) if criterio else None
            if nivel is None or criterio.valor_maximo <= 0:
                continue
            valor = Decimal(str(nivel.valor)) / Decimal(str(criterio.valor_maximo)) * Decimal("5")
            puntos.setdefault(criterio.competencia, []).append(float(valor))
            if p.laboratorio.id not in labs.setdefault(criterio.competencia, []):
                labs[criterio.competencia].append(p.laboratorio.id)
    resultado = []
    for competencia in sorted(puntos, key=str.casefold):
        valor = promedio(puntos[competencia])
        resultado.append(
            DominioCompetencia(
                competencia=competencia, promedio=valor, nivel=nivel_de(valor), laboratorios=labs[competencia]
            )
        )
    return resultado
