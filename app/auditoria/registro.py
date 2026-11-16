"""Guardar acciones en la auditoría (OWASP A09)."""

import ipaddress
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.modelos import Auditoria

# Nombres de datos que nunca se guardan en la auditoría. Son nombres exactos: así
# `sha256` de una evidencia o `debe_cambiar_contrasena` sí se pueden auditar.
PROHIBIDOS = frozenset(
    {
        "contrasena",
        "hash_contrasena",
        "actual",
        "nueva",
        "clave",
        "password",
        "token",
        "cookie",
        "secreto",
        "llave",
        "apikey",
    }
)
TERMINACIONES_PROHIBIDAS = ("api_key", "_token", "_secreto", "password")


def _es_secreto(nombre: str) -> bool:
    nombre = nombre.lower()
    return nombre in PROHIBIDOS or nombre.endswith(TERMINACIONES_PROHIBIDAS)


def revisar_detalle(detalle: Any) -> None:
    """Lanza ValueError si el detalle trae algo que parece un secreto."""
    if isinstance(detalle, dict):
        for llave, valor in detalle.items():
            if _es_secreto(str(llave)) or (
                llave == "campo" and isinstance(valor, str) and _es_secreto(valor)
            ):
                raise ValueError(f"No se guarda '{llave}' en la auditoría: parece un secreto.")
            revisar_detalle(valor)
    elif isinstance(detalle, list | tuple):
        for elemento in detalle:
            revisar_detalle(elemento)


def ip_valida(ip: str | None) -> str | None:
    try:
        return str(ipaddress.ip_address(ip)) if ip else None
    except ValueError:
        return None


def registrar(
    db: Session,
    *,
    usuario_id: uuid.UUID | None,
    accion: str,
    entidad: str,
    entidad_id: str | uuid.UUID | None = None,
    detalle: dict[str, Any] | None = None,
    ip: str | None = None,
) -> Auditoria:
    """Agrega una fila a la auditoría. No hace commit: va en la misma transacción que el cambio."""
    detalle = detalle or {}
    revisar_detalle(detalle)
    fila = Auditoria(
        usuario_id=usuario_id,
        accion=accion,
        entidad=entidad,
        entidad_id=str(entidad_id) if entidad_id is not None else None,
        detalle=detalle,
        ip=ip_valida(ip),
    )
    db.add(fila)
    return fila
