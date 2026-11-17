"""Leer el texto de un PDF por página, en un proceso aparte (OWASP A08, LLM10).

Un PDF bomba (pocos KB que se expanden a cientos de MB) mata el proceso aparte y
no la app: hay tiempo límite y, en Linux (Render), límite de memoria. Además:
- Solo se lee un PDF a la vez: dos procesos de 200 MB más la app no caben en los
  512 MB de Render.
- El texto nunca pasa de `maximo_caracteres`: se corta dentro del proceso aparte,
  antes de copiarlo a la app, y se avisa con `recortado`.
"""

import multiprocessing
import queue
import sys
import threading
import time
from dataclasses import dataclass

from app.archivos import ArchivoNoValido

TIEMPO_SEG = 15
MEMORIA_BYTES = 200 * 1024 * 1024  # solo se aplica en Linux
ESPERA_TURNO_SEG = 30  # si otro PDF se está leyendo, se espera hasta esto

NO_ABRE = "No se pudo leer el PDF."
PESADO = "El PDF es demasiado pesado para leerlo."
LENTO = "El PDF tardó demasiado en leerse."
CON_CLAVE = "El PDF tiene contraseña. Súbelo sin contraseña."

_TURNO = threading.BoundedSemaphore(1)


class ServidorOcupado(Exception):
    """Hay otro archivo pesado leyéndose y no hubo turno a tiempo (la ruta responde 503)."""


@dataclass(frozen=True)
class LecturaPdf:
    paginas: list[str]
    recortado: bool  # True si el texto pasaba del tope y se cortó


def es_pdf(contenido: bytes) -> bool:
    return contenido.startswith(b"%PDF-")


def _leer(contenido: bytes, maximo_paginas: int, maximo_caracteres: int, memoria: int, cola) -> None:
    """Corre en el proceso aparte. Devuelve ("ok", (paginas, recortado)) o ("error", mensaje)."""
    try:
        if sys.platform.startswith("linux"):
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (memoria, memoria))
        import pymupdf

        with pymupdf.open(stream=contenido, filetype="pdf") as doc:
            if doc.needs_pass:
                cola.put(("error", CON_CLAVE))
                return
            if doc.page_count > maximo_paginas:
                cola.put(("error", f"El PDF tiene más de {maximo_paginas} páginas."))
                return
            paginas: list[str] = []
            restante = maximo_caracteres
            recortado = False
            for pagina in doc:
                texto = pagina.get_text()
                if len(texto) > restante:  # se corta aquí: lo de más nunca llega a la app
                    paginas.append(texto[:restante])
                    recortado = True
                    break
                paginas.append(texto)
                restante -= len(texto)
        cola.put(("ok", (paginas, recortado)))
    except Exception:  # PyMuPDF lanza varios tipos según el daño del archivo
        cola.put(("error", NO_ABRE))


def leer_paginas(
    contenido: bytes, *, maximo_paginas: int, maximo_caracteres: int, tiempo_seg: float = TIEMPO_SEG
) -> LecturaPdf:
    """Texto de cada página, con tope.

    Lanza ArchivoNoValido si el PDF no sirve o no se pudo leer a tiempo, y ServidorOcupado
    si otro PDF se está leyendo y no hubo turno (app/main.py lo convierte en 503)."""
    if not es_pdf(contenido):
        raise ArchivoNoValido("El archivo no es un PDF.")
    if not _TURNO.acquire(timeout=ESPERA_TURNO_SEG):
        raise ServidorOcupado("Hay muchos archivos leyéndose en este momento. Intenta en un minuto.")
    try:
        return _leer_aparte(contenido, maximo_paginas, maximo_caracteres, tiempo_seg)
    finally:
        _TURNO.release()


def _leer_aparte(
    contenido: bytes, maximo_paginas: int, maximo_caracteres: int, tiempo_seg: float
) -> LecturaPdf:
    contexto = multiprocessing.get_context("spawn")
    cola = contexto.Queue()
    proceso = contexto.Process(
        target=_leer, args=(contenido, maximo_paginas, maximo_caracteres, MEMORIA_BYTES, cola), daemon=True
    )
    limite = time.monotonic() + tiempo_seg
    proceso.start()
    try:
        while True:
            # El reloj se mira ANTES de cada espera y nunca se espera más de lo que queda:
            # así el tiempo límite se cumple aunque el proceso responda muy rápido.
            restante = limite - time.monotonic()
            if restante <= 0:
                estado, valor = "error", LENTO
                break
            try:
                estado, valor = cola.get(timeout=min(0.2, restante))
                break
            except queue.Empty:
                if not proceso.is_alive():  # murió sin responder: en Linux, por pasarse de memoria
                    try:
                        estado, valor = cola.get(timeout=0.5)
                    except queue.Empty:
                        estado, valor = "error", PESADO
                    break
    finally:
        proceso.join(timeout=1)
        if proceso.is_alive():
            proceso.kill()
            proceso.join()
        cola.close()

    if estado != "ok":
        raise ArchivoNoValido(valor)
    paginas, recortado = valor
    return LecturaPdf(paginas=paginas, recortado=recortado)
