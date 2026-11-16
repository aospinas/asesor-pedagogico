"""Gestión de usuarios por el administrador (RF-02, CU-09)."""

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api import intentos, seguridad
from app.api.seguridad import Actual, Db, ruta
from app.auditoria.registro import registrar
from app.esquemas import ClaveTemporal, Rol, UsuarioCrear, UsuarioEditar, UsuarioPublico
from app.modelos import Usuario

router = APIRouter()

CORREO_REPETIDO = "Ya existe un usuario con ese correo."
NO_EXISTE = "Ese usuario no existe."
ADMINISTRADOR = Rol.ADMINISTRADOR.value


def _buscar(db: Db, usuario_id: uuid.UUID) -> Usuario:
    usuario = db.get(Usuario, usuario_id)
    if usuario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_EXISTE)
    return usuario


def _queda_otro_administrador(db: Db, usuario: Usuario) -> bool:
    """¿Hay otro administrador activo además de este? Bloquea las filas para que dos
    administradores no puedan quitarse el rol el uno al otro al mismo tiempo."""
    activos = db.scalars(
        select(Usuario)
        .where(Usuario.rol == ADMINISTRADOR, Usuario.activo.is_(True))
        .order_by(Usuario.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    return any(a.id != usuario.id for a in activos)


@ruta(router, "GET", "/api/usuarios", response_model=list[UsuarioPublico])
def listar_usuarios(db: Db) -> list[UsuarioPublico]:
    usuarios = db.scalars(select(Usuario).order_by(Usuario.nombre, Usuario.correo))
    return [seguridad.publico(u) for u in usuarios]


@ruta(router, "POST", "/api/usuarios", response_model=UsuarioPublico, status_code=status.HTTP_201_CREATED)
def crear_usuario(request: Request, datos: UsuarioCrear, actual: Actual, db: Db) -> UsuarioPublico:
    if db.scalar(select(Usuario.id).where(Usuario.correo == datos.correo)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, CORREO_REPETIDO)

    usuario = Usuario(
        nombre=datos.nombre,
        correo=datos.correo,
        hash_contrasena=seguridad.crear_hash(datos.contrasena),
        rol=datos.rol.value,
        debe_cambiar_contrasena=True,
    )
    db.add(usuario)
    try:
        db.flush()
    except IntegrityError:  # dos altas del mismo correo al mismo tiempo
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, CORREO_REPETIDO) from None

    registrar(
        db,
        usuario_id=actual.id,
        accion="usuario_creado",
        entidad="usuario",
        entidad_id=usuario.id,
        detalle={"rol": usuario.rol},
        ip=seguridad.ip_de(request),
    )
    db.commit()
    return seguridad.publico(usuario)


@ruta(router, "PATCH", "/api/usuarios/{usuario_id}", response_model=UsuarioPublico)
def editar_usuario(
    request: Request, usuario_id: uuid.UUID, datos: UsuarioEditar, actual: Actual, db: Db
) -> UsuarioPublico:
    usuario = _buscar(db, usuario_id)

    nuevos = datos.model_dump(exclude_none=True)
    if "rol" in nuevos:
        nuevos["rol"] = nuevos["rol"].value

    cambios = [
        {"campo": campo, "anterior": getattr(usuario, campo), "nuevo": valor}
        for campo, valor in nuevos.items()
        if getattr(usuario, campo) != valor
    ]
    campos = {c["campo"] for c in cambios}

    if usuario.id == actual.id and campos & {"rol", "activo"}:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "No puedes cambiar tu propio rol ni desactivar tu cuenta."
        )
    deja_de_administrar = (
        usuario.rol == ADMINISTRADOR
        and usuario.activo
        and (nuevos.get("rol", ADMINISTRADOR) != ADMINISTRADOR or nuevos.get("activo") is False)
    )
    if deja_de_administrar and not _queda_otro_administrador(db, usuario):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Debe quedar al menos un administrador activo.")

    if cambios:
        for cambio in cambios:
            setattr(usuario, cambio["campo"], cambio["nuevo"])
        if "activo" in campos and not usuario.activo:
            usuario.version_sesion += 1  # si lo reactivan, su sesión vieja no revive
        registrar(
            db,
            usuario_id=actual.id,
            accion="usuario_editado",
            entidad="usuario",
            entidad_id=usuario.id,
            detalle={"cambios": cambios},
            ip=seguridad.ip_de(request),
        )
        db.commit()
    return seguridad.publico(usuario)


@ruta(router, "POST", "/api/usuarios/{usuario_id}/clave-temporal", status_code=status.HTTP_204_NO_CONTENT)
def poner_clave_temporal(
    request: Request, usuario_id: uuid.UUID, datos: ClaveTemporal, actual: Actual, db: Db
) -> None:
    """Para quien olvidó su contraseña o quedó bloqueado. El usuario debe cambiarla al entrar."""
    usuario = _buscar(db, usuario_id)
    if usuario.id == actual.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Tu propia contraseña se cambia en tu perfil, con la clave actual."
        )

    usuario.hash_contrasena = seguridad.crear_hash(datos.contrasena)
    usuario.debe_cambiar_contrasena = True
    usuario.version_sesion += 1  # cierra las sesiones que tuviera abiertas
    intentos.limpiar(db, usuario.correo)  # y lo desbloquea
    registrar(
        db,
        usuario_id=actual.id,
        accion="clave_temporal_puesta",
        entidad="usuario",
        entidad_id=usuario.id,
        ip=seguridad.ip_de(request),
    )
    db.commit()
