"""Preparación común de las pruebas.

Las variables se fijan ANTES de importar la app para que las pruebas nunca
usen el .env del PC ni la base de datos real: corren en SQLite en memoria.
"""

import os

os.environ.update(
    ENTORNO="pruebas",
    DATABASE_URL="sqlite+pysqlite:///:memory:",
    JWT_SECRETO="secreto-solo-para-pruebas-" + "x" * 32,
    BCRYPT_RONDAS="4",
    ORIGENES_PERMITIDOS="http://localhost:5173",
    SESION_MINUTOS="480",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.api import seguridad  # noqa: E402
from app.db import Base, obtener_db  # noqa: E402
from app.main import app  # noqa: E402
from app.modelos import Usuario  # noqa: E402

CLAVE = "clave-segura-1"


@pytest.fixture
def motor():
    # Por defecto SQLite en memoria. Para correr lo mismo contra PostgreSQL (antes de un PR):
    #   PRUEBAS_DATABASE_URL=postgresql+psycopg://asesor:asesor_local@127.0.0.1:5432/asesor_pruebas
    # Usa una base aparte: estas pruebas BORRAN las tablas en cada prueba.
    en_postgres = os.environ.get("PRUEBAS_DATABASE_URL")
    if en_postgres:
        assert en_postgres.rsplit("/", 1)[-1].endswith("_pruebas"), (
            "La base de pruebas debe terminar en _pruebas"
        )
        motor = create_engine(en_postgres)
        Base.metadata.drop_all(motor)
    else:
        motor = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    Base.metadata.create_all(motor)

    def _db():
        with Session(motor, expire_on_commit=False) as sesion:
            yield sesion

    app.dependency_overrides[obtener_db] = _db
    seguridad.limitador.reset()
    yield motor
    app.dependency_overrides.clear()
    motor.dispose()


@pytest.fixture
def db(motor):
    with Session(motor, expire_on_commit=False) as sesion:
        yield sesion


@pytest.fixture
def nuevo_cliente(motor):
    """Crea navegadores separados: cada uno guarda su propia cookie."""
    abiertos = []

    def _nuevo(ip: str = "testclient") -> TestClient:
        cliente = TestClient(app, client=(ip, 50000))
        abiertos.append(cliente)
        return cliente

    yield _nuevo
    for cliente in abiertos:
        cliente.close()


@pytest.fixture
def cliente(nuevo_cliente):
    return nuevo_cliente()


@pytest.fixture
def crear_usuario(db):
    def _crear(rol="estudiante", correo=None, contrasena=CLAVE, activo=True, debe_cambiar=False) -> Usuario:
        usuario = Usuario(
            nombre=f"Persona {rol}",
            correo=correo or f"{rol}@umanizales.edu.co",
            hash_contrasena=seguridad.crear_hash(contrasena),
            rol=rol,
            activo=activo,
            debe_cambiar_contrasena=debe_cambiar,
        )
        db.add(usuario)
        db.commit()
        return usuario

    return _crear


@pytest.fixture
def entrar(nuevo_cliente, crear_usuario):
    """Crea un usuario del rol pedido y devuelve un navegador con la sesión abierta."""

    def _entrar(rol="estudiante", **datos) -> TestClient:
        usuario = crear_usuario(rol, **datos)
        cliente = nuevo_cliente()
        r = cliente.post(
            "/api/sesion", json={"correo": usuario.correo, "contrasena": datos.get("contrasena", CLAVE)}
        )
        assert r.status_code == 200, r.text
        cliente.usuario = usuario
        return cliente

    return _entrar
