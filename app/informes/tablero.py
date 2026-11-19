"""Tablero del docente (D-24): métricas reales del curso. Las calcula el backend, nunca la IA.

- Cada entrega cuenta una vez, con su evaluación más reciente.
- Promedios y niveles con las mismas reglas del informe (app/informes/calculo.py).
- El dominio de un criterio es su nivel final llevado a 0-5 (valor del nivel / valor máximo × 5),
  con la versión de rúbrica que se usó al evaluar.
"""

import uuid
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.esquemas import (
    AcuerdoIA,
    AlertasTablero,
    CriterioTablero,
    EstadoEvaluacion,
    LaboratorioTablero,
    NivelCantidad,
    NivelDominio,
    ResumenTablero,
    Rol,
    RubricaEstructura,
    Tablero,
)
from app.informes.calculo import nivel_de, promedio
from app.modelos import Entrega, Evaluacion, EvaluacionCriterio, Laboratorio, RubricaVersion, Usuario

DEBILES = 5  # cuántos criterios débiles se muestran
POR_REVISAR = {EstadoEvaluacion.EN_REVISION.value, EstadoEvaluacion.REVISION_MANUAL.value}
CERRADAS = {EstadoEvaluacion.APROBADA.value, EstadoEvaluacion.PUBLICADA.value}


def _ultimas(db: Session) -> dict[uuid.UUID, Evaluacion]:
    """La evaluación más reciente de cada entrega."""
    ultimas: dict[uuid.UUID, Evaluacion] = {}
    for ev in db.scalars(select(Evaluacion).order_by(Evaluacion.fecha, Evaluacion.id)):
        ultimas[ev.entrega_id] = ev
    return ultimas


def _rubricas(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, RubricaEstructura]:
    salida: dict[uuid.UUID, RubricaEstructura] = {}
    if ids:
        for v in db.scalars(select(RubricaVersion).where(RubricaVersion.id.in_(ids))):
            try:
                salida[v.id] = RubricaEstructura.model_validate(v.estructura)
            except ValueError:
                continue  # una versión dañada no tumba el tablero
    return salida


