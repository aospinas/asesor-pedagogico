"""Sacar el texto de una rúbrica subida (RF-04): PDF, Word (.docx), texto plano o JSON.

El tipo se decide por el contenido, no por el nombre del archivo (OWASP A05).

Defensas contra archivos hechos para tumbar el servidor (OWASP A08, LLM10):
- Topes de tamaño, de páginas y de lo que ocupa un .docx al descomprimirse.
- El .docx se lee con expresiones regulares sin retroceso sobre su XML, sin un
  lector de XML: así no hay entidades externas ni expansiones que atacar.
- El PDF se lee en un proceso aparte con tiempo límite (app/archivos/pdf.py):
  un PDF bomba mata ese proceso, no la app.
- La lectura se corta al pasar el máximo de caracteres que puede ir a la IA.
"""

import hashlib
import html
import io
import re
import zipfile
from dataclasses import dataclass

from app.archivos import ArchivoMuyGrande, ArchivoNoValido, pdf
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
from app.esquemas import OrigenRubrica

__all__ = ["ArchivoMuyGrande", "ArchivoNoValido", "extraer_texto", "revisar_largo"]

MAXIMO_BYTES = 5 * 1024 * 1024  # 5 MB
MAXIMO_PAGINAS = 30
MAXIMO_DESCOMPRIMIDO = 2 * 1024 * 1024  # lo que puede ocupar el XML de un .docx ya abierto
MAXIMO_CARACTERES = 40_000  # lo más que se manda a la IA; una rúbrica más larga se rechaza
MINIMO_CARACTERES_PDF = 30  # menos que esto = PDF escaneado o vacío
MINIMO_CARACTERES_DOCX = 10
MAXIMO_PARTES_DOCX = 2000  # archivos dentro del .docx
TIEMPO_PDF_SEG = pdf.TIEMPO_SEG

TIPOS_PERMITIDOS = "Sube la rúbrica en PDF, Word, texto o JSON."
NO_ABRE_WORD = "No se pudo abrir el documento de Word."

_PARRAFO = re.compile(r"</w:p>")
_CELDA = re.compile(r"</w:tc>")
_TABULADOR = re.compile(r"<w:tab/>")
# [^<>] y no [^>]: así la búsqueda se detiene en la siguiente etiqueta y no recorre
# todo el documento por cada <w:t (eso tardaba horas con un archivo hecho a propósito).
_TEXTO_W = re.compile(r"<w:t(?:\s[^<>]{0,300})?>([^<]*)</w:t>")


class RubricaMuyLarga(ArchivoNoValido):
    """El texto pasa de MAXIMO_CARACTERES: no se recorta sin avisar."""


@dataclass(frozen=True)
class Extraido:
    origen: OrigenRubrica
    texto: str
    sha256: str


def mensaje_muy_grande() -> str:
    return f"El archivo pesa más de {MAXIMO_BYTES // (1024 * 1024)} MB."


def extraer_texto(contenido: bytes) -> Extraido:
    if len(contenido) > MAXIMO_BYTES:
        raise ArchivoMuyGrande(mensaje_muy_grande())
    huella = hashlib.sha256(contenido).hexdigest()

    if pdf.es_pdf(contenido):
        return Extraido(OrigenRubrica.PDF, _de_pdf(contenido), huella)
    if es_zip(contenido):
        return Extraido(OrigenRubrica.DOCX, _de_docx(contenido), huella)

    texto = _de_texto(contenido)
    origen = OrigenRubrica.JSON if texto.lstrip().startswith("{") else OrigenRubrica.TEXTO
    return Extraido(origen, texto, huella)


def _muy_larga() -> RubricaMuyLarga:
    return RubricaMuyLarga(
        f"La rúbrica es muy larga (más de {MAXIMO_CARACTERES:,} caracteres). "
        "Quita lo que no sea rúbrica o súbela en JSON.".replace(",", ".")
    )


def revisar_largo(texto: str) -> None:
    if len(texto) > MAXIMO_CARACTERES:
        raise _muy_larga()


# ---------- PDF ----------


