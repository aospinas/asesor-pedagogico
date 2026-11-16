"""Bloqueo por intentos fallidos (OWASP A07): 5 intentos y 5 minutos de espera.

El intento se anota ANTES de revisar la contraseña y con la fila bloqueada en la
base. Así, aunque lleguen muchas peticiones al mismo tiempo, solo las primeras
cinco alcanzan a probar una contraseña.
"""

from datetime import timedelta
from enum import Enum

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api import seguridad
from app.modelos import IntentoSesion

INTENTOS_MAXIMOS = 5
MINUTOS_DE_BLOQUEO = 5
DIAS_PARA_BORRAR = 1


class Estado(Enum):
    PERMITIDO = "permitido"
    ULTIMO = "ultimo"  # se permite, pero si falla queda bloqueado
    BLOQUEADO = "bloqueado"


def _fila_con_candado(db: Session, correo: str, ip: str) -> IntentoSesion:
    consulta = (
        select(IntentoSesion)
        .where(IntentoSesion.correo == correo, IntentoSesion.ip == ip)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    fila = db.scalar(consulta)
    if fila is None:
        ahora = seguridad.ahora()
        # De paso se borran los intentos viejos para que la tabla no crezca sin fin.
        db.execute(
            delete(IntentoSesion).where(IntentoSesion.actualizado < ahora - timedelta(days=DIAS_PARA_BORRAR))
        )
        try:
            with db.begin_nested():
                db.add(IntentoSesion(correo=correo, ip=ip, intentos=0, actualizado=ahora))
        except IntegrityError:
            pass  # otra petición la creó en el mismo instante: se usa esa
        fila = db.scalar(consulta)
    return fila


def reservar(db: Session, correo: str, ip: str | None) -> Estado:
    """Anota un intento y dice si se puede seguir. Hace commit para soltar el candado."""
    ahora = seguridad.ahora()
    fila = _fila_con_candado(db, correo, ip or "")

    hasta = seguridad.con_zona(fila.bloqueado_hasta)
    if hasta is not None and hasta > ahora:
        db.commit()
        return Estado.BLOQUEADO
    if hasta is not None:  # el bloqueo ya venció
        fila.bloqueado_hasta = None
        fila.intentos = 0

    fila.intentos += 1
    fila.actualizado = ahora
    estado = Estado.PERMITIDO
    if fila.intentos >= INTENTOS_MAXIMOS:
        fila.bloqueado_hasta = ahora + timedelta(minutes=MINUTOS_DE_BLOQUEO)
        fila.intentos = 0
        estado = Estado.ULTIMO
    db.commit()
    return estado


def limpiar(db: Session, correo: str, ip: str | None = None) -> None:
    """Borra la cuenta de intentos. Sin IP, borra todas las de ese correo. No hace commit."""
    consulta = delete(IntentoSesion).where(IntentoSesion.correo == correo)
    if ip is not None:
        consulta = consulta.where(IntentoSesion.ip == ip)
    db.execute(consulta)