def calcular(db: Session) -> Tablero:
    entregas = list(db.scalars(select(Entrega)))
    labs = {lab.id: lab for lab in db.scalars(select(Laboratorio).order_by(Laboratorio.titulo))}
    ultimas = _ultimas(db)
    estudiantes = db.scalar(
        select(func.count()).select_from(Usuario).where(Usuario.rol == Rol.ESTUDIANTE.value, Usuario.activo)
    )

    estados: dict[str, int] = defaultdict(int)
    por_lab: dict[uuid.UUID, dict] = {i: {"entregas": 0, "evaluadas": 0, "notas": []} for i in labs}
    notas: list[float] = []
    cerradas: list[tuple[Evaluacion, Entrega]] = []
    pendientes: list[Evaluacion] = []
    for entrega in entregas:
        fila = por_lab.setdefault(entrega.laboratorio_id, {"entregas": 0, "evaluadas": 0, "notas": []})
        fila["entregas"] += 1
        ev = ultimas.get(entrega.id)
        if ev is None:
            estados["sin_evaluar"] += 1
            continue
        estados[ev.estado] += 1
        if ev.estado != EstadoEvaluacion.EN_PROCESO.value:
            fila["evaluadas"] += 1
        if ev.estado == EstadoEvaluacion.PUBLICADA.value and ev.nota_final is not None:
            notas.append(ev.nota_final)
            fila["notas"].append(ev.nota_final)
        if ev.estado in CERRADAS:
            cerradas.append((ev, entrega))
        elif ev.estado in POR_REVISAR:
            pendientes.append(ev)

    general = promedio(notas)
    resumen = ResumenTablero(
        estudiantes=estudiantes or 0,
        laboratorios=len(labs),
        entregas=len(entregas),
        sin_evaluar=estados["sin_evaluar"],
        en_proceso=estados[EstadoEvaluacion.EN_PROCESO.value],
        por_revisar=sum(estados[e] for e in POR_REVISAR),
        aprobadas=estados[EstadoEvaluacion.APROBADA.value],
        publicadas=estados[EstadoEvaluacion.PUBLICADA.value],
        promedio=general,
    )

    conteo = defaultdict(int)
    for n in notas:
        conteo[nivel_de(promedio([n]) or 0)] += 1
    niveles = [NivelCantidad(nivel=n, cantidad=conteo[n]) for n in NivelDominio]

    laboratorios = []
    for lab_id, fila in por_lab.items():
        lab = labs.get(lab_id)
        if lab is None:
            continue
        prom = promedio(fila["notas"])
        laboratorios.append(
            LaboratorioTablero(
                laboratorio_id=lab_id,
                titulo=lab.titulo,
                entregas=fila["entregas"],
                evaluadas=fila["evaluadas"],
                publicadas=len(fila["notas"]),
                promedio=prom,
                nivel=nivel_de(prom) if prom is not None else None,
            )
        )

    # Criterios (dominio y acuerdo con la IA) de las evaluaciones aprobadas y publicadas
    ids = [ev.id for ev, _ in cerradas]
    criterios: dict[uuid.UUID, list[EvaluacionCriterio]] = defaultdict(list)
    if ids:
        for c in db.scalars(select(EvaluacionCriterio).where(EvaluacionCriterio.evaluacion_id.in_(ids))):
            criterios[c.evaluacion_id].append(c)
    rubricas = _rubricas(db, {ev.rubrica_version_id for ev, _ in cerradas})
    dominio: dict[tuple[str, str], list[float]] = defaultdict(list)
    revisados = iguales = 0
    for ev, entrega in cerradas:
        rubrica = rubricas.get(ev.rubrica_version_id)
        lab = labs.get(entrega.laboratorio_id)
        for c in criterios[ev.id]:
            if c.nivel_ia is not None and c.nivel_final is not None:
                revisados += 1
                iguales += c.nivel_ia == c.nivel_final
            criterio = (
                next((k for k in rubrica.criterios if k.id == c.criterio_id), None) if rubrica else None
            )
            nivel = next((n for n in criterio.niveles if n.id == c.nivel_final), None) if criterio else None
            if criterio and nivel and criterio.valor_maximo > 0 and lab:
                dominio[(lab.titulo, criterio.nombre)].append(nivel.valor / criterio.valor_maximo * 5)

    debiles = []
    for (titulo, nombre), valores in dominio.items():
        prom = promedio(valores)
        if prom is not None:
            debiles.append(
                CriterioTablero(
                    laboratorio=titulo,
                    criterio=nombre,
                    promedio=prom,
                    nivel=nivel_de(prom),
                    evaluaciones=len(valores),
                )
            )
    debiles.sort(key=lambda c: (c.promedio, c.laboratorio, c.criterio))

    acuerdo = AcuerdoIA(
        criterios=revisados,
        iguales=iguales,
        cambiados=revisados - iguales,
        porcentaje=round(iguales * 100 / revisados, 1) if revisados else None,
    )

    ids_pendientes = [ev.id for ev in pendientes]
    con_cita_fallida: set[uuid.UUID] = set()
    if ids_pendientes:
        for c in db.scalars(
            select(EvaluacionCriterio).where(EvaluacionCriterio.evaluacion_id.in_(ids_pendientes))
        ):
            if any(e.get("encontrada") is False for e in c.evidencias or []):
                con_cita_fallida.add(c.evaluacion_id)
    alertas = AlertasTablero(
        inyeccion=sum(1 for ev in pendientes if ev.alerta_inyeccion),
        citas_no_encontradas=len(con_cita_fallida),
        revision_manual=estados[EstadoEvaluacion.REVISION_MANUAL.value],
    )

    return Tablero(
        resumen=resumen,
        niveles=niveles,
        laboratorios=laboratorios,
        criterios_debiles=debiles[:DEBILES],
        acuerdo=acuerdo,
        alertas=alertas,
        generado=datetime.now(UTC),
    )