def _de_pdf(contenido: bytes) -> str:
    try:
        lectura = pdf.leer_paginas(
            contenido,
            maximo_paginas=MAXIMO_PAGINAS,
            maximo_caracteres=MAXIMO_CARACTERES,
            tiempo_seg=TIEMPO_PDF_SEG,
        )
    except ArchivoNoValido as error:
        mensaje = str(error)
        if mensaje in (pdf.PESADO, pdf.LENTO):
            mensaje += " Súbelo en Word o texto."
        raise ArchivoNoValido(mensaje) from None
    if lectura.recortado:  # el texto pasaba del tope: la rúbrica es muy larga
        raise _muy_larga()
    paginas = lectura.paginas
    if sum(len(t.strip()) for t in paginas) < MINIMO_CARACTERES_PDF:
        raise ArchivoNoValido("El PDF no tiene texto legible (parece escaneado). Súbelo en Word o texto.")
    texto = "\n".join(f"[Página {i}]\n{t.strip()}" for i, t in enumerate(paginas, start=1) if t.strip())
    revisar_largo(texto)
    return texto


# ---------- Word ----------


def _de_docx(contenido: bytes) -> str:
    try:
        revisar_indice(contenido, MAXIMO_PARTES_DOCX)  # antes de que zipfile lea el índice entero
    except ArchivoNoValido as error:
        raise ArchivoNoValido(NO_ABRE_WORD if str(error) == NO_ABRE_ZIP else str(error)) from None
    try:
        with zipfile.ZipFile(io.BytesIO(contenido)) as z:
            revisar_entradas(z.infolist(), len(contenido), NO_ABRE_WORD)
            try:
                info = z.getinfo("word/document.xml")
            except KeyError:
                raise ArchivoNoValido("El archivo no es un documento de Word (.docx).") from None
            if info.file_size > MAXIMO_DESCOMPRIMIDO:
                raise ArchivoNoValido("El documento de Word es demasiado grande al abrirlo.")
            # Igual que en el ZIP y el PPTX: solo compresión normal y sin contraseña. Con zstd
            # (Python 3.14+) zipfile lanzaba ZstdError y la carga daba 500 (6.ª revisión).
            if info.compress_type not in COMPRESIONES_PERMITIDAS or info.flag_bits & 0x1:
                raise ArchivoNoValido(NO_ABRE_WORD)
            with z.open(info) as f:
                # El tamaño que dice el zip puede mentir: se lee con tope igual.
                xml = f.read(MAXIMO_DESCOMPRIMIDO + 1)
    except ArchivoNoValido:
        raise
    except ERRORES_ZIP:
        raise ArchivoNoValido(NO_ABRE_WORD) from None
    except ERRORES_DESCONOCIDOS as error:
        error_inesperado("un Word de rúbrica", error)
        raise ArchivoNoValido(NO_ABRE_WORD) from None
    if len(xml) > MAXIMO_DESCOMPRIMIDO:
        raise ArchivoNoValido("El documento de Word es demasiado grande al abrirlo.")

    marcado = xml.decode("utf-8", errors="replace")
    marcado = _TABULADOR.sub("<w:t>\t</w:t>", marcado)
    marcado = _CELDA.sub("<w:t> | </w:t>", marcado)
    parrafos = ["".join(_TEXTO_W.findall(p)) for p in _PARRAFO.split(marcado)]
    texto = "\n".join(html.unescape(p).strip() for p in parrafos if p.strip())
    if len(texto) < MINIMO_CARACTERES_DOCX:
        raise ArchivoNoValido("El documento de Word está vacío.")
    revisar_largo(texto)
    return texto


# ---------- Texto y JSON ----------


def _de_texto(contenido: bytes) -> str:
    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        # El Bloc de notas viejo guarda en cp1252. Si no es eso, no es un texto.
        try:
            texto = contenido.decode("cp1252")
        except UnicodeDecodeError:
            raise ArchivoNoValido(TIPOS_PERMITIDOS) from None
        if any(ord(c) < 32 and c not in "\t\r\n" for c in texto):
            raise ArchivoNoValido(TIPOS_PERMITIDOS) from None
    if "\x00" in texto or not texto.strip():
        raise ArchivoNoValido(TIPOS_PERMITIDOS)
    return texto
