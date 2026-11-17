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

El gancho de auditoría es una capa extra, NO una barrera: código Python decidido puede
saltárselo (por ejemplo con lo que no avisa a los ganchos). La barrera es el contenedor
(modo docker). Por eso en producción la app no arranca con el modo proceso y las pruebas
encendidas (app/config.py, D-18).
"""

import ast
import json
import os
import posixpath
import subprocess  # nosec B404
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
        "sys.remote_exec",
        # gc deja llegar a cualquier objeto, también al gancho y sus listas
        "gc.get_objects",
        "gc.get_referrers",
        "gc.get_referents",
        # sqlite puede cargar librerías nativas
        "sqlite3.enable_load_extension",
        "sqlite3.load_extension",
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
# Funciones sin evento de auditoría que dejan señalar a otro proceso (pidfd)
SIN_AUDITORIA = (("os", "pidfd_open"), ("posix", "pidfd_open"), ("signal", "pidfd_send_signal"))


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
        salida = f"{len(errores)} archivo(s) con error de sintaxis de {len(rutas_py)}:\n"
        salida += "\n".join(errores[:MAXIMO_LINEAS])
        if len(errores) > MAXIMO_LINEAS:
            salida += f"\n... y {len(errores) - MAXIMO_LINEAS} más."
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


def binario_ruff(carpeta: str) -> str:
    """Ruta absoluta del ejecutable de ruff instalado, nunca uno que venga en la entrega.

    No se usa `python -m ruff`: con -m, Python busca primero en la carpeta de trabajo, y un
    `ruff.py` o `ruff/__main__.py` del estudiante se ejecutaría en el paso que no debe
    ejecutar nada. El paquete `ruff` se importa aquí sin riesgo porque el lanzador corre con
    -I (la carpeta de trabajo no está en sys.path), y se comprueba que quede fuera de la entrega.
    """
    from ruff.__main__ import find_ruff_bin

    binario = os.path.realpath(find_ruff_bin())
    raiz = os.path.realpath(carpeta)
    if not os.path.isabs(binario) or binario == raiz or binario.startswith(raiz + os.sep):
        raise RuntimeError("El ejecutable de ruff no es el instalado.")
    return binario


def revisar_ruff(
    carpeta: str, reglas: tuple[str, ...], rutas: list[str], *, por_tipo: bool, binario: str
) -> dict:
    """ruff no ejecuta el código. Lo que la entrega no puede apagar:
    --isolated (no lee su configuración), --ignore-noqa (ni `# noqa` ni `# ruff: noqa` ni
    `# ruff: disable`), --no-respect-gitignore (ni .gitignore ni .ignore) y la lista explícita
    de archivos (ruff no se salta carpetas como build/ o venv/). Cada ruta va con "./" para
    que un archivo llamado "--algo.py" no se tome como opción."""
    seleccion = ",".join(reglas)
    comando = [binario, "check", "--isolated", "--no-cache", "--ignore-noqa", "--no-respect-gitignore"]
    comando += ["--select", seleccion, "--output-format", "json", "--target-version", "py312", "--"]
    comando += ["./" + r for r in rutas]
    entorno = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": carpeta, "RAYON_NUM_THREADS": "2"}
    inicio = time.monotonic()
    hecho = subprocess.run(comando, cwd=carpeta, env=entorno, capture_output=True, text=True, check=False)  # noqa: S603  # nosec B603
    duracion = int((time.monotonic() - inicio) * 1000)
    visible = f"ruff check --isolated --ignore-noqa --select {seleccion} ({len(rutas)} archivo(s))"
    try:
        # Con --output-format json ruff siempre imprime una lista ("[]" si no hay nada):
        # una salida vacía o de otro tipo es una falla, nunca "sin hallazgos".
        hallazgos = json.loads(hecho.stdout)
        if not isinstance(hallazgos, list) or not all(isinstance(h, dict) for h in hallazgos):
            raise ValueError
    except ValueError:  # json.JSONDecodeError también es ValueError
        return {
            "comando": visible,
            "codigo_salida": hecho.returncode if hecho.returncode > 1 else 2,
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
    # ruff también revisa cuadernos de Jupyter y archivos de tipos
    rutas_ruff = sorted(a["ruta"] for a in archivos if a["ruta"].endswith((".py", ".pyi", ".ipynb")))
    binario = binario_ruff(carpeta)
    return {
        "sintaxis": revisar_sintaxis(carpeta, rutas_py),
        "estilo": revisar_ruff(carpeta, RUFF_ESTILO, rutas_ruff, por_tipo=True, binario=binario),
        "seguridad": revisar_ruff(carpeta, RUFF_SEGURIDAD, rutas_ruff, por_tipo=False, binario=binario),
    }


def crear_gancho(carpeta: str, raices_permitidas: tuple[str, ...] = ()):
    """Gancho de auditoría para cuando corre el código del estudiante.

    Todo lo que usa queda guardado en el cierre al crearlo: si el estudiante cambia las
    listas de este módulo (`import __main__`) o funciones de `os`, el gancho no se entera.
    `raices_permitidas`: carpetas de donde sí se pueden cargar extensiones nativas (las de
    Python instalado); cualquier otra se rechaza.
    """
    realpath, normpath, fsdecode, fspath = os.path.realpath, posixpath.normpath, os.fsdecode, os.fspath
    separador = os.sep
    carpeta = realpath(carpeta)
    propio = str(os.getpid())
    bloqueados, prefijos = frozenset(EVENTOS_BLOQUEADOS), tuple(PREFIJOS_BLOQUEADOS)
    de_archivo, nativas = frozenset(EVENTOS_DE_ARCHIVO), tuple(EXTENSIONES_NATIVAS)
    permitidas, escritura = frozenset(ESCRITURA_PERMITIDA), ESCRITURA
    raices = tuple(realpath(r) + separador for r in raices_permitidas)
    rechazo = PermissionError

    def texto_de(ruta) -> str | None:
        try:
            return fsdecode(fspath(ruta))
        except TypeError:
            return None

    def adentro(ruta) -> bool:
        """La ruta (relativa a la carpeta de trabajo real) queda dentro de la carpeta."""
        texto = texto_de(ruta)
        if texto is None:
            return False
        absoluta = realpath(texto)
        return absoluta == carpeta or absoluta.startswith(carpeta + separador)

    def nativa(ruta) -> bool:
        texto = texto_de(ruta)
        return texto is not None and texto.lower().endswith(nativas)

    def otro_proceso(texto: str) -> bool:
        """/proc de otro proceso, también escrito como //proc, /proc/self/../N o con enlaces."""
        for forma in ("/" + normpath(texto.replace("\\", "/")).lstrip("/"), realpath(texto)):
            partes = forma.replace("\\", "/").split("/")
            if len(partes) > 2 and partes[1] == "proc" and partes[2].isdigit() and partes[2] != propio:
                return True
        return False

    def gancho(evento: str, args: tuple) -> None:
        if evento in bloqueados or evento.startswith(prefijos):
            raise rechazo(f"El sandbox no permite '{evento}'.")
        if evento == "open":
            ruta, modo, banderas = (tuple(args) + (None, None, None))[:3]
            if isinstance(ruta, int):  # descriptor que ya estaba abierto
                return
            texto = texto_de(ruta) or ""
            if otro_proceso(texto):
                raise rechazo("El sandbox no permite leer otros procesos.")
            escribe = (isinstance(modo, str) and any(c in modo for c in "wax+")) or (
                isinstance(banderas, int) and banderas & escritura
            )
            if escribe and texto not in permitidas and (not adentro(ruta) or nativa(ruta)):
                raise rechazo("El sandbox solo permite escribir en su carpeta.")
        elif evento in de_archivo:
            caminos = [a for a in args[:2] if isinstance(a, (str, bytes, os.PathLike))]
            if any(not adentro(c) or nativa(c) for c in caminos):
                raise rechazo("El sandbox solo permite cambiar archivos de su carpeta.")
        elif evento == "os.chdir":
            # Sin esto, las rutas relativas se saldrían de la carpeta. fchdir llega con un número.
            if not args or isinstance(args[0], int) or not adentro(args[0]):
                raise rechazo("El sandbox no permite salir de su carpeta.")
        elif evento == "sqlite3.connect":
            base = texto_de(args[0]) if args else None
            if base not in {":memory:", ""} and (
                base is None or base.startswith("file:") or not adentro(base)
            ):
                raise rechazo("El sandbox solo permite bases SQLite en su carpeta o en memoria.")
        elif evento == "import":
            # CPython solo pone el archivo en este evento al cargar una extensión nativa (los .py
            # llegan con None). Se acepta solo si está en Python instalado: así no pasa una .so de
            # la entrega ni una cargada desde /proc/self/fd con memfd, tenga el nombre que tenga.
            archivo = texto_de(args[1]) if len(args) > 1 and args[1] is not None else None
            if archivo and not realpath(archivo).startswith(raices):
                raise rechazo("El sandbox no permite cargar librerías nativas de la entrega.")

    return gancho


