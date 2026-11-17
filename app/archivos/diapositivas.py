"""Texto de unas diapositivas PowerPoint (.pptx) o PDF, por diapositiva (SRS sección 9).

El .pptx NO se abre con python-pptx: esa librería carga todo el XML en memoria y un
archivo de 164 KB hecho a propósito llegó a pedir 265 MB (revisión de seguridad,
D-17). Como con el .docx de las rúbricas, el texto se saca con expresiones regulares
sin retroceso, diapositiva por diapositiva, con tope por parte y en total.
"""

import html
import io
import re
import zipfile

from app.archivos import ArchivoNoValido, megas, pdf
from app.archivos.zip import (
    COMPRESIONES_PERMITIDAS,
    ERRORES_DESCONOCIDOS,
    ERRORES_ZIP,
    error_inesperado,
    es_zip,
    revisar_entradas,
    revisar_indice,
)
from app.archivos.zip import NO_ABRE as NO_ABRE_ZIP

MAXIMO_POR_DIAPOSITIVA = 2 * 1024 * 1024  # XML de una diapositiva ya abierto
MAXIMO_DESCOMPRIMIDO = 10 * 1024 * 1024  # todas las diapositivas abiertas
MAXIMO_DIAPOSITIVAS = 80
MAXIMO_PARTES = 2000  # archivos dentro del .pptx (diapositivas, imágenes, estilos...)
MAXIMO_CARACTERES = 200_000
NO_ABRE = "No se pudieron leer las diapositivas."
NO_ES_PRESENTACION = "Las diapositivas deben ser PowerPoint (.pptx) o PDF."
MUY_GRANDE = "Una de las diapositivas es demasiado grande."

_DIAPOSITIVA = re.compile(r"^ppt/slides/slide(\d{1,4})\.xml$")
_PARRAFO = re.compile(r"</a:p>")
# [^<>] y no [^>]: la búsqueda se detiene en la siguiente etiqueta (sin retroceso largo)
_TEXTO_A = re.compile(r"<a:t(?:\s[^<>]{0,300})?>([^<]*)</a:t>")


def leer_diapositivas(contenido: bytes) -> tuple[str, list[str], bool]:
    """Devuelve ("pdf" | "pptx", texto de cada diapositiva, recortado)."""
    if pdf.es_pdf(contenido):
        lectura = pdf.leer_paginas(
            contenido, maximo_paginas=MAXIMO_DIAPOSITIVAS, maximo_caracteres=MAXIMO_CARACTERES
        )
        return "pdf", [p.strip() for p in lectura.paginas], lectura.recortado
    if not es_zip(contenido):
        raise ArchivoNoValido(NO_ES_PRESENTACION)
    try:
        revisar_indice(contenido, MAXIMO_PARTES)  # antes de que zipfile lea el índice entero
    except ArchivoNoValido as error:
        raise ArchivoNoValido(NO_ABRE if str(error) == NO_ABRE_ZIP else str(error)) from None
    try:
        with zipfile.ZipFile(io.BytesIO(contenido)) as z:
            revisar_entradas(z.infolist(), len(contenido), NO_ABRE)
            if "ppt/presentation.xml" not in z.namelist():
                raise ArchivoNoValido(NO_ES_PRESENTACION)
            numeradas = [
                (int(m.group(1)), info) for info in z.infolist() if (m := _DIAPOSITIVA.match(info.filename))
            ]
            if len(numeradas) > MAXIMO_DIAPOSITIVAS:
                raise ArchivoNoValido(f"Las diapositivas son más de {MAXIMO_DIAPOSITIVAS}.")
            partes = [info for _, info in sorted(numeradas, key=lambda par: par[0])]
            textos, recortado = _textos(z, partes)
            return "pptx", textos, recortado
    except ArchivoNoValido:
        raise
    except ERRORES_ZIP:
        raise ArchivoNoValido(NO_ABRE) from None
    except ERRORES_DESCONOCIDOS as error:
        error_inesperado("unas diapositivas", error)
        raise ArchivoNoValido(NO_ABRE) from None


def _textos(z: zipfile.ZipFile, partes: list[zipfile.ZipInfo]) -> tuple[list[str], bool]:
    if sum(p.file_size for p in partes) > MAXIMO_DESCOMPRIMIDO:
        raise ArchivoNoValido(f"Las diapositivas ocupan más de {megas(MAXIMO_DESCOMPRIMIDO)} al abrirlas.")
    textos: list[str] = []
    restante = MAXIMO_CARACTERES
    leido = 0
    for parte in partes:
        if parte.compress_type not in COMPRESIONES_PERMITIDAS or parte.flag_bits & 0x1:
            raise ArchivoNoValido(NO_ABRE)
        if parte.file_size > MAXIMO_POR_DIAPOSITIVA:
            raise ArchivoNoValido(MUY_GRANDE)
        with z.open(parte) as f:
            xml = f.read(MAXIMO_POR_DIAPOSITIVA + 1)
        leido += len(xml)
        if len(xml) > MAXIMO_POR_DIAPOSITIVA or leido > MAXIMO_DESCOMPRIMIDO:
            raise ArchivoNoValido(MUY_GRANDE)
        marcado = xml.decode("utf-8", errors="replace")
        parrafos = ["".join(_TEXTO_A.findall(p)) for p in _PARRAFO.split(marcado)]
        texto = "\n".join(html.unescape(p).strip() for p in parrafos if p.strip())
        if len(texto) > restante:
            textos.append(texto[:restante])
            return textos, True
        textos.append(texto)
        restante -= len(texto)
    return textos, False
