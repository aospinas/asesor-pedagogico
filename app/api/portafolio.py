"""Portafolio de cada estudiante, por cohorte y laboratorio (RF-08).

El estudiante solo ve el suyo (si pide otro recibe 404, como si no existiera). El
docente ve el de cualquier estudiante y la lista de estudiantes para abrirlos.
"""

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api import seguridad
from app.api.entregas import (
    LIMITE_CONSULTAS,
    LISTA_POR_DEFECTO,
    Desde,
    Limite,
    armar_entregas,
    es_estudiante,
    negar_ajeno,
)
from app.api.seguridad import Actual, Db, limitador, ruta
from app.esquemas import CohortePortafolio, LaboratorioPortafolio, Portafolio, Rol, UsuarioPublico
from app.modelos import Cohorte, Entrega, Laboratorio, Usuario

router = APIRouter()

NO_EXISTE = "Ese portafolio no existe."


@ruta(router, "GET", "/api/estudiantes", response_model=list[UsuarioPublico])
def listar_estudiantes(db: Db, desde: Desde = 0, limite: Limite = LISTA_POR_DEFECTO) -> list[UsuarioPublico]:
    filas = db.scalars(
        select(Usuario)
        .where(Usuario.rol == Rol.ESTUDIANTE.value)
        .order_by(Usuario.nombre, Usuario.correo)
        .offset(desde)
        .limit(limite)
    )
    return [seguridad.publico(u) for u in filas]


@ruta(router, "GET", "/api/portafolio/{estudiante_id}", response_model=Portafolio)
@limitador.limit(LIMITE_CONSULTAS, key_func=seguridad.clave_de_usuario)
def ver_portafolio(request: Request, estudiante_id: uuid.UUID, actual: Actual, db: Db) -> Portafolio:
    if es_estudiante(actual) and estudiante_id != actual.id:
        negar_ajeno(db, request, actual.id, "portafolio", estudiante_id)
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_EXISTE)
    estudiante = db.get(Usuario, estudiante_id)
    if estudiante is None or estudiante.rol != Rol.ESTUDIANTE.value:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_EXISTE)

    filas = db.execute(
        select(Entrega, Laboratorio, Cohorte)
        .join(Laboratorio, Laboratorio.id == Entrega.laboratorio_id)
        .join(Cohorte, Cohorte.id == Laboratorio.cohorte_id)
        .where(Entrega.estudiante_id == estudiante_id)
        .order_by(  # los ids desempatan: el orden es siempre el mismo
            Cohorte.nombre,
            Cohorte.periodo,
            Cohorte.id,
            Laboratorio.creado,
            Laboratorio.id,
            Entrega.fecha.desc(),
            Entrega.id.desc(),
        )
    ).all()
    completas = {e.id: e for e in armar_entregas(db, [fila.Entrega for fila in filas])}

    cohortes: dict[uuid.UUID, CohortePortafolio] = {}
    laboratorios: dict[uuid.UUID, LaboratorioPortafolio] = {}
    for entrega, laboratorio, cohorte in filas:
        if cohorte.id not in cohortes:
            cohortes[cohorte.id] = CohortePortafolio(
                cohorte_id=cohorte.id, nombre=cohorte.nombre, periodo=cohorte.periodo, laboratorios=[]
            )
        if laboratorio.id not in laboratorios:
            laboratorios[laboratorio.id] = LaboratorioPortafolio(
                laboratorio_id=laboratorio.id, titulo=laboratorio.titulo, entregas=[]
            )
            cohortes[cohorte.id].laboratorios.append(laboratorios[laboratorio.id])
        laboratorios[laboratorio.id].entregas.append(completas[entrega.id])

    return Portafolio(estudiante_id=estudiante.id, nombre=estudiante.nombre, cohortes=list(cohortes.values()))
