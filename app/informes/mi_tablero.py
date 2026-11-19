"""Tablero del estudiante (D-25). Lo calcula el backend y solo con evaluaciones publicadas (RNF-09):
de lo que no se ha publicado el estudiante solo sabe que está esperando, nunca una nota.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.esquemas import CriterioEstudiante, LaboratorioPendiente, MiTablero, UltimaNota
from app.informes.calculo import nivel_de, promedio, publicadas_de
from app.modelos import Entrega, Laboratorio

CUANTOS = 3  # fortalezas y criterios por mejorar que se muestran


def calcular(db: Session, estudiante_id: uuid.UUID) -> MiTablero:
    labs = list(db.scalars(select(Laboratorio).order_by(Laboratorio.titulo)))
    entregados = set(db.scalars(select(Entrega.laboratorio_id).where(Entrega.estudiante_id == estudiante_id)))
    publicadas = publicadas_de(db, estudiante_id)  # una por laboratorio, en orden de publicación
    con_nota = {p.laboratorio.id for p in publicadas}

    notas = [p.evaluacion.nota_final for p in publicadas if p.evaluacion.nota_final is not None]
    general = promedio(notas)

    ultima = None
    if publicadas and publicadas[-1].evaluacion.nota_final is not None:
        p = publicadas[-1]
        anterior = publicadas[-2].evaluacion.nota_final if len(publicadas) > 1 else None
        nota = p.evaluacion.nota_final
        ultima = UltimaNota(
            evaluacion_id=p.evaluacion.id,
            titulo=p.laboratorio.titulo,
            nota=nota,
            nivel=nivel_de(nota),
            fecha=p.evaluacion.fecha_publicacion or p.evaluacion.fecha,
            cambio=round(nota - anterior, 1) if anterior is not None else None,
        )

    # Dominio de cada criterio: nivel final llevado a 0-5 con la rúbrica que se usó al evaluar.
    criterios: list[CriterioEstudiante] = []
    for p in publicadas:
        if p.rubrica is None:
            continue
        por_id = {c.id: c for c in p.rubrica.criterios}
        for fila in p.criterios:
            criterio = por_id.get(fila.criterio_id)
            nivel = (
                next((n for n in criterio.niveles if n.id == fila.nivel_final), None) if criterio else None
            )
            if criterio is None or nivel is None or criterio.valor_maximo <= 0:
                continue
            valor = promedio([nivel.valor / criterio.valor_maximo * 5]) or 0.0
            criterios.append(
                CriterioEstudiante(
                    laboratorio=p.laboratorio.titulo,
                    criterio=criterio.nombre,
                    promedio=valor,
                    nivel=nivel_de(valor),
                )
            )
    altos = sorted(criterios, key=lambda c: (-c.promedio, c.laboratorio, c.criterio))
    bajos = sorted(criterios, key=lambda c: (c.promedio, c.laboratorio, c.criterio))

    return MiTablero(
        laboratorios=len(labs),
        pendientes=[
            LaboratorioPendiente(laboratorio_id=lab.id, titulo=lab.titulo)
            for lab in labs
            if lab.id not in entregados
        ],
        entregados=len(entregados),
        esperando=len(entregados - con_nota),
        publicados=len(con_nota),
        promedio=general,
        nivel=nivel_de(general) if general is not None else None,
        ultima=ultima,
        fortalezas=altos[:CUANTOS],
        # Solo se muestra como "por mejorar" lo que no está ya en Alto.
        por_mejorar=[c for c in bajos if c.promedio < 4.5][:CUANTOS],
    )
