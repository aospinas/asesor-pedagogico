"""Mensajes de validación en español sencillo (regla 6 de CLAUDE.md).

Pydantic explica los errores en inglés. Aquí se traducen según el tipo de error.
Nunca se devuelve lo que escribió la persona: podría ser una contraseña.
"""

from typing import Any

MENSAJES = {
    "missing": "Falta este dato.",
    "extra_forbidden": "Hay un dato que no se esperaba.",
    "string_too_short": "Es muy corto. Mínimo de caracteres: {min_length}.",
    "string_too_long": "Es muy largo. Máximo de caracteres: {max_length}.",
    "string_pattern_mismatch": "No tiene el formato esperado.",
    "enum": "No es una de las opciones permitidas.",
    "uuid_parsing": "No es un identificador válido.",
    "json_invalid": "Los datos no se pudieron leer.",
    "greater_than_equal": "El número es muy pequeño.",
    "less_than_equal": "El número es muy grande.",
}
MENSAJE_GENERICO = "El valor no es válido."


def explicar(error: dict[str, Any], desde: int = 0) -> dict[str, str]:
    """Convierte un error de Pydantic en {"campo", "mensaje"}.

    `desde` salta las primeras partes de la ubicación (en la API la primera es "body" o "path").
    """
    tipo = error["type"]
    if tipo == "value_error":
        # Estos mensajes los escribimos nosotros en app/esquemas.py, ya en español.
        mensaje = error["msg"].removeprefix("Value error, ")
    else:
        try:
            mensaje = MENSAJES.get(tipo, MENSAJE_GENERICO).format(**error.get("ctx", {}))
        except (KeyError, IndexError):
            mensaje = MENSAJE_GENERICO
    # Ni siquiera se devuelve el nombre de un dato que no se esperaba.
    campo = "" if tipo == "extra_forbidden" else ".".join(str(parte) for parte in error["loc"][desde:])
    return {"campo": campo, "mensaje": mensaje}
