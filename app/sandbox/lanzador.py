"""Programa que corre DENTRO del sandbox (RF-10, RNF-03). Solo usa la biblioteca estándar.

El backend lo ejecuta como `python -I -B -c <este código>`, en un contenedor desechable
(modo docker) o en un proceso aparte con límites (modo proceso). `main()` nunca corre en
el proceso web: la app solo importa sus constantes y las pruebas sus funciones sueltas.

Recibe por la entrada estándar un JSON:
    {"tarea": "revisar" | "pruebas", "carpeta": str | null,
     "archivos": [{"ruta": str, "texto": str}], "limites": {...}}

- "revisar" no ejecuta el código del estudiante: ast.parse y ruff. Imprime una línea
  MARCA + JSON con los tres resultados.
- "pruebas" ejecuta pytest con el código del estudiante, después de poner los límites del
  sistema y un gancho de auditoría que bloquea red, procesos nuevos, ctypes, /proc de otros
  procesos y escrituras fuera de la carpeta de trabajo. Lo que imprime pytest es la salida.

El gancho de auditoría es una defensa extra: no se puede quitar desde Python, pero no es
tan fuerte como un contenedor (por eso en Render las pruebas vienen apagadas, D-18).
"""

import ast
import json
import os
import subprocess
import sys
import tempfile
import time

MARCA = "@@RESULTADO_SANDBOX@@"
EXTENSIONES_NATIVAS = (".so", ".pyd", ".dll", ".dylib")
MAXIMO_LINEAS = 60  # hallazgos que se listan por verificación; el resto se cuenta
RUFF_ESTILO = ("E", "F", "B")
RUFF_SEGURIDAD = ("S",)

# Eventos de auditoría que el código del estudiante no puede disparar
PREFIJOS_BLOQUEADOS = ("socket.", "ctypes.", "subprocess.", "_posixsubprocess.", "os.exec", "os.spawn")
EVENTOS_BLOQUEADOS = frozenset(
    {
        "os.system",
        "os.fork",
        "os.forkpty",
        "os.posix_spawn",
        "os.startfile",
        "os.kill",
        "os.killpg",
        "os.setsid",
        "pty.spawn",
        "sys._getframe_hidden",
        "sys.remote_exec",
        "sys.addaudithook",  # nadie más agrega ganchos (un gancho que lanza error frena el evento)
        "webbrowser.open",
        "urllib.Request",
        "http.client.connect",
        "ftplib.connect",
        "smtplib.connect",
        "imaplib.open",
        "poplib.connect",
        "telnetlib.Telnet.open",
    }
)
# Eventos que cambian archivos: todos sus caminos deben quedar dentro de la carpeta de trabajo
EVENTOS_DE_ARCHIVO = frozenset(
    {
        "os.remove",
        "os.rmdir",
        "os.rename",
        "os.link",
        "os.symlink",
        "os.chmod",
        "os.chown",
        "os.chflags",
        "os.lchmod",
        "os.lchown",
        "os.truncate",
        "os.mkdir",
        "os.mkfifo",
        "os.mknod",
        "os.utime",
        "os.setxattr",
        "os.removexattr",
        "shutil.rmtree",
        "shutil.copyfile",
        "shutil.copymode",
        "shutil.copystat",
        "shutil.move",
        "shutil.chown",
    }
)
ESCRITURA = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
ESCRITURA_PERMITIDA = frozenset({"/dev/null"})  # pytest abre su registro ahí


def ruta_valida(ruta: str) -> bool:
    """Ruta relativa que no se sale de la carpeta (el lector de ZIP ya lo revisó; esto es otra capa)."""
    if not ruta or "\x00" in ruta or "\\" in ruta or ruta.startswith("/"):
        return False
    partes = ruta.split("/")
    return all(p not in {"", ".", ".."} for p in partes) and len(ruta) <= 1024


def escribir_archivos(carpeta: str, archivos: list[dict]) -> None:
    for archivo in archivos:
        ruta = archivo["ruta"]
        if not ruta_valida(ruta):
            raise ValueError("Ruta no permitida en la entrega.")
        destino = os.path.join(carpeta, *ruta.split("/"))
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        with open(destino, "x", encoding="utf-8", newline="") as salida:
            salida.write(archivo["texto"])


def poner_limites(limites: dict) -> None:
    """Límites del sistema (Linux). Se ponen antes de correr nada pesado."""
    import resource

    pares = [
        (resource.RLIMIT_CORE, 0),
        (resource.RLIMIT_CPU, limites.get("cpu_seg")),
        (resource.RLIMIT_AS, limites.get("memoria_bytes")),
        (resource.RLIMIT_FSIZE, limites.get("archivo_bytes")),
    ]
    if limites.get("procesos") is not None:
        # RLIMIT_NPROC cuenta TODOS los procesos e hilos del usuario, no solo los nuestros:
        # el tope es lo que ya tiene el usuario más el margen permitido.
        pares.append((resource.RLIMIT_NPROC, contar_tareas_del_usuario() + limites["procesos"]))
    for recurso, valor in pares:
        if valor is not None:
            resource.setrlimit(recurso, (valor, valor))


