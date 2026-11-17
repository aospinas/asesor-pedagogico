"""Prueba manual del sandbox: `python -m app.sandbox entrega.zip` (o una carpeta).

Lee el código igual que una entrega (el ZIP con el lector de app/archivos/zip.py, sin
ejecutar nada) y muestra las verificaciones. Usa SANDBOX_MODE y los demás ajustes del .env.
"""

import sys
from pathlib import Path

from app.archivos import ArchivoNoValido
from app.archivos.zip import ArchivoCodigo, leer_zip
from app.sandbox import verificar

MAXIMO_CARPETA = 5 * 1024 * 1024


def _de_carpeta(carpeta: Path) -> list[ArchivoCodigo]:
    archivos, total = [], 0
    for ruta in sorted(carpeta.rglob("*")):
        relativa = ruta.relative_to(carpeta).as_posix()
        if not ruta.is_file() or ruta.is_symlink() or any(p.startswith(".") for p in relativa.split("/")):
            continue
        if "__pycache__" in relativa:
            continue
        try:
            texto = ruta.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        total += len(texto)
        if total > MAXIMO_CARPETA:
            break
        archivos.append(ArchivoCodigo(ruta=relativa, texto=texto))
    return archivos


def main(argumentos: list[str]) -> int:
    if len(argumentos) != 1:
        print("Uso: python -m app.sandbox <entrega.zip | carpeta>")
        return 2
    origen = Path(argumentos[0])
    if origen.is_dir():
        archivos = _de_carpeta(origen)
    else:
        try:
            archivos = leer_zip(origen.read_bytes()).archivos
        except (ArchivoNoValido, OSError) as error:
            print(f"No se pudo leer: {error}")
            return 1
    print(f"{len(archivos)} archivo(s) de texto. Revisando en el sandbox...\n")
    verificaciones = verificar(archivos)
    if not verificaciones:
        print("La entrega no trae archivos .py.")
    for v in verificaciones:
        estado = "TIEMPO AGOTADO" if v.tiempo_agotado else f"código de salida {v.codigo_salida}"
        print(f"=== {v.tipo.value}: {v.comando} ({estado}, {v.duracion_ms} ms)")
        print(v.salida, end="\n\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
