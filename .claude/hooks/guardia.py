"""Guardrail de Claude Code (hook PreToolUse).

Bloquea acciones peligrosas antes de que pasen. Claude Code envía por stdin un
JSON con `tool_name` y `tool_input`. Si este script sale con código 2, la
acción se bloquea y el mensaje de stderr le llega a Claude para que corrija.
"""

import json
import re
import sys

# Flujo de Git: Claude sube su rama y abre el PR; Andrés hace el merge en GitHub
SOLO_PR = "No se hace push a main: sube tu rama y abre un PR; el merge lo hace Andrés."
MERGE_HUMANO = "El merge lo hace Andrés en GitHub: abre un PR y espera."

# Comandos de terminal que nunca se deben correr sin un humano
COMANDOS_BLOQUEADOS = [
    (r"git\s+push\b.*\s(main|master)\b", SOLO_PR),
    (r"git\s+push\b.*\s(HEAD|\S+):(main|master)\b", SOLO_PR),
    (r"gh\s+pr\s+merge\b", MERGE_HUMANO),
    (r"git\s+merge\b.*\b(feat|fix)/", MERGE_HUMANO),
    (r"git\s+push\b.*(--force|-f\b)", "Push forzado bloqueado."),
    (r"git\s+reset\s+--hard", "reset --hard bloqueado: puede borrar trabajo."),
    (
        r"\brm\s+-[a-z]*r[a-z]*f|\brm\s+-[a-z]*f[a-z]*r",
        "Borrado recursivo bloqueado. Pide confirmación al humano.",
    ),
    (r"Remove-Item\b.*-Recurse", "Borrado recursivo bloqueado. Pide confirmación al humano."),
    (r"\b(del|rd|rmdir)\s+/s", "Borrado recursivo bloqueado. Pide confirmación al humano."),
    (
        r"(curl|wget|iwr|Invoke-WebRequest)\b.*\|\s*(sh|bash|iex|python)",
        "No se ejecutan scripts descargados de internet.",
    ),
    (r"(cat|type|more|less|Get-Content|gc)\s+\S*\.env(\s|$)", "No se leen secretos de .env."),
    (
        r"\bprintenv\b|\benv\s*$|Get-ChildItem\s+env:",
        "No se listan variables de entorno: pueden tener secretos.",
    ),
]

# Archivos que Claude no debe leer ni escribir
ARCHIVO_SECRETO = re.compile(r"(^|[\\/])\.env(\.(?!example$)[^\\/]*)?$")


def bloquear(motivo: str) -> None:
    print(f"[guardia] {motivo}", file=sys.stderr)
    sys.exit(2)


def main() -> None:
    try:
        datos = json.load(sys.stdin)
    except json.JSONDecodeError:
        return  # Si no entiende la entrada, no estorba

    herramienta = datos.get("tool_name", "")
    entrada = datos.get("tool_input", {}) or {}

    if herramienta == "Bash":
        comando = entrada.get("command", "")
        for patron, motivo in COMANDOS_BLOQUEADOS:
            if re.search(patron, comando, flags=re.IGNORECASE):
                bloquear(motivo)

    if herramienta in {"Read", "Edit", "Write", "MultiEdit"}:
        ruta = entrada.get("file_path", "")
        if ARCHIVO_SECRETO.search(ruta):
            bloquear("Los archivos .env tienen secretos: usa .env.example.")


if __name__ == "__main__":
    main()