def contar_tareas_del_usuario() -> int:
    uid = os.getuid()
    total = 0
    for nombre in os.listdir("/proc"):
        if not nombre.isdigit():
            continue
        try:
            if os.stat(f"/proc/{nombre}").st_uid == uid:
                total += len(os.listdir(f"/proc/{nombre}/task"))
        except OSError:
            continue
    return total


def _rel(ruta: str, carpeta: str) -> str:
    try:
        relativa = os.path.relpath(ruta, carpeta)
    except ValueError:
        return ruta
    return relativa.replace(os.sep, "/")


def revisar_sintaxis(carpeta: str, rutas_py: list[str]) -> dict:
    inicio = time.monotonic()
    errores = []
    for ruta in rutas_py:
        with open(os.path.join(carpeta, *ruta.split("/")), encoding="utf-8") as fuente:
            texto = fuente.read()
        try:
            ast.parse(texto, filename=ruta)
        except SyntaxError as error:
            errores.append(f"{ruta}:{error.lineno or 0}: {error.msg}")
        except (RecursionError, MemoryError, ValueError) as error:
            errores.append(f"{ruta}:0: no se pudo analizar ({type(error).__name__})")
    if errores:
        salida = f"{len(errores)} archivo(s) con error de sintaxis de {len(rutas_py)}:\n" + "\n".join(errores)
    else:
        salida = f"Sin errores de sintaxis en {len(rutas_py)} archivo(s) .py."
    return {
        "comando": f"ast.parse en {len(rutas_py)} archivo(s) .py",
        "codigo_salida": 1 if errores else 0,
        "salida": salida,
        "duracion_ms": int((time.monotonic() - inicio) * 1000),
    }


def es_prueba(ruta: str) -> bool:
    nombre = ruta.rsplit("/", 1)[-1]
    return nombre.endswith(".py") and (nombre.startswith("test_") or nombre.endswith("_test.py"))


def filtrar_ruff(hallazgos: list[dict], carpeta: str, reglas: tuple[str, ...]) -> list[dict]:
    """Solo las reglas pedidas (ruff también reporta errores de sintaxis, que ya tienen su paso)
    y sin S101 (assert) en los archivos de pruebas, donde assert es lo normal."""
    utiles = []
    for h in hallazgos:
        codigo = h.get("code") or ""
        if reglas == RUFF_SEGURIDAD and not codigo.startswith(reglas):
            continue
        if codigo == "S101" and es_prueba(_rel(h.get("filename", ""), carpeta)):
            continue
        utiles.append(h)
    return utiles


def resumir_ruff(hallazgos: list[dict], carpeta: str, *, por_tipo: bool) -> str:
    if not hallazgos:
        return "Sin hallazgos."
    conteo: dict[str, int] = {}
    lineas = []
    for h in hallazgos:
        codigo = h.get("code") or "sintaxis"
        conteo[codigo] = conteo.get(codigo, 0) + 1
        fila = (h.get("location") or {}).get("row", 0)
        lineas.append(f"{_rel(h.get('filename', ''), carpeta)}:{fila}: {codigo} {h.get('message', '')}")
    texto = [f"{len(hallazgos)} hallazgo(s)."]
    if por_tipo:
        texto.append("Por tipo:")
        texto += [f"  {c}: {n}" for c, n in sorted(conteo.items(), key=lambda x: (-x[1], x[0]))]
    texto.append("Detalle:")
    texto += lineas[:MAXIMO_LINEAS]
    if len(lineas) > MAXIMO_LINEAS:
        texto.append(f"... y {len(lineas) - MAXIMO_LINEAS} más.")
    return "\n".join(texto)


