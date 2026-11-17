"""Cómo se arranca el lanzador en cada modo (SRS sección 10, D-18).

- docker: contenedor desechable sin red, con límites de memoria, CPU y procesos, sistema
  de archivos de solo lectura y sin capacidades. Si se pasa del tiempo, `docker kill`.
- proceso: proceso aparte en su propio grupo, con entorno vacío y `python -I`. Los límites
  los pone el lanzador (RLIMIT). Si se pasa del tiempo, se mata el grupo entero. Solo Linux.

En los dos casos el código entra por la entrada estándar (no se monta ninguna carpeta del
equipo) y la salida se lee con tope: aunque el código imprima gigas, la app guarda poco.
"""

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

LANZADOR = Path(__file__).with_name("lanzador.py")
MAXIMO_LEIDO = 256 * 1024  # bytes de salida que se guardan en memoria; el resto se descarta
ESPERA_CIERRE_SEG = 5
PROCESOS = 32
CPU_SEG = 30
ARCHIVO_BYTES = 10 * 1024 * 1024
CPUS_DOCKER = "0.5"
USUARIO_DOCKER = "10001:10001"
# Variables que el cliente de Docker necesita para hablar con Docker Desktop o el servicio.
# Ninguna lleva secretos de la app; las demás no se le pasan.
VARIABLES_DOCKER = (
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "USERPROFILE",
    "HOME",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "TEMP",
    "TMP",
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_CONFIG",
    "DOCKER_CERT_PATH",
    "DOCKER_TLS_VERIFY",
    "XDG_RUNTIME_DIR",
)
PR_SET_DUMPABLE = 4


class SandboxNoDisponible(Exception):
    """El sandbox no puede correr en este equipo (sin Docker, sin imagen o modo no soportado)."""


@dataclass(frozen=True)
class Corrida:
    codigo_salida: int | None
    salida: bytes
    recortada: bool
    duracion_ms: int
    tiempo_agotado: bool


def _lanzador() -> str:
    return LANZADOR.read_text(encoding="utf-8")


def _correr(comando: list[str], entrada: bytes, tiempo_seg: float, al_vencer, **opciones) -> Corrida:
    """Corre el comando con la entrada dada, lee la salida con tope y lo corta al vencer el tiempo."""
    inicio = time.monotonic()
    proceso = subprocess.Popen(  # noqa: S603 (comando armado por el backend, sin shell)
        comando, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **opciones
    )
    leido = bytearray()
    recortada = False

    def escribir() -> None:
        try:
            proceso.stdin.write(entrada)
            proceso.stdin.close()
        except OSError:  # el proceso murió antes de leer todo
            pass

    def leer() -> None:
        nonlocal recortada
        while bloque := proceso.stdout.read(65536):
            espacio = MAXIMO_LEIDO - len(leido)
            if espacio > 0:
                leido.extend(bloque[:espacio])
            if len(bloque) > espacio:
                recortada = True

    hilos = [threading.Thread(target=escribir, daemon=True), threading.Thread(target=leer, daemon=True)]
    for hilo in hilos:
        hilo.start()
    agotado = False
    try:
        proceso.wait(timeout=max(tiempo_seg, 0.1))
    except subprocess.TimeoutExpired:
        agotado = True
        al_vencer(proceso)
        proceso.kill()
        proceso.wait()
    for hilo in hilos:
        hilo.join(timeout=ESPERA_CIERRE_SEG)
    proceso.stdout.close()
    return Corrida(
        codigo_salida=None if agotado else proceso.returncode,
        salida=bytes(leido),
        recortada=recortada,
        duracion_ms=int((time.monotonic() - inicio) * 1000),
        tiempo_agotado=agotado,
    )


def _datos(tarea: str, archivos: list[dict], carpeta: str | None, memoria_mb: int) -> bytes:
    limites = {
        "cpu_seg": CPU_SEG,
        "memoria_bytes": memoria_mb * 1024 * 1024,
        "archivo_bytes": ARCHIVO_BYTES,
        # ruff usa hilos y no ejecuta el código: el tope de procesos va solo en las pruebas
        "procesos": PROCESOS if tarea == "pruebas" else None,
    }
    datos = {"tarea": tarea, "carpeta": carpeta, "archivos": archivos, "limites": limites}
    return json.dumps(datos, ensure_ascii=False).encode("utf-8")


# ---------- Modo docker ----------


