"""Cliente único de IA (SRS sección 9): el SDK de OpenAI sirve para OpenAI, Ollama y OpenRouter.

Reglas:
- La dirección se revisa con `ConfigIA` antes de llamar: la llave nunca sale a otro servidor.
  OpenAI y OpenRouter tienen una sola dirección permitida; Ollama, solo los equipos de
  OLLAMA_HOSTS_PERMITIDOS, y a Ollama nunca se le manda la llave.
- La respuesta se valida con el esquema (extra="forbid"): si la IA agrega campos, se rechaza.
- Los errores no llevan la respuesta de la IA ni la llave: solo un aviso en español.
- El proveedor y el modelo los elige el administrador (tabla config_ia, RF-19); si no ha
  elegido, salen de las variables de entorno. La llave SIEMPRE sale de LLM_API_KEY.
"""

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import ajustes
from app.esquemas import ConfigIA, ProveedorIA, RespuestaPrueba

if TYPE_CHECKING:
    from app.modelos import ConfigIAFila

registro = logging.getLogger("asesor.ia")

MAXIMO_TOKENS_RESPUESTA = 4000
# Los modelos que razonan gastan tokens pensando antes de escribir: se les da más espacio.
MAXIMO_TOKENS_CON_RAZONAMIENTO = 16000


@dataclass(frozen=True)
class Uso:
    modelo: str
    entrada: int
    salida: int


class ErrorIA(Exception):
    """La IA no respondió o respondió algo que no cumple el esquema.

    Si la IA alcanzó a responder (y cobró), `uso` trae los tokens: hay que sumarlos igual al
    costo y al tope (RF-20, OWASP LLM10)."""

    def __init__(self, mensaje: str, *, configurada: bool = True, uso: Uso | None = None):
        super().__init__(mensaje)
        self.configurada = configurada
        self.uso = uso


@dataclass(frozen=True)
class Imagen:
    """Una imagen para un modelo con visión. Va como data URL: nunca se manda un enlace."""

    contenido_base64: str
    tipo_mime: str


def validar_respuesta[T: BaseModel](texto: str, esquema: type[T]) -> T:
    """Convierte el texto de la IA al esquema. Si no es JSON o no cumple el esquema, ErrorIA."""
    try:
        return esquema.model_validate(json.loads(texto))
    except (json.JSONDecodeError, ValidationError, TypeError, RecursionError) as error:
        registro.warning("La IA devolvió algo que no cumple %s: %s", esquema.__name__, type(error).__name__)
        raise ErrorIA("La IA no devolvió un JSON con el formato esperado.") from None


def _de_entorno() -> ConfigIA:
    a = ajustes()
    if not a.llm_model:
        raise ErrorIA("La IA no está configurada (falta LLM_MODEL).", configurada=False)
    try:
        return ConfigIA(proveedor=a.llm_provider, modelo=a.llm_model, base_url=a.llm_base_url)
    except ValidationError:
        raise ErrorIA("La configuración de la IA no es válida.", configurada=False) from None


def ultima_config_guardada(db: Session) -> "ConfigIAFila | None":
    from app.modelos import ConfigIAFila

    return db.scalars(select(ConfigIAFila).order_by(ConfigIAFila.fecha.desc()).limit(1)).first()


def configuracion(db: Session | None = None) -> ConfigIA:
    """La que eligió el administrador (si hay base y la eligió) o la de las variables de entorno."""
    if db is not None:
        fila = ultima_config_guardada(db)
        if fila is not None:
            try:
                return ConfigIA(
                    proveedor=fila.proveedor,
                    modelo=fila.modelo,
                    base_url=fila.base_url,
                    precio_entrada_usd=fila.precio_entrada_usd,
                    precio_salida_usd=fila.precio_salida_usd,
                )
            except ValidationError:  # p. ej. cambió OLLAMA_HOSTS_PERMITIDOS después de guardarla
                raise ErrorIA("La configuración de la IA no es válida.", configurada=False) from None
    return _de_entorno()


def _parametros(config: ConfigIA, maximo: int | None) -> dict:
    """Los parámetros cambian según el proveedor (documentación de OpenAI de nov-2026):
    los modelos de OpenAI que razonan no aceptan `temperature` ni `max_tokens`."""
    esfuerzo = ajustes().llm_esfuerzo
    if config.proveedor == ProveedorIA.OPENAI:
        datos: dict = {"max_completion_tokens": maximo or MAXIMO_TOKENS_CON_RAZONAMIENTO}
        if esfuerzo:
            datos["reasoning_effort"] = esfuerzo
        if esfuerzo in ("", "none"):
            datos["temperature"] = 0
        return datos
    return {"max_tokens": maximo or MAXIMO_TOKENS_RESPUESTA, "temperature": 0}


def pedir_json[T: BaseModel](
    sistema: str,
    usuario: str,
    esquema: type[T],
    *,
    config: ConfigIA | None = None,
    imagenes: list[Imagen] | None = None,
    maximo_tokens: int | None = None,
) -> tuple[T, Uso]:
    """Manda el prompt (y si hay, imágenes) y devuelve la respuesta ya validada con el esquema."""
    config = config or configuracion()
    from openai import OpenAI, OpenAIError  # se importa aquí: las pruebas no lo necesitan

    # Ollama no pide llave y puede ir por http: la llave real nunca se le manda.
    llave = ajustes().llm_api_key.get_secret_value()
    if config.proveedor == ProveedorIA.OLLAMA or not llave:
        llave = "sin-llave"
    # Sin reintento automático: cada intento gasta tokens. Quien llama decide si reintenta.
    cliente = OpenAI(base_url=config.base_url, api_key=llave, timeout=ajustes().llm_tiempo_seg, max_retries=0)
    contenido: str | list[dict] = usuario
    if imagenes:
        contenido = [{"type": "text", "text": usuario}] + [
            {"type": "image_url", "image_url": {"url": f"data:{i.tipo_mime};base64,{i.contenido_base64}"}}
            for i in imagenes
        ]
    try:
        respuesta = cliente.chat.completions.create(
            model=config.modelo,
            messages=[{"role": "system", "content": sistema}, {"role": "user", "content": contenido}],
            response_format={"type": "json_object"},
            **_parametros(config, maximo_tokens),
        )
    except OpenAIError as error:
        registro.error("Falló la llamada a la IA (%s): %s", config.proveedor, type(error).__name__)
        raise ErrorIA("No se pudo hablar con la IA. Intenta de nuevo en un momento.") from None

    datos_uso = respuesta.usage
    uso = Uso(
        modelo=config.modelo,
        entrada=datos_uso.prompt_tokens if datos_uso else 0,
        salida=datos_uso.completion_tokens if datos_uso else 0,
    )
    eleccion = respuesta.choices[0] if respuesta.choices else None
    if eleccion is None or not eleccion.message.content:
        raise ErrorIA("La IA respondió vacío.", uso=uso)
    if eleccion.finish_reason == "length":  # se quedó sin espacio: el JSON viene cortado
        raise ErrorIA("La respuesta de la IA quedó incompleta.", uso=uso)
    try:
        return validar_respuesta(eleccion.message.content, esquema), uso
    except ErrorIA as error:
        error.uso = uso
        raise


def probar_conexion(config: ConfigIA) -> Uso:
    """Pide algo mínimo para saber si el proveedor, el modelo y la llave funcionan (RF-19)."""
    _, uso = pedir_json(
        'Responde solo con este JSON: {"ok": true}',
        "Prueba de conexión.",
        RespuestaPrueba,
        config=config,
        maximo_tokens=2000,
    )
    return uso