def revisar_ruff(carpeta: str, reglas: tuple[str, ...], *, por_tipo: bool) -> dict:
    """ruff no ejecuta el código. --isolated: no lee la configuración que traiga la entrega."""
    seleccion = ",".join(reglas)
    comando = [sys.executable, "-m", "ruff", "check", "--isolated", "--no-cache"]
    comando += ["--select", seleccion, "--output-format", "json", "--target-version", "py312", "."]
    entorno = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": carpeta, "RAYON_NUM_THREADS": "2"}
    inicio = time.monotonic()
    hecho = subprocess.run(comando, cwd=carpeta, env=entorno, capture_output=True, text=True, check=False)  # noqa: S603
    duracion = int((time.monotonic() - inicio) * 1000)
    visible = f"ruff check --isolated --select {seleccion}"
    try:
        hallazgos = json.loads(hecho.stdout or "[]")
    except json.JSONDecodeError:
        return {
            "comando": visible,
            "codigo_salida": hecho.returncode,
            "salida": "ruff no pudo revisar el código.\n" + (hecho.stderr or "")[-2000:],
            "duracion_ms": duracion,
        }
    utiles = filtrar_ruff(hallazgos, carpeta, reglas)
    return {
        "comando": visible,
        # 0 = sin hallazgos, 1 = con hallazgos (los que quedan después de filtrar), 2 = ruff falló
        "codigo_salida": hecho.returncode if hecho.returncode > 1 else int(bool(utiles)),
        "salida": resumir_ruff(utiles, carpeta, por_tipo=por_tipo),
        "duracion_ms": duracion,
    }


def revisar(carpeta: str, archivos: list[dict]) -> dict:
    rutas_py = sorted(a["ruta"] for a in archivos if a["ruta"].endswith(".py"))
    return {
        "sintaxis": revisar_sintaxis(carpeta, rutas_py),
        "estilo": revisar_ruff(carpeta, RUFF_ESTILO, por_tipo=True),
        "seguridad": revisar_ruff(carpeta, RUFF_SEGURIDAD, por_tipo=False),
    }


def crear_gancho(carpeta: str):
    """Gancho de auditoría para cuando corre el código del estudiante."""
    carpeta = os.path.realpath(carpeta)
    propio = str(os.getpid())

    def adentro(ruta) -> bool:
        if isinstance(ruta, int):  # descriptor ya abierto
            return True
        try:
            ruta = os.fsdecode(ruta)
        except TypeError:
            return False
        absoluta = os.path.realpath(os.path.join(carpeta, ruta))
        return absoluta == carpeta or absoluta.startswith(carpeta + os.sep)

    def nativa(ruta) -> bool:
        return isinstance(ruta, (str, bytes)) and os.fsdecode(ruta).lower().endswith(EXTENSIONES_NATIVAS)

    def gancho(evento: str, args: tuple) -> None:
        if evento in EVENTOS_BLOQUEADOS or evento.startswith(PREFIJOS_BLOQUEADOS):
            raise PermissionError(f"El sandbox no permite '{evento}'.")
        if evento == "open":
            ruta, modo, banderas = (tuple(args) + (None, None, None))[:3]
            if isinstance(ruta, int):
                return
            texto = os.fsdecode(ruta) if isinstance(ruta, (str, bytes)) else ""
            if texto.startswith("/proc/"):
                parte = texto.split("/")[2] if texto.count("/") >= 2 else ""
                if parte not in {"self", "thread-self", propio}:
                    raise PermissionError("El sandbox no permite leer otros procesos.")
            escribe = (isinstance(modo, str) and any(c in modo for c in "wax+")) or (
                isinstance(banderas, int) and banderas & ESCRITURA
            )
            if escribe and texto not in ESCRITURA_PERMITIDA and (not adentro(ruta) or nativa(ruta)):
                raise PermissionError("El sandbox solo permite escribir en su carpeta.")
        elif evento in EVENTOS_DE_ARCHIVO:
            caminos = [a for a in args[:2] if isinstance(a, (str, bytes, os.PathLike))]
            if any(not adentro(c) or nativa(c) for c in caminos):
                raise PermissionError("El sandbox solo permite cambiar archivos de su carpeta.")

    return gancho


def correr_pruebas(carpeta: str) -> int:
    temporal = os.path.join(carpeta, ".tmp")
    os.makedirs(temporal, exist_ok=True)
    os.environ["TMPDIR"] = temporal
    tempfile.tempdir = temporal
    import pytest  # se importa antes del gancho: es nuestro, no del estudiante

    sys.addaudithook(crear_gancho(carpeta))
    sys.dont_write_bytecode = True
    argumentos = ["-q", "-p", "no:cacheprovider", "--color=no", "--basetemp", os.path.join(temporal, "pt")]
    return int(pytest.main(argumentos))


def main() -> int:
    datos = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    carpeta = datos.get("carpeta") or tempfile.mkdtemp(prefix="sandbox-")
    escribir_archivos(carpeta, datos["archivos"])
    os.chdir(carpeta)
    if sys.platform.startswith("linux"):
        poner_limites(datos.get("limites") or {})
    if datos["tarea"] == "revisar":
        resultado = revisar(carpeta, datos["archivos"])
        sys.stdout.write(MARCA + json.dumps(resultado, ensure_ascii=False) + "\n")
        sys.stdout.flush()
        return 0
    if datos["tarea"] == "pruebas":
        sys.stdout.flush()
        return correr_pruebas(carpeta)
    raise ValueError("Tarea desconocida.")


if __name__ == "__main__":
    sys.exit(main())
