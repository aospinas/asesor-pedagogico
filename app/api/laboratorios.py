"""Cohortes y laboratorios (RF-03). Todos los ven; solo el docente los crea y edita."""

import hashlib
import uuid

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api import seguridad
from app.api.seguridad import Actual, Db, ruta
from app.auditoria.registro import registrar
from app.esquemas import Cohorte, CohorteCrear, Laboratorio, LaboratorioCrear, LaboratorioEditar
from app.modelos import Cohorte as CohorteFila
from app.modelos import Laboratorio as LaboratorioFila

router = APIRouter()

COHORTE_NO_EXISTE = "Esa cohorte no existe."
LABORATORIO_NO_EXISTE = "Ese laboratorio no existe."
COHORTE_REPETIDA = "Ya existe una cohorte con ese nombre y periodo."
LARGO_AUDITORIA = 200


def buscar_laboratorio(db: Db, laboratorio_id: uuid.UUID) -> LaboratorioFila:
    laboratorio = db.get(LaboratorioFila, laboratorio_id)
    if laboratorio is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, LABORATORIO_NO_EXISTE)
    return laboratorio


def _para_auditoria(valor):
    """Los textos largos (descripción, objetivos) se guardan recortados y con su huella."""
    if isinstance(valor, str) and len(valor) > LARGO_AUDITORIA:
        return {"inicio": valor[:LARGO_AUDITORIA], "sha256": hashlib.sha256(valor.encode()).hexdigest()}
    return valor


def _cohorte(fila: CohorteFila) -> Cohorte:
    return Cohorte(id=fila.id, nombre=fila.nombre, periodo=fila.periodo)


def _laboratorio(fila: LaboratorioFila) -> Laboratorio:
    return Laboratorio(
        id=fila.id,
        cohorte_id=fila.cohorte_id,
        titulo=fila.titulo,
        descripcion=fila.descripcion,
        objetivos=fila.objetivos,
        temas_ia=list(fila.temas_ia),
    )


@ruta(router, "GET", "/api/cohortes", response_model=list[Cohorte])
def listar_cohortes(db: Db) -> list[Cohorte]:
    return [_cohorte(c) for c in db.scalars(select(CohorteFila).order_by(CohorteFila.nombre))]


@ruta(router, "POST", "/api/cohortes", response_model=Cohorte, status_code=status.HTTP_201_CREATED)
def crear_cohorte(request: Request, datos: CohorteCrear, actual: Actual, db: Db) -> Cohorte:
    repetida = select(CohorteFila.id).where(
        CohorteFila.nombre == datos.nombre, CohorteFila.periodo == datos.periodo
    )
    if db.scalar(repetida) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, COHORTE_REPETIDA)
    cohorte = CohorteFila(nombre=datos.nombre, periodo=datos.periodo)
    db.add(cohorte)
    try:
        db.flush()
    except IntegrityError:  # dos altas iguales al mismo tiempo
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, COHORTE_REPETIDA) from None
    registrar(
        db,
        usuario_id=actual.id,
        accion="cohorte_creada",
        entidad="cohorte",
        entidad_id=cohorte.id,
        ip=seguridad.ip_de(request),
    )
    db.commit()
    return _cohorte(cohorte)


@ruta(router, "GET", "/api/laboratorios", response_model=list[Laboratorio])
def listar_laboratorios(db: Db, cohorte_id: uuid.UUID | None = None) -> list[Laboratorio]:
    consulta = select(LaboratorioFila).order_by(LaboratorioFila.creado, LaboratorioFila.titulo)
    if cohorte_id is not None:
        consulta = consulta.where(LaboratorioFila.cohorte_id == cohorte_id)
    return [_laboratorio(lab) for lab in db.scalars(consulta)]


@ruta(router, "POST", "/api/laboratorios", response_model=Laboratorio, status_code=status.HTTP_201_CREATED)
def crear_laboratorio(request: Request, datos: LaboratorioCrear, actual: Actual, db: Db) -> Laboratorio:
    if db.get(CohorteFila, datos.cohorte_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, COHORTE_NO_EXISTE)
    laboratorio = LaboratorioFila(**datos.model_dump())
    db.add(laboratorio)
    db.flush()
    registrar(
        db,
        usuario_id=actual.id,
        accion="laboratorio_creado",
        entidad="laboratorio",
        entidad_id=laboratorio.id,
        detalle={"cohorte_id": str(datos.cohorte_id)},
        ip=seguridad.ip_de(request),
    )
    db.commit()
    return _laboratorio(laboratorio)


@ruta(router, "GET", "/api/laboratorios/{laboratorio_id}", response_model=Laboratorio)
def ver_laboratorio(laboratorio_id: uuid.UUID, db: Db) -> Laboratorio:
    return _laboratorio(buscar_laboratorio(db, laboratorio_id))


@ruta(router, "PATCH", "/api/laboratorios/{laboratorio_id}", response_model=Laboratorio)
def editar_laboratorio(
    request: Request, laboratorio_id: uuid.UUID, datos: LaboratorioEditar, actual: Actual, db: Db
) -> Laboratorio:
    laboratorio = buscar_laboratorio(db, laboratorio_id)
    cambios = []
    for campo, valor in datos.model_dump(exclude_none=True).items():
        anterior = getattr(laboratorio, campo)
        if anterior != valor:
            setattr(laboratorio, campo, valor)
            cambios.append(
                {"campo": campo, "anterior": _para_auditoria(anterior), "nuevo": _para_auditoria(valor)}
            )
    if cambios:
        registrar(
            db,
            usuario_id=actual.id,
            accion="laboratorio_editado",
            entidad="laboratorio",
            entidad_id=laboratorio.id,
            detalle={"cambios": cambios},
            ip=seguridad.ip_de(request),
        )
        db.commit()
    return _laboratorio(laboratorio)
