"""Contraseñas, sesión y control de acceso por rol (RNF-06, OWASP A01 y A07).

Toda ruta se registra con `ruta(...)`, que busca sus roles en la tabla de
`app/api/rutas.py`. Si la ruta no está en la tabla, la app no arranca.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.api.rutas import RUTAS, Ruta
from app.auditoria.registro import registrar
from app.config import ajustes
from app.db import obtener_db
from app.esquemas import MiSesion, Rol, UsuarioPublico
from app.modelos import Usuario

ALGORITMO = "HS256"
INTENTOS_POR_IP_POR_MINUTO = 30

NO_AUTENTICADO = "Inicia sesión para continuar."
SIN_PERMISO = "No tienes permiso para hacer esto."
DEBE_CAMBIAR = "Debes cambiar tu contraseña antes de continuar."

# Lo único que puede hacer quien todavía tiene la contraseña temporal.
PERMITIDAS_CON_CLAVE_TEMPORAL = {("GET", "/api/yo"), ("PUT", "/api/yo/contrasena"), ("DELETE", "/api/sesion")}

_TABLA = {(r.metodo, r.ruta): r for r in RUTAS}

# key_style="endpoint": el cupo se cuenta por ruta (`/api/portafolio/{estudiante_id}`) y no
# por la dirección exacta. Con "url" (lo que trae slowapi), cada id tenía su propio
# contador y probar ids al azar no tenía límite (cuarta revisión).
limitador = Limiter(key_func=get_remote_address, key_style="endpoint")

Db = Annotated[Session, Depends(obtener_db)]


def ahora() -> datetime:
    return datetime.now(UTC)


def con_zona(fecha: datetime | None) -> datetime | None:
    """SQLite devuelve las fechas sin zona horaria; aquí siempre se trabaja en UTC."""
    if fecha is not None and fecha.tzinfo is None:
        return fecha.replace(tzinfo=UTC)
    return fecha


# ---------- Contraseñas ----------


def crear_hash(contrasena: str) -> str:
    sal = bcrypt.gensalt(rounds=ajustes().bcrypt_rondas)
    return bcrypt.hashpw(contrasena.encode("utf-8"), sal).decode("ascii")


def clave_correcta(contrasena: str, resumen: str) -> bool:
    try:
        return bcrypt.checkpw(contrasena.encode("utf-8"), resumen.encode("ascii"))
    except ValueError:
        return False


# ---------- Sesión (JWT en cookie httpOnly) ----------


def crear_token(usuario: Usuario, minutos: int | None = None) -> str:
    minutos = ajustes().sesion_minutos if minutos is None else minutos
    datos = {
        "sub": str(usuario.id),
        "ver": usuario.version_sesion,
        "iat": ahora(),
        "exp": ahora() + timedelta(minutes=minutos),
    }
    return jwt.encode(datos, ajustes().jwt_secreto, algorithm=ALGORITMO)


def nombre_cookie() -> str:
    # En producción el prefijo __Host- hace que el navegador solo la acepte por HTTPS
    # y para este dominio exacto.
    return "__Host-sesion" if ajustes().en_produccion else "sesion"


def poner_cookie(respuesta: Response, usuario: Usuario) -> None:
    respuesta.set_cookie(
        nombre_cookie(),
        crear_token(usuario),
        max_age=ajustes().sesion_minutos * 60,
        httponly=True,
        secure=ajustes().en_produccion,
        samesite="lax",
        path="/",
    )


def quitar_cookie(respuesta: Response) -> None:
    respuesta.delete_cookie(
        nombre_cookie(), path="/", httponly=True, secure=ajustes().en_produccion, samesite="lax"
    )


def _leer_token(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    try:
        return jwt.decode(
            token,
            ajustes().jwt_secreto,
            algorithms=[ALGORITMO],
            options={"require": ["sub", "ver", "exp"]},
        )
    except jwt.InvalidTokenError:
        return None


def clave_de_usuario(request: Request) -> str:
    """Clave para los límites de frecuencia: el usuario de la sesión, o la IP si no hay.

    Detrás del proxy de Render todos llegan con la misma IP: con la IP como clave, un
    curso entero compartiría el mismo cupo y un solo estudiante podría gastarlo."""
    datos = _leer_token(request.cookies.get(nombre_cookie()))
    if datos and isinstance(datos.get("sub"), str):
        return "usuario:" + datos["sub"]
    return "ip:" + (ip_de(request) or "desconocida")


def tiene_sesion_firmada(request: Request) -> bool:
    """¿Trae una cookie de sesión firmada por la app y sin vencer? No consulta la base.

    Sirve para frenar en el middleware las subidas grandes de quien no tiene cuenta,
    antes de recibirlas. La revisión completa (usuario activo, rol) va después."""
    return _leer_token(request.cookies.get(nombre_cookie())) is not None


def usuario_actual(request: Request, db: Db) -> Usuario:
    """El usuario de la sesión. Se lee de la base en cada petición: el rol nunca viene del navegador."""
    datos = _leer_token(request.cookies.get(nombre_cookie()))
    try:
        usuario = db.get(Usuario, uuid.UUID(datos["sub"])) if datos else None
    except (ValueError, TypeError):
        usuario = None
    # `type(...) is int` y no `==`: en Python False == 0, y un token con "ver": false no debe valer.
    if (
        usuario is None
        or not usuario.activo
        or type(datos["ver"]) is not int
        or usuario.version_sesion != datos["ver"]
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, NO_AUTENTICADO)
    return usuario


Actual = Annotated[Usuario, Depends(usuario_actual)]


def _exigir(definicion: Ruta):
    def revisar(request: Request, usuario: Actual, db: Db) -> None:
        if usuario.rol not in {rol.value for rol in definicion.roles}:
            # Queda en la auditoría: sirve para ver si alguien anda probando rutas ajenas.
            registrar(
                db,
                usuario_id=usuario.id,
                accion="acceso_denegado",
                entidad="ruta",
                detalle={"metodo": definicion.metodo, "ruta": definicion.ruta, "rol": usuario.rol},
                ip=ip_de(request),
            )
            db.commit()
            raise HTTPException(status.HTTP_403_FORBIDDEN, SIN_PERMISO)
        clave = (definicion.metodo, definicion.ruta)
        if usuario.debe_cambiar_contrasena and clave not in PERMITIDAS_CON_CLAVE_TEMPORAL:
            raise HTTPException(status.HTTP_403_FORBIDDEN, DEBE_CAMBIAR)

    return revisar


def ruta(router: APIRouter, metodo: str, camino: str, **opciones: Any):
    """Registra una ruta con los roles que dice la tabla. Falla si la ruta no está en la tabla."""
    definicion = _TABLA[metodo, camino]
    permisos = [] if definicion.publica else [Depends(_exigir(definicion))]
    return router.api_route(camino, methods=[metodo], dependencies=permisos, **opciones)


# ---------- Respuestas ----------


def publico(usuario: Usuario) -> UsuarioPublico:
    return UsuarioPublico(
        id=usuario.id,
        nombre=usuario.nombre,
        correo=usuario.correo,
        rol=Rol(usuario.rol),
        activo=usuario.activo,
        foto_url=usuario.foto_url,
    )


def mi_sesion(usuario: Usuario) -> MiSesion:
    return MiSesion(usuario=publico(usuario), debe_cambiar_contrasena=usuario.debe_cambiar_contrasena)


def ip_de(request: Request) -> str | None:
    return request.client.host if request.client else None
