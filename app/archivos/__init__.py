"""Lectura segura de archivos subidos (rúbricas y entregas).

Nada de lo que hay aquí ejecuta el contenido de un archivo: solo lo lee con topes.
El código del estudiante se ejecuta únicamente en app/sandbox/.
"""


class ArchivoNoValido(ValueError):
    """El archivo no se puede usar. El mensaje es para la persona que lo subió, en español."""


class ArchivoMuyGrande(ArchivoNoValido):
    """El archivo pasa del tamaño permitido (la ruta responde 413)."""


def megas(cantidad_bytes: int) -> str:
    """5242880 -> '5 MB' (para los mensajes)."""
    return f"{cantidad_bytes // (1024 * 1024)} MB"
