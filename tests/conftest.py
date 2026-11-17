"""Preparación común de las pruebas.

Las variables se fijan ANTES de importar la app para que las pruebas nunca
usen el .env del PC ni la base de datos real: corren en SQLite en memoria.
"""

import json
import os

os.environ.update(
    ENTORNO="pruebas",
    DATABASE_URL="sqlite+pysqlite:///:memory:",
    JWT_SECRETO="secreto-solo-para-pruebas-" + "x" * 32,
    BCRYPT_RONDAS="4",
    ORIGENES_PERMITIDOS="http://localhost:5173",
    SESION_MINUTOS="480",
    # Sin modelo: si alguna prueba llegara a la IA real, falla en vez de gastar tokens.
    LLM_PROVIDER="openai",
    LLM_MODEL="",
    LLM_API_KEY="",
    LLM_BASE_URL="https://api.openai.com/v1",
)

import pytest  # noqa: E402
from datos_prueba import rubrica_de_prueba as _rubrica_de_prueba  # noqa: E402
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
    # El evaluador corre en segundo plano con su propia sesión: que use la base de la prueba.
    from app.api import evaluaciones

    app.dependency_overrides[evaluaciones.obtener_fabrica] = lambda: (
        lambda: Session(motor, expire_on_commit=False)
    )
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


# ---------- Laboratorios y rúbricas ----------


@pytest.fixture
def rubrica_de_prueba():
    """Devuelve la función que arma una rúbrica de prueba."""
    return _rubrica_de_prueba


@pytest.fixture
def laboratorio(db):
    """Una cohorte con un laboratorio, creados directo en la base."""
    from app.modelos import Cohorte, Laboratorio

    cohorte = Cohorte(nombre="Cohorte 1", periodo="2026-2")
    db.add(cohorte)
    db.flush()
    lab = Laboratorio(
        cohorte_id=cohorte.id,
        titulo="Laboratorio 1",
        descripcion="Agentes con herramientas",
        objetivos="Construir un agente",
        temas_ia=["agentes"],
    )
    db.add(lab)
    db.commit()
    return lab


@pytest.fixture
def rubrica_lista(db, laboratorio, crear_usuario):
    """El laboratorio con una rúbrica válida y confirmada: ya se puede entregar."""
    from app.esquemas import RubricaEstructura
    from app.rubricas import versiones

    autor = crear_usuario("docente", correo="autor.rubrica@umanizales.edu.co")
    version = versiones.guardar_version(
        db,
        laboratorio.id,
        RubricaEstructura.model_validate(_rubrica_de_prueba()),
        origen="editor",
        creada_por=autor.id,
    )
    db.commit()
    return version


@pytest.fixture
def almacen(motor, tmp_path):
    """Los archivos van a una carpeta temporal de la prueba (almacén local)."""
    from app.almacen import AlmacenLocal
    from app.api import entregas

    local = AlmacenLocal(tmp_path / "almacen")
    app.dependency_overrides[entregas._almacen] = lambda: local
    return local


@pytest.fixture
def ia_simulada(motor):
    """Reemplaza la IA: devuelve lo que la prueba ponga en `respuesta` y guarda lo que se le pidió."""
    from app.api import rubricas
    from app.ia.cliente import Uso, validar_respuesta

    class IASimulada:
        def __init__(self):
            self.respuesta: dict | str | Exception = _rubrica_de_prueba()
            self.pedidos: list[dict] = []

        def __call__(self, sistema, usuario, esquema):
            self.pedidos.append({"sistema": sistema, "usuario": usuario})
            if isinstance(self.respuesta, Exception):
                raise self.respuesta
            texto = self.respuesta if isinstance(self.respuesta, str) else json.dumps(self.respuesta)
            return validar_respuesta(texto, esquema), Uso(modelo="simulado", entrada=100, salida=50)

    simulada = IASimulada()
    app.dependency_overrides[rubricas.obtener_ia] = lambda: simulada
    return simulada


# ---------- Evaluador ----------


