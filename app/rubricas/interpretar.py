"""Convertir con IA el texto de una rúbrica en `RubricaEstructura` (RF-04).

La IA solo copia la estructura; la validación (pesos, niveles, descriptores) la
hace `validar_rubrica` y la revisa el docente antes de usarla (D-16). El texto va
delimitado como datos (OWASP LLM01) y con tope de tamaño (OWASP LLM10).
"""

import re
import unicodedata
from collections.abc import Callable
from functools import cache
from pathlib import Path

from app.esquemas import RubricaEstructura
from app.ia.cliente import Uso
from app.rubricas.extraer import MAXIMO_CARACTERES, revisar_largo

VERSION_PROMPT = "interpretar_rubrica_v1"
CARPETA_PROMPTS = Path(__file__).resolve().parents[2] / "prompts"

__all__ = ["MAXIMO_CARACTERES", "VERSION_PROMPT", "armar_prompt", "interpretar"]

# Quien escriba "</rubrica>" (o "< /RUBRICA x>") en su archivo no puede cerrar la
# etiqueta y meter instrucciones por fuera de los datos.
_ETIQUETA = re.compile(r"<\s*/?\s*rubrica\b[^>]*>", re.IGNORECASE)

PedirJson = Callable[[str, str, type[RubricaEstructura]], tuple[RubricaEstructura, Uso]]


@cache
def _sistema() -> str:
    return (CARPETA_PROMPTS / f"{VERSION_PROMPT}.md").read_text(encoding="utf-8")


def armar_prompt(texto: str) -> tuple[str, str]:
    """Devuelve (mensaje del sistema, mensaje del usuario). Si el texto es muy largo, RubricaMuyLarga."""
    revisar_largo(texto)
    # NFKC convierte letras "parecidas" (por ejemplo, de ancho completo) en las normales.
    limpio = _ETIQUETA.sub("[etiqueta quitada]", unicodedata.normalize("NFKC", texto))
    usuario = f"Convierte esta rúbrica al JSON pedido.\n\n<rubrica>\n{limpio}\n</rubrica>"
    return _sistema(), usuario


def interpretar(texto: str, pedir: PedirJson) -> tuple[RubricaEstructura, Uso]:
    sistema, usuario = armar_prompt(texto)
    return pedir(sistema, usuario, RubricaEstructura)
