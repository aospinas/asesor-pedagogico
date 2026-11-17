"""Sacar el texto de una rúbrica subida (RF-04): PDF, Word (.docx), texto plano o JSON.

El tipo se decide por el contenido, no por el nombre del archivo (OWASP A05).

Defensas contra archivos hechos para tumbar el servidor (OWASP A08, LLM10):
- Topes de tamaño, de páginas y de lo que ocupa un .docx al descomprimirse.
- El .docx se lee con expresiones regulares sin retroceso sobre su XML, sin un
  lector de XML: así no hay entidades externas ni expansiones que atacar.
- El PDF se lee en un proceso aparte con tiempo límite (y memoria limitada en
  Linux): un PDF bomba mata ese proceso, no la app.
- La lectura se corta al pasar el máximo de caracteres que puede ir a la IA.
"""

import hashlib
import html
import io
import multiprocessing
import queue
import re
import sys
import time
import zipfile
import zlib
from dataclasses import dataclass

from app.esquemas import OrigenRubrica

MAXIMO_BYTES = 5 * 1024 * 1024  # 5 MB
MAXIMO_PAGINAS = 30
MAXIMO_DESCOMPRIMIDO = 2 * 1024 * 1024  # lo que puede ocupar el XML de un .docx ya abierto
MAXIMO_CARACTERES = 40_000  # lo más que se manda a la IA; una rúbrica más larga se rechaza
MINIMO_CARACTERES_PDF = 30  # menos que esto = PDF escaneado o vacío
MINIMO_CARACTERES_DOCX = 10
TIEMPO_PDF_SEG = 15
MEMORIA_PDF_BYTES = 400 * 1024 * 1024  # solo se aplica en Linux (Render)

TIPOS_PERMITIDOS = "Sube la rúbrica en PDF, Word, texto o JSON."
NO_ABRE_WORD = "No se pudo abrir el documento de Word."
NO_ABRE_PDF = "No se pudo leer el PDF."
PDF_PESADO = "El PDF es demasiado pesado para leerlo. Súbelo en Word o texto."

_PARRAFO = re.compile(r"</w:p>")
_CELDA = re.compile(r"</w:tc>")
_TABULADOR = re.compile(r"<w:tab/>")
# [^<>] y no [^>]: así la búsqueda se detiene en la siguiente etiqueta y no recorre
# todo el documento por cada <w:t (eso tardaba horas con un archivo hecho a propósito).
_TEXTO_W = re.compile(r"<w:t(?:\s[^<>]{0,300})?>([^<]*)</w:t>")

# Errores que lanza zipfile con archivos cifrados, dañados o con compresión rara
_ERRORES_ZIP = (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error, OSError)


class ArchivoNoValido(ValueError):
    """El archivo no se puede usar. El mensaje es para el docente, en español."""


class ArchivoMuyGrande(ArchivoNoValido):
    """El archivo pesa más de MAXIMO_BYTES (la ruta responde 413)."""


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

    if contenido.startswith(b"%PDF-"):
        return Extraido(OrigenRubrica.PDF, _de_pdf(contenido), huella)
    if contenido.startswith(b"PK\x03\x04"):
        return Extraido(OrigenRubrica.DOCX, _de_docx(contenido), huella)

    texto = _de_texto(contenido)
    origen = OrigenRubrica.JSON if texto.lstrip().startswith("{") else OrigenRubrica.TEXTO
    return Extraido(origen, texto, huella)


def revisar_largo(texto: str) -> None:
    if len(texto) > MAXIMO_CARACTERES:
        raise RubricaMuyLarga(
            f"La rúbrica es muy larga (más de {MAXIMO_CARACTERES:,} caracteres). "
            "Quita lo que no sea rúbrica o súbela en JSON.".replace(",", ".")
        )


# ---------- PDF ----------


def _leer_pdf(contenido: bytes, cola) -> None:
    """Corre en el proceso aparte. Devuelve ("ok", paginas) o ("error", mensaje)."""
    try:
        if sys.platform.startswith("linux"):
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (MEMORIA_PDF_BYTES, MEMORIA_PDF_BYTES))
        import pymupdf

        with pymupdf.open(stream=contenido, filetype="pdf") as doc:
            if doc.needs_pass:
                cola.put(("error", "El PDF tiene contraseña. Súbelo sin contraseña."))
                return
            if doc.page_count > MAXIMO_PAGINAS:
                cola.put(("error", f"El PDF tiene más de {MAXIMO_PAGINAS} páginas."))
                return
            paginas: list[str] = []
            total = 0
            for pagina in doc:
                texto = pagina.get_text()
                paginas.append(texto)
                total += len(texto)
                if total > MAXIMO_CARACTERES:  # no hace falta leer más: ya es muy larga
                    break
        cola.put(("ok", paginas))
    except Exception:  # PyMuPDF lanza varios tipos según el daño del archivo
        cola.put(("error", NO_ABRE_PDF))


def _de_pdf(contenido: bytes) -> str:
    contexto = multiprocessing.get_context("spawn")
    cola = contexto.Queue()
    proceso = contexto.Process(target=_leer_pdf, args=(contenido, cola), daemon=True)
    proceso.start()
    limite = time.monotonic() + TIEMPO_PDF_SEG
    try:
        while True:
            try:
                estado, valor = cola.get(timeout=0.2)
                break
            except queue.Empty:
                if not proceso.is_alive():  # murió sin responder: en Linux, por pasarse de memoria
                    try:
                        estado, valor = cola.get(timeout=0.5)
                    except queue.Empty:
                        estado, valor = "error", PDF_PESADO
                    break
                if time.monotonic() > limite:
                    estado, valor = "error", "El PDF tardó demasiado en leerse. Súbelo en Word o texto."
                    break
    finally:
        proceso.join(timeout=1)
        if proceso.is_alive():
            proceso.kill()
            proceso.join()
        cola.close()

    if estado != "ok":
        raise ArchivoNoValido(valor)
    paginas: list[str] = valor
    if sum(len(t.strip()) for t in paginas) < MINIMO_CARACTERES_PDF:
        raise ArchivoNoValido("El PDF no tiene texto legible (parece escaneado). Súbelo en Word o texto.")
    texto = "\n".join(f"[Página {i}]\n{t.strip()}" for i, t in enumerate(paginas, start=1) if t.strip())
    revisar_largo(texto)
    return texto


# ---------- Word ----------


def _de_docx(contenido: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(contenido)) as z:
            try:
                info = z.getinfo("word/document.xml")
            except KeyError:
                raise ArchivoNoValido("El archivo no es un documento de Word (.docx).") from None
            if info.file_size > MAXIMO_DESCOMPRIMIDO:
                raise ArchivoNoValido("El documento de Word es demasiado grande al abrirlo.")
            with z.open(info) as f:
                # El tamaño que dice el zip puede mentir: se lee con tope igual.
                xml = f.read(MAXIMO_DESCOMPRIMIDO + 1)
    except ArchivoNoValido:
        raise
    except _ERRORES_ZIP:
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
