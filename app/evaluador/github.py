"""Bajar el código de un repositorio público de GitHub como ZIP (RF-09, OWASP A10 SSRF).

- Solo se piden direcciones armadas por el backend con el usuario y el repositorio que ya
  validó PATRON_REPO_GITHUB: nunca una dirección escrita por el estudiante.
- Solo https y solo dos sitios: github.com y codeload.github.com. Las redirecciones se
  siguen a mano y cualquier otro sitio se rechaza.
- Tope de tamaño mientras se baja (no se confía en Content-Length) y tiempo límite.
- Lo bajado pasa por el mismo lector seguro de ZIP que una entrega normal.
"""

import re
import time
from urllib.parse import urlsplit

import httpx

from app.archivos import ArchivoNoValido, megas
from app.esquemas import PATRON_REPO_GITHUB

MAXIMO_BYTES = 15 * 1024 * 1024  # igual que el ZIP de código de una entrega
SITIOS_PERMITIDOS = frozenset({"github.com", "codeload.github.com"})
MAXIMO_REDIRECCIONES = 3
TIEMPO_SEG = 30  # por cada lectura
TIEMPO_TOTAL_SEG = 120  # toda la descarga

NO_SE_PUDO = "No se pudo bajar el repositorio de GitHub. Revisa que sea público y que exista."


def partes(enlace: str) -> tuple[str, str]:
    """(usuario, repositorio) de un enlace ya validado."""
    if not re.fullmatch(PATRON_REPO_GITHUB, enlace):
        raise ArchivoNoValido(NO_SE_PUDO)
    usuario, repositorio = enlace.rstrip("/").split("/")[-2:]
    return usuario, repositorio.removesuffix(".git")


def _permitida(url: str) -> bool:
    partes_url = urlsplit(url)
    return (
        partes_url.scheme == "https"
        and partes_url.hostname in SITIOS_PERMITIDOS
        and partes_url.port in (None, 443)
        and not partes_url.username
        and not partes_url.password
    )


def bajar_zip(enlace: str, cliente: httpx.Client | None = None) -> bytes:
    """El ZIP de la rama principal del repositorio (archive/HEAD.zip)."""
    usuario, repositorio = partes(enlace)
    url = f"https://github.com/{usuario}/{repositorio}/archive/HEAD.zip"
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=TIEMPO_SEG, follow_redirects=False)
    vence = time.monotonic() + TIEMPO_TOTAL_SEG
    try:
        for _ in range(MAXIMO_REDIRECCIONES + 1):
            if not _permitida(url):
                raise ArchivoNoValido(NO_SE_PUDO)
            with cliente.stream("GET", url, headers={"User-Agent": "asesor-pedagogico"}) as respuesta:
                if respuesta.is_redirect:
                    destino = respuesta.headers.get("location", "")
                    url = str(respuesta.url.join(destino))
                    continue
                if respuesta.status_code != 200:
                    raise ArchivoNoValido(NO_SE_PUDO)
                datos = bytearray()
                for pedazo in respuesta.iter_bytes():
                    datos.extend(pedazo)
                    if len(datos) > MAXIMO_BYTES:
                        raise ArchivoNoValido(f"El repositorio de GitHub pesa más de {megas(MAXIMO_BYTES)}.")
                    # El tiempo límite de httpx es por cada lectura: un servidor que manda a
                    # gotas lo reinicia siempre. Aquí se cuenta el tiempo total.
                    if time.monotonic() > vence:
                        raise ArchivoNoValido(NO_SE_PUDO)
                return bytes(datos)
        raise ArchivoNoValido(NO_SE_PUDO)  # demasiadas redirecciones
    except httpx.HTTPError:
        raise ArchivoNoValido(NO_SE_PUDO) from None
    finally:
        if propio:
            cliente.close()