def comando_docker(nombre: str, imagen: str, memoria_mb: int, codigo: str) -> list[str]:
    """El `docker run` con todos los límites. Se prueba aparte para que nadie quite uno sin ver."""
    return [
        "docker",
        "run",
        "--rm",
        "-i",
        "--pull",
        "never",  # nunca se baja una imagen de internet en medio de una evaluación
        "--name",
        nombre,
        "--network",
        "none",
        "--memory",
        f"{memoria_mb}m",
        "--memory-swap",
        f"{memoria_mb}m",
        "--cpus",
        CPUS_DOCKER,
        "--pids-limit",
        str(PROCESOS),
        "--read-only",
        "--tmpfs",
        f"/tmp:rw,noexec,nosuid,nodev,size={ARCHIVO_BYTES // (1024 * 1024)}m",  # noqa: S108 (/tmp del contenedor)
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        USUARIO_DOCKER,
        "--ulimit",
        "core=0",
        "--workdir",
        "/tmp",  # noqa: S108 (/tmp del contenedor, un tmpfs desechable)
        imagen,
        "python",
        "-I",
        "-B",
        "-c",
        codigo,
    ]


def _entorno_docker() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k.upper() in VARIABLES_DOCKER}


def revisar_docker(imagen: str) -> None:
    """Lanza SandboxNoDisponible con un aviso claro si Docker no corre o falta la imagen."""
    try:
        hecho = subprocess.run(  # noqa: S603
            ["docker", "image", "inspect", "--format", "{{.Id}}", imagen],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=20,
            env=_entorno_docker(),
            check=False,
        )
    except FileNotFoundError as error:
        raise SandboxNoDisponible("Docker no está instalado en este equipo.") from error
    except subprocess.TimeoutExpired as error:
        raise SandboxNoDisponible("Docker no responde. Revisa que Docker Desktop esté abierto.") from error
    if hecho.returncode != 0:
        detalle = (hecho.stderr or "").lower()
        if "no such image" in detalle or "no such object" in detalle:
            raise SandboxNoDisponible(
                f"Falta la imagen del sandbox ({imagen}). Créala con: "
                f"docker build -t {imagen} -f sandbox.Dockerfile ."
            )
        raise SandboxNoDisponible("Docker no responde. Revisa que Docker Desktop esté abierto.")


def correr_docker(
    tarea: str, archivos: list[dict], tiempo_seg: float, imagen: str, memoria_mb: int
) -> Corrida:
    nombre = f"asesor-sandbox-{uuid.uuid4().hex}"
    entorno = _entorno_docker()

    def matar(_proceso) -> None:
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            subprocess.run(  # noqa: S603
                ["docker", "kill", nombre],  # noqa: S607
                capture_output=True,
                timeout=20,
                env=entorno,
                check=False,
            )

    comando = comando_docker(nombre, imagen, memoria_mb, _lanzador())
    return _correr(comando, _datos(tarea, archivos, None, memoria_mb), tiempo_seg, matar, env=entorno)


# ---------- Modo proceso ----------


def proteger_proceso_web() -> None:
    """Marca el proceso web como no volcable (Linux): así un proceso del mismo usuario no
    puede leer /proc/<pid>/environ (donde están las llaves) ni engancharse con ptrace."""
    if not sys.platform.startswith("linux"):
        return
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
        raise SandboxNoDisponible("No se pudo proteger el proceso web.")


def entorno_proceso(carpeta: str) -> dict[str, str]:
    """El entorno del proceso aparte: nada de la app, solo lo mínimo para que Python corra."""
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "HOME": carpeta,
        "TMPDIR": carpeta,
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def correr_proceso(tarea: str, archivos: list[dict], tiempo_seg: float, memoria_mb: int) -> Corrida:
    if not sys.platform.startswith("linux"):
        raise SandboxNoDisponible("El modo proceso solo funciona en Linux. En el PC usa SANDBOX_MODE=docker.")
    proteger_proceso_web()
    carpeta = tempfile.mkdtemp(prefix="sandbox-")

    def matar(proceso) -> None:
        with contextlib.suppress(OSError):
            os.killpg(proceso.pid, signal.SIGKILL)  # todo el grupo, también los hijos

    try:
        return _correr(
            [sys.executable, "-I", "-B", "-c", _lanzador()],
            _datos(tarea, archivos, carpeta, memoria_mb),
            tiempo_seg,
            matar,
            env=entorno_proceso(carpeta),
            cwd=carpeta,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        _borrar(carpeta)


def _borrar(carpeta: str) -> None:
    """Borra la carpeta aunque el código del estudiante le haya quitado permisos a algo."""
    for raiz, carpetas, _ in os.walk(carpeta):
        for nombre in carpetas:
            with contextlib.suppress(OSError):
                os.chmod(os.path.join(raiz, nombre), 0o700)
    shutil.rmtree(carpeta, ignore_errors=True)
