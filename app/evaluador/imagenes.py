"""Imágenes de la entrega: tamaño en píxeles y descripción con un modelo de visión (RF-09).

Antes de mandar una imagen a la IA se leen el ancho y el alto de su cabecera (sin abrirla
con una librería de imágenes): una PNG de 2 MB puede decir que mide 50.000 × 50.000 y
pedir muchísima memoria o tokens al proveedor (pendiente de D-17).
"""

import base64
import struct

from app.archivos import ArchivoNoValido

MAXIMO_LADO = 4096
VERSION_PROMPT = "describir_imagen_v1"


NO_SE_LEE = "No se pudo leer el tamaño de la imagen."


def dimensiones(contenido: bytes) -> tuple[int, int]:
    """(ancho, alto) leídos de la cabecera de una PNG, JPG o WEBP. Una imagen cortada o con la
    cabecera rota da ArchivoNoValido (nunca struct.error)."""
    try:
        if contenido.startswith(b"\x89PNG\r\n\x1a\n") and contenido[12:16] == b"IHDR":
            return struct.unpack(">II", contenido[16:24])
        if contenido.startswith(b"\xff\xd8"):
            return _jpeg(contenido)
        if contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP":
            return _webp(contenido)
    except struct.error:
        raise ArchivoNoValido(NO_SE_LEE) from None
    raise ArchivoNoValido(NO_SE_LEE)


def _jpeg(contenido: bytes) -> tuple[int, int]:
    i = 2
    while i + 9 < len(contenido):
        if contenido[i] != 0xFF:
            break
        marca = contenido[i + 1]
        largo = struct.unpack(">H", contenido[i + 2 : i + 4])[0]
        # Marcas SOF (inicio de imagen): ahí van alto y ancho
        if marca in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            alto, ancho = struct.unpack(">HH", contenido[i + 5 : i + 9])
            return ancho, alto
        if largo < 2:
            break
        i += 2 + largo
    raise ArchivoNoValido(NO_SE_LEE)


def _webp(contenido: bytes) -> tuple[int, int]:
    trozo = contenido[12:16]
    if trozo == b"VP8X" and len(contenido) >= 30:
        ancho = 1 + int.from_bytes(contenido[24:27], "little")
        alto = 1 + int.from_bytes(contenido[27:30], "little")
        return ancho, alto
    if trozo == b"VP8 " and len(contenido) >= 30:
        ancho, alto = struct.unpack("<HH", contenido[26:30])
        return ancho & 0x3FFF, alto & 0x3FFF
    if trozo == b"VP8L" and len(contenido) >= 25:
        bits = int.from_bytes(contenido[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    raise ArchivoNoValido(NO_SE_LEE)


def revisar(contenido: bytes) -> None:
    ancho, alto = dimensiones(contenido)
    if ancho < 1 or alto < 1 or ancho > MAXIMO_LADO or alto > MAXIMO_LADO:
        raise ArchivoNoValido(f"La imagen mide más de {MAXIMO_LADO} píxeles por lado: no se describe.")


def en_base64(contenido: bytes) -> str:
    return base64.b64encode(contenido).decode("ascii")
