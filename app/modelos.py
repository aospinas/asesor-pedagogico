"""Tablas de la base de datos (SRS sección 8). Por ahora: usuarios, intentos de sesión y auditoría."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _ahora() -> datetime:
    return datetime.now(UTC)


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    nombre: Mapped[str] = mapped_column(String(120))
    correo: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    hash_contrasena: Mapped[str] = mapped_column(String(100))
    rol: Mapped[str] = mapped_column(String(20))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    foto_url: Mapped[str | None] = mapped_column(String(500), default=None)
    # La clave que pone el administrador es temporal: el usuario la cambia al entrar.
    debe_cambiar_contrasena: Mapped[bool] = mapped_column(Boolean, default=True)
    # Sube al cambiar la contraseña, cerrar sesión o desactivar: las sesiones viejas dejan de servir.
    version_sesion: Mapped[int] = mapped_column(Integer, default=0)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)


class IntentoSesion(Base):
    """Intentos de entrar, contados por correo e IP (OWASP A07).

    Se cuenta aunque el correo no exista: así la respuesta no revela qué correos
    están registrados, y nadie puede bloquearle la cuenta a otro desde otra IP.
    """

    __tablename__ = "intentos_sesion"
    __table_args__ = (UniqueConstraint("correo", "ip", name="uq_intentos_sesion_correo_ip"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    correo: Mapped[str] = mapped_column(String(254))
    ip: Mapped[str] = mapped_column(String(45))
    intentos: Mapped[int] = mapped_column(Integer, default=0)
    bloqueado_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    actualizado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora, index=True)


class Auditoria(Base):
    """Quién hizo qué y cuándo. Solo se agregan filas: nunca se editan ni se borran."""

    __tablename__ = "auditoria"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    usuario_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("usuarios.id"), index=True, default=None)
    accion: Mapped[str] = mapped_column(String(60))
    entidad: Mapped[str] = mapped_column(String(60))
    entidad_id: Mapped[str | None] = mapped_column(String(60), default=None)
    detalle: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(45), default=None)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora, index=True)
