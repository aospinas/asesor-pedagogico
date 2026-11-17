"""Tablas de la base de datos (SRS sección 8).

Por ahora: usuarios, intentos de sesión, auditoría, cohortes, laboratorios y rúbricas.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
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


class Cohorte(Base):
    __tablename__ = "cohortes"
    __table_args__ = (UniqueConstraint("nombre", "periodo", name="uq_cohortes_nombre_periodo"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    nombre: Mapped[str] = mapped_column(String(80))
    periodo: Mapped[str] = mapped_column(String(40))
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)


class Laboratorio(Base):
    __tablename__ = "laboratorios"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    cohorte_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cohortes.id"), index=True)
    titulo: Mapped[str] = mapped_column(String(160))
    descripcion: Mapped[str] = mapped_column(Text)
    objetivos: Mapped[str] = mapped_column(Text)
    temas_ia: Mapped[list[str]] = mapped_column(JSON, default=list)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)


class Rubrica(Base):
    """Una por laboratorio. La versión vigente es la de número más alto (D-16)."""

    __tablename__ = "rubricas"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    laboratorio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("laboratorios.id"), unique=True)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)


class RubricaVersion(Base):
    """Versiones inmutables (RF-06): nunca se editan ni se borran, se crea la siguiente."""

    __tablename__ = "rubrica_versiones"
    __table_args__ = (UniqueConstraint("rubrica_id", "numero", name="uq_rubrica_versiones_numero"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    rubrica_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rubricas.id"), index=True)
    numero: Mapped[int] = mapped_column(Integer)
    estructura: Mapped[dict[str, Any]] = mapped_column(JSON)
    valida: Mapped[bool] = mapped_column(Boolean)
    errores: Mapped[list[str]] = mapped_column(JSON, default=list)
    # De dónde salió: json, pdf, docx, texto o editor. Si pasó por la IA, con qué prompt y modelo.
    origen: Mapped[str] = mapped_column(String(10))
    archivo_sha256: Mapped[str | None] = mapped_column(String(64), default=None)
    prompt_version: Mapped[str | None] = mapped_column(String(60), default=None)
    modelo: Mapped[str | None] = mapped_column(String(120), default=None)
    tokens_entrada: Mapped[int | None] = mapped_column(Integer, default=None)
    tokens_salida: Mapped[int | None] = mapped_column(Integer, default=None)
    creada_por: Mapped[uuid.UUID] = mapped_column(ForeignKey("usuarios.id"))
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)
