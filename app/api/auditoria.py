"""Consulta del registro de auditoría. Solo para el administrador (OWASP A09)."""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.seguridad import Db, con_zona, ruta
from app.esquemas import RegistroAuditoria
from app.modelos import Auditoria

router = APIRouter()


@ruta(router, "GET", "/api/auditoria", response_model=list[RegistroAuditoria])
def ver_auditoria(db: Db, limite: Annotated[int, Query(ge=1, le=200)] = 100) -> list[RegistroAuditoria]:
    filas = db.scalars(select(Auditoria).order_by(Auditoria.fecha.desc(), Auditoria.id).limit(limite))
    return [
        RegistroAuditoria(
            id=f.id,
            usuario_id=f.usuario_id,
            accion=f.accion,
            entidad=f.entidad,
            entidad_id=f.entidad_id,
            detalle=f.detalle,
            ip=f.ip,
            fecha=con_zona(f.fecha),
        )
        for f in filas
    ]
