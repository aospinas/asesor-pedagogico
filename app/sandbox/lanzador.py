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

# El resultado de "revisar" va en una línea que empieza con esta marca más un código al
# azar que manda la app en cada corrida (la entrega no lo conoce ni lo puede imitar).
MARCA = "@@RESULTADO_SANDBOX@@"
CODIFICACIONES_PERMITIDAS = frozenset({"utf-8", "utf8", "utf_8", "ascii", "us-ascii"})
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
SIN_AUDITORIA = (
    ("os", "pidfd_open"),
    ("posix", "pidfd_open"),
    ("signal", "pidfd_send_signal"),
    ("_signal", "pidfd_send_signal"),
)


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


def codificacion_declarada(texto: str) -> str | None:
    """La codificación que declara el archivo en sus 2 primeras líneas (PEP 263), en minúsculas.

    Con `# -*- coding: utf-7 -*-`, ast y ruff (que leen utf-8) ven un comentario y Python
    ejecuta código escondido en él: por eso solo se acepta utf-8."""
    import re

    for linea in texto.split("\n")[:2]:
        encontrada = re.match(r"^[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)", linea)
        if encontrada:
            return encontrada.group(1).lower()
    return None


def revisar_sintaxis(carpeta: str, rutas_py: list[str]) -> dict:
    inicio = time.monotonic()
    errores = []
    for ruta in rutas_py:
        with open(os.path.join(carpeta, *ruta.split("/")), encoding="utf-8") as fuente:
            texto = fuente.read()
        declarada = codificacion_declarada(texto)
        if declarada is not None and declarada not in CODIFICACIONES_PERMITIDAS:
            errores.append(f"{ruta}:1: declara la codificación {declarada!r}; solo se acepta utf-8")
            continue
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

    No es un cierre: en Python 3.13+ (PEP 667) el estudiante puede llegar al frame del gancho
    por un traceback y reescribir las variables de un cierre. Aquí todo lo que usa va en una
    tupla (que no se puede cambiar) atada con functools.partial a una función de módulo, y
    se desempaca en cada llamada: reescribir el frame de una llamada que ya terminó no cambia
    la siguiente. Las funciones del sistema (isinstance, realpath...) también van en la tupla,
    así cambiar `builtins` o `__main__` no lo engaña. Cambiar el código interno de esas
    funciones sí (no es una barrera, D-18).
    """
    import functools
    import pathlib

    realpath = os.path.realpath
    datos = (
        realpath(carpeta),
        os.sep,
        str(os.getpid()),
        frozenset(EVENTOS_BLOQUEADOS),
        tuple(PREFIJOS_BLOQUEADOS),
        frozenset(EVENTOS_DE_ARCHIVO),
        tuple(EXTENSIONES_NATIVAS),
        frozenset(ESCRITURA_PERMITIDA),
        ESCRITURA,
        tuple(realpath(r) + os.sep for r in raices_permitidas),
        # Tipos de ruta que se aceptan tal cual: sin __fspath__ del estudiante, que podría
        # devolver una ruta al revisar y otra al abrir.
        (str, bytes, pathlib.PurePosixPath, pathlib.PosixPath, pathlib.PureWindowsPath, pathlib.WindowsPath),
        realpath,
        posixpath.normpath,
        os.fsdecode,
        os.fspath,
        isinstance,
        type,
        any,
        len,
        PermissionError,
    )
    return functools.partial(_evaluar_evento, datos=datos)


def _evaluar_evento(evento: str, args: tuple, *, datos: tuple) -> None:
    """El gancho. Solo usa lo que trae `datos` (ver crear_gancho)."""
    (
        carpeta,
        separador,
        propio,
        bloqueados,
        prefijos,
        de_archivo,
        nativas,
        permitidas,
        escritura,
        raices,
        tipos_ruta,
        realpath,
        normpath,
        fsdecode,
        fspath,
        es_tipo,
        tipo_de,
        alguno,
        largo,
        rechazo,
    ) = datos

    if evento in bloqueados or evento.startswith(prefijos):
        raise rechazo(f"El sandbox no permite '{evento}'.")

    def texto_de(ruta):
        # Solo los tipos exactos; cualquier otro objeto cuenta como "afuera".
        if tipo_de(ruta) not in tipos_ruta:
            return None
        return fsdecode(fspath(ruta))

    def adentro(ruta) -> bool:
        texto = texto_de(ruta)
        if texto is None:
            return False
        absoluta = realpath(texto)
        return absoluta == carpeta or absoluta.startswith(carpeta + separador)

    def nativa(ruta) -> bool:
        texto = texto_de(ruta)
        return texto is not None and texto.lower().endswith(nativas)

    if evento == "open":
        ruta, modo, banderas = (args + (None, None, None))[:3]  # args ya es tupla (sin builtins)
        if es_tipo(ruta, int) and tipo_de(ruta) is not bool:  # descriptor que ya estaba abierto
            return
        texto = texto_de(ruta)
        if texto is None:
            raise rechazo("El sandbox solo acepta rutas de texto.")
        # /proc de otro proceso, también escrito como //proc, /proc/self/../N o con enlaces
        for forma in ("/" + normpath(texto.replace("\\", "/")).lstrip("/"), realpath(texto)):
            partes = forma.replace("\\", "/").split("/")
            if largo(partes) > 2 and partes[1] == "proc" and partes[2].isdigit() and partes[2] != propio:
                raise rechazo("El sandbox no permite leer otros procesos.")
        escribe = (es_tipo(modo, str) and alguno(c in modo for c in "wax+")) or (
            es_tipo(banderas, int) and banderas & escritura
        )
        if escribe and texto not in permitidas and (not adentro(ruta) or nativa(ruta)):
            raise rechazo("El sandbox solo permite escribir en su carpeta.")
    elif evento in de_archivo:
        # Los argumentos que son rutas. Números, None y tuplas (por ejemplo los tiempos de
        # os.utime) no lo son; cualquier otro objeto se toma como ruta y, si no es de un tipo
        # aceptado, cuenta como "afuera".
        caminos = [a for a in args[:2] if not es_tipo(a, (int, float, tuple, list, type(None)))]
        if alguno(not adentro(c) or nativa(c) for c in caminos):
            raise rechazo("El sandbox solo permite cambiar archivos de su carpeta.")
    elif evento == "os.chdir":
        # Sin esto, las rutas relativas se saldrían de la carpeta. fchdir llega con un número.
        if not args or es_tipo(args[0], int) or not adentro(args[0]):
            raise rechazo("El sandbox no permite salir de su carpeta.")
    elif evento.startswith("sqlite3."):
        # SQLite escribe con ATTACH o VACUUM INTO sin pasar por el gancho: no se usa en las pruebas.
        raise rechazo("El sandbox no permite SQLite en las pruebas.")
    elif evento == "import":
        # CPython solo pone el archivo en este evento al cargar una extensión nativa (los .py
        # llegan con None). Se acepta solo si está en Python instalado: así no pasa una .so de
        # la entrega ni una cargada desde /proc/self/fd con memfd, tenga el nombre que tenga.
        archivo = args[1] if largo(args) > 1 else None
        if archivo is not None:
            texto = texto_de(archivo)
            if texto is None or not realpath(texto).startswith(raices):
                raise rechazo("El sandbox no permite cargar librerías nativas de la entrega.")


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
        import warnings

        # ast.parse avisa (SyntaxWarning) repitiendo líneas del estudiante: nada de eso sale.
        warnings.simplefilter("ignore")
        resultado = revisar(carpeta, datos["archivos"])
        marca = MARCA + str(datos.get("marca", ""))
        sys.stdout.write(marca + json.dumps(resultado, ensure_ascii=True) + "\n")
        sys.stdout.flush()
        return 0
    if datos["tarea"] == "pruebas":
        sys.stdout.flush()
        return correr_pruebas(carpeta)
    raise ValueError("Tarea desconocida.")


if __name__ == "__main__":
    sys.exit(main())
