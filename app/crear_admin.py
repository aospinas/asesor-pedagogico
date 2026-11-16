"""Crea el primer administrador. Se corre una sola vez, a mano:

    python -m app.crear_admin

Pide los datos por teclado para que la contraseña no quede escrita en ningún
archivo ni en el historial de la terminal.

Usa la base de DATABASE_URL. Para producción (Render gratis no tiene consola) se
corre desde el PC con DATABASE_URL apuntando a Supabase solo en esa terminal.
"""

import getpass
import sys

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.seguridad import crear_hash
from app.auditoria.registro import registrar
from app.db import BaseNoDisponible, motor
from app.esquemas import Rol, UsuarioCrear
from app.mensajes import explicar
from app.modelos import Usuario


def crear_administrador(db: Session, nombre: str, correo: str, contrasena: str) -> Usuario:
    """Valida los datos con el contrato y guarda el administrador. Lanza ValueError si ya existe."""
    datos = UsuarioCrear(nombre=nombre, correo=correo, contrasena=contrasena, rol=Rol.ADMINISTRADOR)
    if db.scalar(select(Usuario.id).where(Usuario.correo == datos.correo)) is not None:
        raise ValueError("Ya existe un usuario con ese correo.")
    usuario = Usuario(
        nombre=datos.nombre,
        correo=datos.correo,
        hash_contrasena=crear_hash(datos.contrasena),
        rol=Rol.ADMINISTRADOR.value,
        debe_cambiar_contrasena=False,  # la escribió la misma persona
    )
    db.add(usuario)
    db.flush()
    registrar(db, usuario_id=None, accion="administrador_creado", entidad="usuario", entidad_id=usuario.id)
    db.commit()
    return usuario


def main() -> int:
    nombre = input("Nombre: ")
    correo = input("Correo: ")
    contrasena = getpass.getpass("Contraseña (mínimo 10 caracteres, no se muestra): ")
    if contrasena != getpass.getpass("Repite la contraseña: "):
        print("Las contraseñas no coinciden.")
        return 1
    try:
        with Session(motor(), expire_on_commit=False) as db:
            usuario = crear_administrador(db, nombre, correo, contrasena)
    except ValidationError as error:
        for e in error.errors(include_input=False):
            explicado = explicar(e)
            print(f"- {explicado['campo']}: {explicado['mensaje']}")
        return 1
    except ValueError as error:
        print(error)
        return 1
    except (BaseNoDisponible, OperationalError):
        print("No se pudo conectar a la base de datos. Revisa DATABASE_URL y que la base esté encendida.")
        return 1
    print(f"Administrador creado: {usuario.correo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
