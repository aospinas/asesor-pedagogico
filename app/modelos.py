"""Tablas de la base de datos (SRS sección 8).

Por ahora: usuarios, intentos de sesión, auditoría, cohortes, laboratorios, rúbricas,
entregas, evidencias, evaluaciones y la configuración de IA.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
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


class Entrega(Base):
    """Una entrega de un estudiante, amarrada a la versión de rúbrica con la que se evaluará (F2).

    Se puede entregar varias veces: cada entrega es una fila nueva y nada se borra.
    """

    __tablename__ = "entregas"
    # El mismo informe no entra dos veces en un laboratorio, ni con dos subidas al mismo tiempo.
    __table_args__ = (
        UniqueConstraint("estudiante_id", "laboratorio_id", "sha256_informe", name="uq_entregas_informe"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    estudiante_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("usuarios.id"), index=True)
    laboratorio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("laboratorios.id"), index=True)
    rubrica_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rubrica_versiones.id"))
    enlace_github: Mapped[str | None] = mapped_column(String(200), default=None)
    sha256_informe: Mapped[str] = mapped_column(String(64))
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora, index=True)


class Evidencia(Base):
    """Un archivo de la entrega con su huella SHA-256 y el texto que se le sacó (RF-09).

    `texto_extraido`:
    - PDF: {"paginas": [...], "recortado": bool}
    - diapositivas: {"paginas": [...], "formato": "pptx" | "pdf", "recortado": bool}
    - código: {"arbol": [...], "archivos": [{"ruta", "texto"}], "omitidos": [{"ruta", "motivo"}]}
    - imágenes: None (las describe el evaluador)
    `recortado` es True si el texto pasaba del tope y se cortó.
    """

    __tablename__ = "evidencias"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entrega_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entregas.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(20))
    nombre: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    tamano_bytes: Mapped[int] = mapped_column(Integer)
    tipo_mime: Mapped[str] = mapped_column(String(100))
    ruta_storage: Mapped[str] = mapped_column(String(300))
    # Se carga solo cuando hace falta (evaluar): puede pesar varios MB por archivo.
    # En las imágenes lo llena el evaluador con la descripción de la IA (se guarda para no
    # pagar dos veces): {"descripcion", "modelo", "prompt_version"}.
    texto_extraido: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None, deferred=True)
    # Lo que muestran las listas, calculado al subir: así no se lee el texto completo.
    resumen: Mapped[str | None] = mapped_column(String(300), default=None)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)


class Evaluacion(Base):
    """Una evaluación de una entrega con IA (RF-11 a RF-13, CU-04). La traza principal (C6).

    La nota la escribe el backend con app/evaluador/nota.py; la IA solo propone niveles.
    """

    __tablename__ = "evaluaciones"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entrega_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entregas.id"), index=True)
    rubrica_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rubrica_versiones.id"))
    lanzada_por: Mapped[uuid.UUID] = mapped_column(ForeignKey("usuarios.id"), index=True)
    estado: Mapped[str] = mapped_column(String(20), index=True)
    proveedor: Mapped[str] = mapped_column(String(20))
    modelo: Mapped[str] = mapped_column(String(120))
    version_prompt: Mapped[str] = mapped_column(String(60))
    nota_preliminar: Mapped[float | None] = mapped_column(Float, default=None)
    nota_final: Mapped[float | None] = mapped_column(Float, default=None)
    tokens_entrada: Mapped[int] = mapped_column(Integer, default=0)
    tokens_salida: Mapped[int] = mapped_column(Integer, default=0)
    costo_usd: Mapped[float] = mapped_column(Float, default=0)
    alerta_inyeccion: Mapped[bool] = mapped_column(Boolean, default=False)
    # Qué reglas del filtro de inyección saltaron (ids nuestros, nunca el texto del estudiante)
    reglas_inyeccion: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Aviso para el docente si algo no salió (texto nuestro, nunca la respuesta de la IA)
    aviso: Mapped[str | None] = mapped_column(String(300), default=None)
    # Cuántos motivos tiene para ir primero en la bandeja (cita no encontrada, alerta de
    # inyección, sin propuesta). Se guarda para ordenar y paginar en la base (D-21).
    prioridad: Mapped[int] = mapped_column(Integer, default=0, index=True)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora, index=True)
    actualizada: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)
    aprobada_por: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("usuarios.id"), default=None)
    fecha_aprobacion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    fecha_publicacion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class EvaluacionCriterio(Base):
    """Lo que propuso la IA para un criterio, con sus citas ya verificadas (RF-11, RF-12).

    nivel_ia es None cuando la IA falló 3 veces: el criterio queda "Sin propuesta".
    """

    __tablename__ = "evaluacion_criterios"
    __table_args__ = (UniqueConstraint("evaluacion_id", "criterio_id", name="uq_evaluacion_criterio"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    evaluacion_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluaciones.id"), index=True)
    criterio_id: Mapped[str] = mapped_column(String(40))
    orden: Mapped[int] = mapped_column(Integer)
    nivel_ia: Mapped[str | None] = mapped_column(String(40), default=None)
    nivel_final: Mapped[str | None] = mapped_column(String(40), default=None)
    justificacion: Mapped[str] = mapped_column(Text, default="")
    evidencias: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    fortalezas: Mapped[list[str]] = mapped_column(JSON, default=list)
    debilidades: Mapped[list[str]] = mapped_column(JSON, default=list)
    recomendaciones: Mapped[list[str]] = mapped_column(JSON, default=list)
    intentos: Mapped[int] = mapped_column(Integer, default=0)


class RevisionDocenteFila(Base):
    """Una acción del docente sobre una evaluación (RF-14), con el valor anterior y el nuevo.
    Es la traza que ve la pestaña "Traza" (RF-15). Nunca se edita ni se borra."""

    __tablename__ = "revisiones_docente"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    evaluacion_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluaciones.id"), index=True)
    docente_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("usuarios.id"))
    accion: Mapped[str] = mapped_column(String(30))
    criterio_id: Mapped[str | None] = mapped_column(String(40), default=None)
    valor_anterior: Mapped[str | None] = mapped_column(Text, default=None)
    valor_nuevo: Mapped[str | None] = mapped_column(Text, default=None)
    justificacion: Mapped[str | None] = mapped_column(Text, default=None)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)


class VerificacionCodigoFila(Base):
    """Un resultado del sandbox para una evaluación (RF-10, SRS sección 8). La salida trae
    texto del estudiante (rutas, lo que imprimen sus pruebas): se muestra como texto escapado y
    a la IA le llega como datos."""

    __tablename__ = "verificaciones_codigo"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    evaluacion_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluaciones.id"), index=True)
    orden: Mapped[int] = mapped_column(Integer)
    tipo: Mapped[str] = mapped_column(String(20))
    comando: Mapped[str] = mapped_column(String(500))
    codigo_salida: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salida: Mapped[str] = mapped_column(Text)
    duracion_ms: Mapped[int] = mapped_column(Integer)
    tiempo_agotado: Mapped[bool] = mapped_column(Boolean)


class ConfigIAFila(Base):
    """Proveedor y modelo de IA elegidos por el administrador (RF-19). La llave NO va aquí:
    vive en la variable LLM_API_KEY. Cada cambio es una fila nueva; manda la última."""

    __tablename__ = "config_ia"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    proveedor: Mapped[str] = mapped_column(String(20))
    modelo: Mapped[str] = mapped_column(String(120))
    base_url: Mapped[str] = mapped_column(String(300))
    # Precio por millón de tokens de ESTE modelo (RF-20). Vacío: se usan LLM_PRECIO_*.
    precio_entrada_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    precio_salida_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    actualizado_por: Mapped[uuid.UUID] = mapped_column(ForeignKey("usuarios.id"))
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora, index=True)
