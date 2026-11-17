"""La IA redacta el plan con datos ya calculados. Si no está, el informe sale igual, sin plan."""

import re
import unicodedata
from functools import cache
from pathlib import Path

from app.esquemas import Informe, PlanFortalecimiento
from app.ia.cliente import ErrorIA, pedir_json

VERSION_PROMPT = "plan_fortalecimiento_v1"
_CARPETA = Path(__file__).resolve().parents[2] / "prompts"
_ETIQUETA = re.compile(r"<\s*/?\s*datos\b[^>]*>", re.IGNORECASE)


@cache
def _sistema() -> str:
    return (_CARPETA / f"{VERSION_PROMPT}.md").read_text(encoding="utf-8")


def _texto(informe: Informe) -> str:
    lineas = []
    for tema in informe.temas:
        lineas.append(f"- {tema.categoria} / {tema.tema}: nivel {tema.nivel.value}")
    for brecha in informe.brechas:
        lineas.append(f"Brecha: {brecha}")
    limpio = _ETIQUETA.sub("[etiqueta quitada]", unicodedata.normalize("NFKC", "\n".join(lineas)))
    return f"Redacta el plan de fortalecimiento.\n\n<datos>\n{limpio}\n</datos>"


def redactar_plan(informe: Informe) -> PlanFortalecimiento | None:
    if not informe.temas and not informe.brechas:
        return None
    try:
        plan, _uso = pedir_json(_sistema(), _texto(informe), PlanFortalecimiento)
    except (ErrorIA, OSError, TimeoutError):
        return None
    return plan
