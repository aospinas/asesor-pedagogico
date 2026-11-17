"""Cliente único de IA (SRS sección 9): el SDK de OpenAI sirve para OpenAI, Ollama y OpenRouter.

Versión mínima para el módulo de rúbricas: una sola función que pide un JSON y lo
valida contra un esquema de app/esquemas.py. El módulo evaluador la amplía.

Reglas:
- La dirección se revisa con `ConfigIA` antes de llamar: la llave nunca sale a otro servidor.
- La respuesta se valida con el esquema (extra="forbid"): si la IA agrega campos, se rechaza.
- Los errores no llevan la respuesta de la IA ni la llave: solo un aviso en español.
"""

import json
import logging
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from app.config import ajustes
from app.esquemas import ConfigIA, ProveedorIA

registro = logging.getLogger("asesor.ia")

MAXIMO_TOKENS_RESPUESTA = 4000


class ErrorIA(Exception):
    """La IA no respondió o respondió algo que no cumple el esquema."""

    def __init__(self, mensaje: str, *, configurada: bool = True):
        super().__init__(mensaje)
        self.configurada = configurada


@dataclass(frozen=True)
class Uso:
    modelo: str
    entrada: int
    salida: int


def validar_respuesta[T: BaseModel](texto: str, esquema: type[T]) -> T:
    """Convierte el texto de la IA al esquema. Si no es JSON o no cumple el esquema, ErrorIA."""
    try:
        return esquema.model_validate(json.loads(texto))
    except (json.JSONDecodeError, ValidationError, TypeError, RecursionError) as error:
        registro.warning("La IA devolvió algo que no cumple %s: %s", esquema.__name__, type(error).__name__)
        raise ErrorIA("La IA no devolvió un JSON con el formato esperado.") from None


def configuracion() -> ConfigIA:
    a = ajustes()
    if not a.llm_model:
        raise ErrorIA("La IA no está configurada (falta LLM_MODEL).", configurada=False)
    try:
        return ConfigIA(proveedor=a.llm_provider, modelo=a.llm_model, base_url=a.llm_base_url)
    except ValidationError:
        raise ErrorIA("La configuración de la IA no es válida.", configurada=False) from None


def pedir_json[T: BaseModel](sistema: str, usuario: str, esquema: type[T]) -> tuple[T, Uso]:
    """Manda el prompt y devuelve la respuesta ya validada con el esquema."""
    config = configuracion()
    from openai import OpenAI, OpenAIError  # se importa aquí: las pruebas no lo necesitan

    # Ollama no pide llave y puede ir por http: la llave real nunca se le manda.
    llave = ajustes().llm_api_key.get_secret_value()
    if config.proveedor == ProveedorIA.OLLAMA or not llave:
        llave = "sin-llave"
    # Sin reintento: cada intento gasta tokens y deja al docente esperando.
    cliente = OpenAI(base_url=config.base_url, api_key=llave, timeout=ajustes().llm_tiempo_seg, max_retries=0)
    try:
        respuesta = cliente.chat.completions.create(
            model=config.modelo,
            messages=[{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=MAXIMO_TOKENS_RESPUESTA,
        )
    except OpenAIError as error:
        registro.error("Falló la llamada a la IA (%s): %s", config.proveedor, type(error).__name__)
        raise ErrorIA("No se pudo hablar con la IA. Intenta de nuevo en un momento.") from None

    eleccion = respuesta.choices[0] if respuesta.choices else None
    if eleccion is None or not eleccion.message.content:
        raise ErrorIA("La IA respondió vacío.")
    if eleccion.finish_reason == "length":  # se quedó sin espacio: el JSON viene cortado
        raise ErrorIA("La respuesta de la IA quedó incompleta.")
    texto = eleccion.message.content
    uso = respuesta.usage
    return validar_respuesta(texto, esquema), Uso(
        modelo=config.modelo,
        entrada=uso.prompt_tokens if uso else 0,
        salida=uso.completion_tokens if uso else 0,
    )