def quitar_funciones_sin_auditoria(objetivos: tuple[tuple[str, str], ...] = SIN_AUDITORIA) -> None:
    """Quita las funciones que señalan a otro proceso sin pasar por el gancho (pidfd).
    Solo se llama dentro del sandbox, nunca en el proceso web."""
    import importlib

    for nombre_modulo, funcion in objetivos:
        try:
            modulo = importlib.import_module(nombre_modulo)
        except ImportError:  # "posix" no existe en Windows
            continue
        if hasattr(modulo, funcion):
            delattr(modulo, funcion)


def raices_de_python() -> tuple[str, ...]:
    """Carpetas de la instalación de Python (biblioteca estándar y paquetes instalados)."""
    import sysconfig

    nombres = ("stdlib", "platstdlib", "purelib", "platlib")
    return tuple(sorted({sysconfig.get_path(n) for n in nombres if sysconfig.get_path(n)}))


def correr_pruebas(carpeta: str) -> int:
    temporal = os.path.join(carpeta, ".tmp")
    os.makedirs(temporal, exist_ok=True)
    os.environ["TMPDIR"] = temporal
    tempfile.tempdir = temporal
    import pytest  # se importa antes del gancho: es nuestro, no del estudiante

    quitar_funciones_sin_auditoria()
    sys.addaudithook(crear_gancho(carpeta, raices_de_python()))
    sys.dont_write_bytecode = True
    argumentos = ["-q", "-p", "no:cacheprovider", "--color=no", "--basetemp", os.path.join(temporal, "pt")]
    return int(pytest.main(argumentos))


def main() -> int:
    # Sin -I (o -P) la carpeta de trabajo entra a sys.path y un `pytest.py` o `ruff/` de la
    # entrega reemplazaría al instalado: el lanzador no corre así.
    if not (sys.flags.isolated and sys.flags.safe_path):
        raise RuntimeError("El lanzador del sandbox debe correr con python -I.")
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
