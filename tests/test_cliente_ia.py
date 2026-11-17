"""Cliente de IA con los 3 proveedores simulados (RF-19, fila C4 de la matriz del SRS)."""

import json
from types import SimpleNamespace

import pytest
from datos_prueba import rubrica_de_prueba

from app.config import Ajustes
from app.esquemas import ConfigIA, RubricaEstructura
from app.ia import cliente
from app.ia.cliente import ErrorIA, Imagen

OPENAI = ConfigIA(proveedor="openai", modelo="gpt-6-luna", base_url="https://api.openai.com/v1")
OPENROUTER = ConfigIA(proveedor="openrouter", modelo="algun/modelo", base_url="https://openrouter.ai/api/v1")
OLLAMA = ConfigIA(proveedor="ollama", modelo="llama", base_url="http://localhost:11434/v1")


class _SDKFalso:
    """Reemplaza al SDK de OpenAI: guarda con qué se creó y qué se le pidió."""

    creado: dict = {}
    pedido: dict = {}
    respuesta = None

    def __init__(self, **datos):
        _SDKFalso.creado = datos

        def crear(**pedido):
            _SDKFalso.pedido = pedido
            return _SDKFalso.respuesta

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=crear))


def _respuesta(datos: dict) -> SimpleNamespace:
    eleccion = SimpleNamespace(message=SimpleNamespace(content=json.dumps(datos)), finish_reason="stop")
    return SimpleNamespace(choices=[eleccion], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


@pytest.fixture
def sdk(monkeypatch):
    import openai

    def configurar(esfuerzo="low"):
        datos = Ajustes(llm_api_key="llave-real", llm_esfuerzo=esfuerzo)
        monkeypatch.setattr(cliente, "ajustes", lambda: datos)
        return datos

    monkeypatch.setattr(openai, "OpenAI", _SDKFalso)
    _SDKFalso.respuesta = _respuesta(rubrica_de_prueba())
    configurar()
    return configurar


@pytest.mark.parametrize("config", [OPENAI, OPENROUTER, OLLAMA], ids=["openai", "openrouter", "ollama"])
def test_los_tres_proveedores_responden_y_se_valida(sdk, config):
    resultado, uso = cliente.pedir_json("s", "u", RubricaEstructura, config=config)
    assert isinstance(resultado, RubricaEstructura)
    assert (uso.modelo, uso.entrada, uso.salida) == (config.modelo, 10, 5)
    assert _SDKFalso.creado["base_url"] == config.base_url
    assert _SDKFalso.creado["max_retries"] == 0


def test_a_ollama_nunca_va_la_llave_y_a_los_demas_si(sdk):
    cliente.pedir_json("s", "u", RubricaEstructura, config=OLLAMA)
    assert _SDKFalso.creado["api_key"] == "sin-llave"
    cliente.pedir_json("s", "u", RubricaEstructura, config=OPENROUTER)
    assert _SDKFalso.creado["api_key"] == "llave-real"


def test_openai_con_razonamiento_no_recibe_temperature(sdk):
    """Los modelos GPT-6 rechazan temperature si razonan (documentación de OpenAI, nov-2026)."""
    cliente.pedir_json("s", "u", RubricaEstructura, config=OPENAI)
    assert _SDKFalso.pedido["reasoning_effort"] == "low"
    assert "temperature" not in _SDKFalso.pedido
    assert "max_tokens" not in _SDKFalso.pedido
    assert _SDKFalso.pedido["max_completion_tokens"] > 0


def test_openai_sin_razonamiento_si_recibe_temperature(sdk):
    sdk(esfuerzo="none")
    cliente.pedir_json("s", "u", RubricaEstructura, config=OPENAI)
    assert _SDKFalso.pedido["reasoning_effort"] == "none"
    assert _SDKFalso.pedido["temperature"] == 0


def test_los_otros_proveedores_usan_max_tokens(sdk):
    cliente.pedir_json("s", "u", RubricaEstructura, config=OLLAMA)
    assert _SDKFalso.pedido["max_tokens"] > 0
    assert "reasoning_effort" not in _SDKFalso.pedido


def test_las_imagenes_van_como_data_url_y_no_como_enlace(sdk):
    cliente.pedir_json("s", "texto", RubricaEstructura, config=OPENAI, imagenes=[Imagen("QUJD", "image/png")])
    contenido = _SDKFalso.pedido["messages"][1]["content"]
    assert contenido[0] == {"type": "text", "text": "texto"}
    assert contenido[1]["image_url"]["url"] == "data:image/png;base64,QUJD"


def test_si_el_proveedor_falla_el_error_es_nuestro_y_en_espanol(sdk, monkeypatch):
    """Prueba de aceptación de RNF-10 (llave mala o sin red): ErrorIA sin datos del proveedor."""
    import httpx
    import openai

    def falla(**_):
        raise openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1"))

    _SDKFalso.respuesta = None
    monkeypatch.setattr(_SDKFalso, "__init__", lambda self, **datos: setattr(
        self, "chat", SimpleNamespace(completions=SimpleNamespace(create=falla))
    ))  # fmt: skip
    with pytest.raises(ErrorIA) as error:
        cliente.pedir_json("s", "u", RubricaEstructura, config=OPENAI)
    assert str(error.value) == "No se pudo hablar con la IA. Intenta de nuevo en un momento."
    assert error.value.uso is None


@pytest.mark.parametrize(
    "eleccion",
    [
        SimpleNamespace(message=SimpleNamespace(content="no es json"), finish_reason="stop"),
        SimpleNamespace(message=SimpleNamespace(content='{"criterios": ['), finish_reason="length"),
        SimpleNamespace(message=SimpleNamespace(content=""), finish_reason="stop"),
    ],
    ids=["json_malo", "cortada", "vacia"],
)
def test_una_respuesta_que_no_sirve_igual_trae_los_tokens(sdk, eleccion):
    _SDKFalso.respuesta = SimpleNamespace(
        choices=[eleccion], usage=SimpleNamespace(prompt_tokens=700, completion_tokens=16000)
    )
    with pytest.raises(ErrorIA) as error:
        cliente.pedir_json("s", "u", RubricaEstructura, config=OPENAI)
    assert (error.value.uso.entrada, error.value.uso.salida) == (700, 16000)


def test_la_prueba_de_conexion_pide_un_json_minimo(sdk):
    _SDKFalso.respuesta = _respuesta({"ok": True})
    uso = cliente.probar_conexion(OPENAI)
    assert uso.modelo == "gpt-6-luna"


def test_la_config_de_la_base_manda_sobre_la_del_entorno(db, crear_usuario, monkeypatch):
    from app.modelos import ConfigIAFila

    monkeypatch.setattr(cliente, "ajustes", lambda: Ajustes(llm_model="del-entorno"))
    assert cliente.configuracion(db).modelo == "del-entorno"
    admin = crear_usuario("administrador")
    db.add(
        ConfigIAFila(
            proveedor="openrouter",
            modelo="de-la-base",
            base_url=OPENROUTER.base_url,
            actualizado_por=admin.id,
        )
    )
    db.commit()
    assert cliente.configuracion(db).modelo == "de-la-base"


def test_una_config_guardada_que_ya_no_es_valida_no_se_usa(db, crear_usuario, monkeypatch):
    """Si cambian los equipos permitidos para Ollama, una dirección vieja no sirve."""
    from app.modelos import ConfigIAFila

    admin = crear_usuario("administrador")
    db.add(
        ConfigIAFila(
            proveedor="ollama", modelo="x", base_url="http://10.0.0.9:11434/v1", actualizado_por=admin.id
        )
    )
    db.commit()
    with pytest.raises(ErrorIA) as error:
        cliente.configuracion(db)
    assert error.value.configurada is False


def test_sin_modelo_en_ninguna_parte_no_esta_configurada():
    with pytest.raises(ErrorIA) as error:
        cliente.configuracion()
    assert error.value.configurada is False
