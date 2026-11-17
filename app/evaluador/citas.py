"""Verificación de citas (RF-12, OWASP LLM09).

Cada evidencia que cita la IA se busca en el material entregado: en ese archivo y en esa
página, diapositiva o esas líneas. Comparación aproximada con rapidfuzz (similitud mínima
de 85 %), porque la IA puede cambiar espacios o una tilde al copiar. Si no aparece, la cita
queda como "no encontrada" y la evaluación sube en la bandeja del docente.
"""

import re
import unicodedata
from dataclasses import dataclass, field

from rapidfuzz import fuzz

SIMILITUD_MINIMA = 85
HOLGURA_LINEAS = 2  # la IA a veces se corre una o dos líneas al citar
# Topes de tiempo (OWASP LLM10): rapidfuzz tarda según largo de la cita × largo del texto.
MAXIMO_FRAGMENTO = 1_000
MAXIMO_DONDE = 100_000

_PAGINA = re.compile(
    r"(?:p[aá]g(?:ina)?s?\.?|diapositivas?|slides?|pages?)\s*(\d{1,4})(?:\s*(?:-|–|a|al|to)\s*(\d{1,4}))?"
)
_LINEAS = re.compile(r"(?:l[ií]neas?|lines?|l\.)\s*(\d{1,6})(?:\s*(?:-|–|a|al|to)\s*(\d{1,6}))?")


@dataclass
class Documento:
    """Un archivo del material, como lo vio la IA: por páginas o por líneas."""

    paginas: list[str] = field(default_factory=list)  # PDF y diapositivas
    lineas: list[str] = field(default_factory=list)  # código
    texto: str = ""  # otro (descripción de imagen)

    def todo(self) -> str:
        if self.paginas:
            return "\n".join(self.paginas)
        if self.lineas:
            return "\n".join(self.lineas)
        return self.texto


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKC", texto).lower()
    return re.sub(r"\s+", " ", texto).strip()


def _rango(coincidencia: re.Match) -> tuple[int, int]:
    inicio = int(coincidencia.group(1))
    fin = int(coincidencia.group(2)) if coincidencia.group(2) else inicio
    return min(inicio, fin), max(inicio, fin)


def _donde_buscar(documento: Documento, ubicacion: str) -> str | None:
    """El pedazo de texto que corresponde a la ubicación citada, o None si no existe."""
    ubicacion = ubicacion.lower()
    if documento.paginas and (m := _PAGINA.search(ubicacion)):
        inicio, fin = _rango(m)
        if inicio < 1 or inicio > len(documento.paginas):
            return None
        return "\n".join(documento.paginas[inicio - 1 : fin])
    if documento.lineas and (m := _LINEAS.search(ubicacion)):
        inicio, fin = _rango(m)
        if inicio < 1 or inicio > len(documento.lineas):
            return None
        desde = max(0, inicio - 1 - HOLGURA_LINEAS)
        return "\n".join(documento.lineas[desde : fin + HOLGURA_LINEAS])
    return documento.todo()  # sin ubicación entendible: se busca en todo el archivo


def buscar_documento(documentos: dict[str, Documento], archivo: str) -> Documento | None:
    """El archivo citado. Primero exacto, luego sin mayúsculas, luego por el final de la ruta
    (la IA a veces cita 'main.py' por 'agente/main.py')."""
    if archivo in documentos:
        return documentos[archivo]
    clave = archivo.casefold()
    for nombre, documento in documentos.items():
        if nombre.casefold() == clave:
            return documento
    candidatos = [d for n, d in documentos.items() if n.casefold().endswith("/" + clave)]
    return candidatos[0] if len(candidatos) == 1 else None


def cita_encontrada(documentos: dict[str, Documento], archivo: str, ubicacion: str, fragmento: str) -> bool:
    documento = buscar_documento(documentos, archivo)
    if documento is None:
        return False
    texto = _donde_buscar(documento, ubicacion)
    if not texto:
        return False
    buscado = normalizar(fragmento[:MAXIMO_FRAGMENTO])
    if len(buscado) < 8:  # algo tan corto aparece en cualquier parte: no prueba nada
        return False
    if len(buscado) > MAXIMO_FRAGMENTO:  # NFKC lo infló (p. ej. U+FDFA): compararlo congelaría la app
        return False
    donde = normalizar(texto[:MAXIMO_DONDE])[:MAXIMO_DONDE]
    if len(buscado) > len(donde):
        # partial_ratio buscaría el texto corto dentro de la cita: una cita que trae la página
        # entera y algo inventado pasaría. Aquí la cita tiene que ser, casi toda, el texto.
        return fuzz.ratio(buscado, donde, score_cutoff=SIMILITUD_MINIMA) > 0
    return fuzz.partial_ratio(buscado, donde, score_cutoff=SIMILITUD_MINIMA) > 0