@pytest.fixture
def ia_evaluador(motor):
    """IA simulada para el evaluador. Por defecto propone 'alto' en cada criterio, citando un
    pedazo real del informe. `respuestas[criterio_id]` es una lista que se va gastando: cada
    elemento es un dict (la respuesta), un str (texto crudo) o una excepción."""
    import re

    from archivos_prueba import TEXTO_INFORME

    from app.api import evaluaciones
    from app.esquemas import ConfigIA, DescripcionImagen
    from app.ia.cliente import Uso, validar_respuesta

    class IAEvaluador:
        def __init__(self):
            self.respuestas: dict[str, list] = {}
            self.descripcion = "Captura de la consola: el agente movió 3 archivos a la carpeta imagenes."
            self.error_imagen: Exception | None = None  # si se pone, describir la imagen falla
            self.pedidos: list[dict] = []
            self.uso = Uso(modelo="modelo-prueba", entrada=1000, salida=200)

        def correcta(self, criterio_id: str, nivel: str = "alto") -> dict:
            return {
                "criterio_id": criterio_id,
                "nivel_id": nivel,
                "justificacion": "El informe explica cómo el agente usa herramientas.",
                "evidencias": [
                    {"archivo": "informe.pdf", "ubicacion": "página 1", "fragmento": TEXTO_INFORME[:60]}
                ],
                "fortalezas": ["Explica el agente con claridad"],
                "debilidades": ["Faltan pruebas"],
                "recomendaciones": ["Agregar pruebas unitarias"],
            }

        def __call__(self, sistema, usuario, esquema, *, config=None, imagenes=None, maximo_tokens=None):
            self.pedidos.append(
                {
                    "sistema": sistema,
                    "usuario": usuario,
                    "esquema": esquema,
                    "imagenes": imagenes,
                    "config": config,
                }
            )
            if esquema is DescripcionImagen:
                if self.error_imagen is not None:
                    raise self.error_imagen
                return DescripcionImagen(descripcion=self.descripcion), self.uso
            criterio_id = re.search(r'"id": "([^"]+)"', usuario).group(1)
            pendientes = self.respuestas.get(criterio_id)
            respuesta = pendientes.pop(0) if pendientes else self.correcta(criterio_id)
            if isinstance(respuesta, Exception):
                raise respuesta
            texto = respuesta if isinstance(respuesta, str) else json.dumps(respuesta)
            return validar_respuesta(texto, esquema), self.uso

    simulada = IAEvaluador()
    config = ConfigIA(proveedor="openai", modelo="modelo-prueba", base_url="https://api.openai.com/v1")
    app.dependency_overrides[evaluaciones.obtener_ia] = lambda: simulada
    app.dependency_overrides[evaluaciones.obtener_config] = lambda: config
    app.dependency_overrides[evaluaciones.obtener_bajar_github] = lambda: simulada_github
    simulada.github = simulada_github
    return simulada


class _GitHubSimulado:
    """Reemplaza la descarga de GitHub: devuelve un ZIP de prueba o lanza lo que se le ponga."""

    def __init__(self):
        self.respuesta = None
        self.pedidos: list[str] = []

    def __call__(self, enlace: str) -> bytes:
        from archivos_prueba import zip_codigo

        self.pedidos.append(enlace)
        if isinstance(self.respuesta, Exception):
            raise self.respuesta
        return self.respuesta or zip_codigo({"repo-main/agente.py": "def actuar():\n    return 'ok'\n"})


simulada_github = _GitHubSimulado()


@pytest.fixture(autouse=True)
def _github_limpio():
    simulada_github.respuesta = None
    simulada_github.pedidos.clear()


class _EjecutorInmediato:
    """En las pruebas la evaluación corre ahí mismo: termina antes de que vuelva la respuesta."""

    def __init__(self):
        self.apagado = False

    def submit(self, funcion, *args):
        if self.apagado:
            raise RuntimeError("cannot schedule new futures after shutdown")
        funcion(*args)

    def shutdown(self, wait=True, cancel_futures=False):
        self.apagado = True


@pytest.fixture(autouse=True)
def _evaluador_inmediato(monkeypatch):
    from app.evaluador import motor as motor_evaluador

    monkeypatch.setattr(motor_evaluador, "_EJECUTOR", _EjecutorInmediato())
    motor_evaluador._EN_COLA.clear()
    motor_evaluador._CORRIENDO.clear()
