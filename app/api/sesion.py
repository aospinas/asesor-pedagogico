"""Iniciar y cerrar sesión, ver mis datos y cambiar mi contraseña (RF-01, CU-01)."""

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.api import intentos, seguridad
from app.api.intentos import Estado
from app.api.seguridad import Actual, Db, limitador, ruta
from app.auditoria.registro import registrar
from app.esquemas import CambioContrasena, Credenciales, MiSesion
from app.modelos import Usuario

router = APIRouter()

DATOS_MALOS = "Correo o contraseña incorrectos."
BLOQUEADO = "Demasiados intentos. Espera unos minutos y vuelve a intentar."
LIMITE_POR_IP = f"{seguridad.INTENTOS_POR_IP_POR_MINUTO}/minute"

# Se compara contra este resumen cuando el correo no existe, para que la respuesta
# tarde lo mismo y no se pueda adivinar qué correos están registrados.
_RESUMEN_DE_RELLENO: str | None = None


def _relleno() -> str:
    global _RESUMEN_DE_RELLENO
    if _RESUMEN_DE_RELLENO is None:
        _RESUMEN_DE_RELLENO = seguridad.crear_hash("relleno-que-nadie-usa")
    return _RESUMEN_DE_RELLENO


@ruta(router, "POST", "/api/sesion", response_model=MiSesion)
@limitador.limit(LIMITE_POR_IP)
def iniciar_sesion(request: Request, response: Response, datos: Credenciales, db: Db) -> MiSesion:
    ip = seguridad.ip_de(request)

    # El intento se anota antes de revisar la clave. Vale igual si el correo no existe:
    # así la respuesta es la misma y no revela qué correos están registrados.
    estado = intentos.reservar(db, datos.correo, ip)
    if estado is Estado.BLOQUEADO:
        registrar(
            db,
            usuario_id=None,
            accion="sesion_bloqueada",
            entidad="usuario",
            detalle={"correo": datos.correo},
            ip=ip,
        )
        db.commit()
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, BLOQUEADO)

    usuario = db.scalar(select(Usuario).where(Usuario.correo == datos.correo))
    resumen = usuario.hash_contrasena if usuario else _relleno()
    correcta = seguridad.clave_correcta(datos.contrasena, resumen)

    if usuario is None or not correcta or not usuario.activo:
        registrar(
            db,
            usuario_id=usuario.id if usuario else None,
            accion="sesion_fallida",
            entidad="usuario",
            entidad_id=usuario.id if usuario else None,
            detalle={"correo": datos.correo, "bloqueado": estado is Estado.ULTIMO},
            ip=ip,
        )
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, DATOS_MALOS)

    intentos.limpiar(db, datos.correo, ip or "")
    registrar(
        db, usuario_id=usuario.id, accion="sesion_iniciada", entidad="usuario", entidad_id=usuario.id, ip=ip
    )
    db.commit()

    seguridad.poner_cookie(response, usuario)
    return seguridad.mi_sesion(usuario)


@ruta(router, "DELETE", "/api/sesion", status_code=status.HTTP_204_NO_CONTENT)
def cerrar_sesion(request: Request, response: Response, usuario: Actual, db: Db) -> None:
    # Subir la versión deja sin valor el token, aunque alguien lo haya copiado.
    # También cierra las sesiones de este usuario en otros equipos.
    usuario.version_sesion += 1
    registrar(
        db,
        usuario_id=usuario.id,
        accion="sesion_cerrada",
        entidad="usuario",
        entidad_id=usuario.id,
        ip=seguridad.ip_de(request),
    )
    db.commit()
    seguridad.quitar_cookie(response)


@ruta(router, "GET", "/api/yo", response_model=MiSesion)
def ver_mis_datos(usuario: Actual) -> MiSesion:
    return seguridad.mi_sesion(usuario)


@ruta(router, "PUT", "/api/yo/contrasena", status_code=status.HTTP_204_NO_CONTENT)
@limitador.limit(LIMITE_POR_IP)
def cambiar_mi_contrasena(
    request: Request, response: Response, datos: CambioContrasena, usuario: Actual, db: Db
) -> None:
    ip = seguridad.ip_de(request)

    # Adivinar la clave actual desde una sesión abierta tiene el mismo tope que entrar.
    estado = intentos.reservar(db, usuario.correo, ip)
    correcta = estado is not Estado.BLOQUEADO and seguridad.clave_correcta(
        datos.actual, usuario.hash_contrasena
    )
    if not correcta:
        cerrar = estado is not Estado.PERMITIDO
        if cerrar:
            usuario.version_sesion += 1  # demasiados intentos: se cierra la sesión
        registrar(
            db,
            usuario_id=usuario.id,
            accion="contrasena_fallida",
            entidad="usuario",
            entidad_id=usuario.id,
            detalle={"sesion_cerrada": cerrar},
            ip=ip,
        )
        db.commit()
        if estado is Estado.BLOQUEADO:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, BLOQUEADO)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La contraseña actual no es correcta.")

    if datos.nueva == datos.actual:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La contraseña nueva debe ser distinta a la actual.")

    usuario.hash_contrasena = seguridad.crear_hash(datos.nueva)
    usuario.debe_cambiar_contrasena = False
    usuario.version_sesion += 1  # cierra las sesiones abiertas en otros equipos
    intentos.limpiar(db, usuario.correo, ip or "")
    registrar(
        db,
        usuario_id=usuario.id,
        accion="contrasena_cambiada",
        entidad="usuario",
        entidad_id=usuario.id,
        ip=ip,
    )
    db.commit()
    seguridad.poner_cookie(response, usuario)
