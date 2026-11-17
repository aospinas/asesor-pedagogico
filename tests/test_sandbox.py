"""Pruebas del sandbox (RF-10, RNF-03, fila C3 de la matriz, SRS sección 10).

Las pruebas de la matriz (red, ciclo infinito, memoria, entorno) corren de verdad en cada
modo disponible en el equipo:
- proceso: solo en Linux (el CI).
- docker: si Docker responde y existe la imagen (docker build -t asesor-sandbox:1 -f sandbox.Dockerfile .).
Si no hay ningún modo, se saltan con el motivo. Las demás pruebas corren en cualquier equipo.
"""

import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

import app.sandbox as sandbox
from app.archivos.zip import ArchivoCodigo
from app.config import SECRETOS_DEL_ENTORNO, Ajustes
from app.esquemas import TipoVerificacion
from app.sandbox import ConfigSandbox, ejecutar, lanzador, limpiar_salida, verificar
from app.sandbox.ejecutar import Corrida, SandboxNoDisponible

IMAGEN = os.environ.get("SANDBOX_IMAGEN_PRUEBAS", "asesor-sandbox:1")
EN_LINUX = sys.platform.startswith("linux")
SECRETO = "sk-secreto-falso-de-prueba-123"


def _docker_listo() -> bool:
    try:
        ejecutar.revisar_docker(IMAGEN, tiempo_seg=5)
    except SandboxNoDisponible:
        return False
    return True


MODOS = [m for m, listo in (("proceso", EN_LINUX), ("docker", _docker_listo())) if listo]
sin_modos = pytest.mark.skipif(
    not MODOS, reason="No hay Linux ni imagen de Docker del sandbox en este equipo"
)


def _config(modo: str, **cambios) -> ConfigSandbox:
    base = ConfigSandbox(modo=modo, tiempo_seg=60, memoria_mb=256, imagen=IMAGEN, pruebas=True)
    return replace(base, **cambios)


def _archivos(**textos: str) -> list[ArchivoCodigo]:
    """_archivos(**{"src/main.py": "..."}) -> lista de ArchivoCodigo."""
    return [ArchivoCodigo(ruta=r, texto=t) for r, t in textos.items()]


def _por_tipo(verificaciones, tipo):
    return [v for v in verificaciones if v.tipo == tipo]


def _pruebas(verificaciones):
    (resultado,) = _por_tipo(verificaciones, TipoVerificacion.PRUEBAS)
    return resultado


# ---------- Contrato y casos sin ejecutar nada ----------


def test_sin_codigo_python_no_hay_verificaciones():
    assert verificar(_archivos(**{"README.md": "hola"}), _config("docker")) == []


def test_limpiar_salida_quita_nul_y_recorta():
    assert limpiar_salida(b"a\x00b") == "ab"
    larga = limpiar_salida("x" * 50000)
    assert len(larga) <= sandbox.MAXIMO_SALIDA
    assert larga.endswith(sandbox.RECORTADA)
    assert limpiar_salida("corta", recortada=True).endswith(sandbox.RECORTADA)


def test_entrega_demasiado_grande_no_se_manda(monkeypatch):
    monkeypatch.setattr(sandbox, "MAXIMO_ENTRADA", 10)
    (aviso,) = verificar(_archivos(**{"a.py": "x = 1\n" * 10}), _config("docker"))
    assert aviso.salida == sandbox.GRANDE
    assert aviso.codigo_salida is None


def test_sin_docker_no_tumba_la_app(monkeypatch):
    """RNF-10: si el sandbox no puede correr, queda un aviso y no un error."""

    def sin_docker(_imagen):
        raise SandboxNoDisponible("Docker no responde.")

    monkeypatch.setattr(ejecutar, "revisar_docker", sin_docker)
    (aviso,) = verificar(_archivos(**{"a.py": "x = 1\n"}), _config("docker"))
    assert aviso.salida == "Docker no responde."
    assert aviso.codigo_salida is None


@pytest.mark.parametrize(
    ("efecto", "texto"),
    [
        (FileNotFoundError(), "no está instalado"),
        (subprocess.CompletedProcess([], 1, "", "Error: No such image: x"), "docker build"),
        (subprocess.CompletedProcess([], 1, "", "Cannot connect to the Docker daemon"), "Docker Desktop"),
    ],
)
def test_revisar_docker_explica_que_falta(monkeypatch, efecto, texto):
    def correr(*_args, **_kwargs):
        if isinstance(efecto, Exception):
            raise efecto
        return efecto

    monkeypatch.setattr(ejecutar.subprocess, "run", correr)
    with pytest.raises(SandboxNoDisponible, match=texto):
        ejecutar.revisar_docker("asesor-sandbox:1")


def test_sandbox_ocupado_avisa(monkeypatch):
    monkeypatch.setattr(sandbox, "ESPERA_TURNO_SEG", 0.01)
    assert sandbox._TURNO.acquire(timeout=1)
    try:
        (aviso,) = verificar(_archivos(**{"a.py": "x = 1\n"}), _config("docker"))
    finally:
        sandbox._TURNO.release()
    assert aviso.salida == sandbox.OCUPADO


def _revision_falsa(*_args, **_kwargs):
    paso = {"comando": "c", "codigo_salida": 0, "salida": "ok", "duracion_ms": 1}
    datos = {"sintaxis": paso, "estilo": paso, "seguridad": paso}
    texto = ("ruido\n" + lanzador.MARCA + __import__("json").dumps(datos) + "\n").encode()
    return Corrida(codigo_salida=0, salida=texto, recortada=False, duracion_ms=5, tiempo_agotado=False)


def test_pruebas_apagadas_no_se_ejecutan(monkeypatch):
    """En Render (SANDBOX_PRUEBAS=false) solo se revisa sin ejecutar y se avisa por qué."""
    llamadas = []

    def correr(tarea, *args):
        llamadas.append(tarea)
        return _revision_falsa()

    monkeypatch.setattr(ejecutar, "revisar_docker", lambda _imagen: None)
    monkeypatch.setattr(ejecutar, "correr_docker", correr)
    archivos = _archivos(**{"main.py": "x = 1\n", "tests/test_main.py": "def test_a():\n    pass\n"})
    verificaciones = verificar(archivos, _config("docker", pruebas=False))
    assert llamadas == ["revisar"]
    assert [v.tipo for v in verificaciones] == [
        TipoVerificacion.SINTAXIS,
        TipoVerificacion.ESTATICO,
        TipoVerificacion.ESTATICO,
        TipoVerificacion.PRUEBAS,
    ]
    assert _pruebas(verificaciones).salida == sandbox.PRUEBAS_APAGADAS


def test_sin_archivos_de_prueba_no_corre_pytest(monkeypatch):
    llamadas = []
    monkeypatch.setattr(ejecutar, "revisar_docker", lambda _imagen: None)
    monkeypatch.setattr(
        ejecutar, "correr_docker", lambda tarea, *a: llamadas.append(tarea) or _revision_falsa()
    )
    verificaciones = verificar(_archivos(**{"main.py": "x = 1\n"}), _config("docker"))
    assert llamadas == ["revisar"]
    assert not _por_tipo(verificaciones, TipoVerificacion.PRUEBAS)


def test_salida_sin_marca_queda_como_fallo(monkeypatch):
    """Si el lanzador no devuelve su resultado (por ejemplo, murió), se dice y no se inventa nada."""
    monkeypatch.setattr(ejecutar, "revisar_docker", lambda _imagen: None)
    monkeypatch.setattr(
        ejecutar,
        "correr_docker",
        lambda *a: Corrida(
            codigo_salida=137, salida=b"Killed", recortada=False, duracion_ms=3, tiempo_agotado=False
        ),
    )
    (fallo,) = verificar(_archivos(**{"main.py": "x = 1\n"}), _config("docker"))
    assert fallo.salida.startswith(sandbox.FALLO)
    assert fallo.codigo_salida == 137


@pytest.mark.parametrize("ruta", ["tests/test_a.py", "test_b.py", "pkg/c_test.py"])
def test_reconoce_archivos_de_prueba(ruta):
    assert lanzador.es_prueba(ruta)


@pytest.mark.parametrize("ruta", ["main.py", "testing.py", "tests/conftest.py", "test_a.txt"])
def test_no_confunde_archivos_normales_con_pruebas(ruta):
    assert not lanzador.es_prueba(ruta)


# ---------- Configuración ----------


@pytest.mark.parametrize("imagen", ["--privileged", "asesor sandbox:1", "asesor-sandbox", "-v=/:/x:1"])
def test_imagen_no_puede_ser_una_opcion_de_docker(imagen):
    with pytest.raises(ValidationError):
        Ajustes(sandbox_imagen=imagen)


def test_modo_solo_docker_o_proceso():
    with pytest.raises(ValidationError):
        Ajustes(sandbox_mode="local")


# ---------- Cómo se arranca (los límites no se pueden quitar sin que falle una prueba) ----------


def test_docker_run_lleva_todos_los_limites():
    comando = ejecutar.comando_docker("asesor-sandbox-x", "asesor-sandbox:1", 256, "print(1)", 12.3)
    texto = " ".join(comando)
    for esperado in (
        "--rm",
        "--pull never",
        "--network none",
        "--memory 256m",
        "--memory-swap 256m",
        "--cpus 0.5",
        "--pids-limit 32",
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--user 10001:10001",
        "--ulimit core=0",
        "--label asesor-sandbox=1",
    ):
        assert esperado in texto
    tmpfs = "/tmp:rw,noexec,nosuid,nodev,size="  # noqa: S108 (/tmp del contenedor)
    assert any(p.startswith(tmpfs) for p in comando)
    # Nada del equipo entra al contenedor: ni carpetas, ni variables, ni privilegios
    for prohibido in (
        "-v",
        "--volume",
        "--mount",
        "-e",
        "--env",
        "--env-file",
        "--privileged",
        "--network=host",
    ):
        assert prohibido not in comando
    # Adentro, timeout mata al lanzador aunque falle el docker kill de la app
    despues = comando[comando.index("asesor-sandbox:1") :]
    assert despues[:9] == ["asesor-sandbox:1", "timeout", "-s", "KILL", "18", "python", "-I", "-B", "-c"]


def test_cliente_docker_no_recibe_secretos(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", SECRETO)
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", SECRETO)
    monkeypatch.setenv("DOCKER_HOST", "npipe:////./pipe/docker_engine")
    entorno = ejecutar._entorno_docker()
    assert SECRETO not in entorno.values()
    assert entorno["DOCKER_HOST"] == "npipe:////./pipe/docker_engine"


def test_proceso_aparte_arranca_con_entorno_vacio(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_API_KEY", SECRETO)
    entorno = ejecutar.entorno_proceso(str(tmp_path))
    assert set(entorno) == {"PATH", "LANG", "HOME", "TMPDIR", "PYTHONDONTWRITEBYTECODE"}
    assert SECRETO not in entorno.values()


@pytest.mark.skipif(EN_LINUX, reason="En Linux el modo proceso sí funciona")
def test_modo_proceso_fuera_de_linux_avisa():
    with pytest.raises(SandboxNoDisponible, match="solo funciona en Linux"):
        ejecutar.correr_proceso("revisar", [], 5, 256)


def test_lectura_de_salida_tiene_tope():
    """Aunque el proceso imprima megas, la app guarda como mucho MAXIMO_LEIDO."""
    codigo = "import sys; sys.stdout.write('x' * 3_000_000)"
    corrida = ejecutar._correr([sys.executable, "-c", codigo], b"", 30, lambda _p: None)
    assert corrida.codigo_salida == 0
    assert len(corrida.salida) == ejecutar.MAXIMO_LEIDO
    assert corrida.recortada


def test_tiempo_agotado_corta_el_proceso():
    vencidos = []
    inicio = time.monotonic()
    corrida = ejecutar._correr(
        [sys.executable, "-c", "import time; time.sleep(60)"], b"", 1, lambda p: vencidos.append(p.pid)
    )
    assert corrida.tiempo_agotado
    assert corrida.codigo_salida is None
    assert vencidos
    assert time.monotonic() - inicio < 15


# ---------- El lanzador (funciones sueltas, sin ejecutar código ajeno) ----------


@pytest.mark.parametrize(
    "ruta", ["../x.py", "/etc/x.py", "a/../../x.py", "a\\x.py", "a//x.py", "./x.py", "", "a\x00.py"]
)
def test_lanzador_rechaza_rutas_tramposas(tmp_path, ruta):
    assert not lanzador.ruta_valida(ruta)
    with pytest.raises(ValueError):
        lanzador.escribir_archivos(str(tmp_path), [{"ruta": ruta, "texto": "x"}])


def test_lanzador_escribe_dentro_de_la_carpeta(tmp_path):
    lanzador.escribir_archivos(str(tmp_path), [{"ruta": "src/a.py", "texto": "x = 1\r\n"}])
    assert (tmp_path / "src" / "a.py").read_bytes() == b"x = 1\r\n"


def test_sintaxis_dice_archivo_y_linea(tmp_path):
    lanzador.escribir_archivos(
        str(tmp_path),
        [{"ruta": "bien.py", "texto": "x = 1\n"}, {"ruta": "mal.py", "texto": "x = 1\ndef f(:\n"}],
    )
    resultado = lanzador.revisar_sintaxis(str(tmp_path), ["bien.py", "mal.py"])
    assert resultado["codigo_salida"] == 1
    assert "mal.py:2:" in resultado["salida"]
    assert "bien.py" not in resultado["salida"]


def test_ruff_filtra_assert_en_pruebas_y_sintaxis_en_seguridad(tmp_path):
    carpeta = str(tmp_path)
    hallazgos = [
        {"code": "S101", "filename": os.path.join(carpeta, "tests", "test_a.py"), "message": "assert"},
        {"code": "S101", "filename": os.path.join(carpeta, "main.py"), "message": "assert"},
        {"code": None, "filename": os.path.join(carpeta, "main.py"), "message": "sintaxis"},
        {"code": "S307", "filename": os.path.join(carpeta, "main.py"), "message": "eval"},
    ]
    seguridad = lanzador.filtrar_ruff(hallazgos, carpeta, lanzador.RUFF_SEGURIDAD)
    assert [(h["code"], h["filename"].endswith("main.py")) for h in seguridad] == [
        ("S101", True),
        ("S307", True),
    ]
    resumen = lanzador.resumir_ruff(seguridad, carpeta, por_tipo=False)
    assert resumen.startswith("2 hallazgo(s).")
    assert carpeta not in resumen  # rutas relativas, sin la carpeta interna


def test_resumen_de_ruff_cuenta_por_tipo_y_tiene_tope(tmp_path):
    hallazgos = [
        {"code": "E501", "filename": "a.py", "location": {"row": i}, "message": "larga"} for i in range(100)
    ]
    resumen = lanzador.resumir_ruff(hallazgos, str(tmp_path), por_tipo=True)
    assert "E501: 100" in resumen
    assert f"... y {100 - lanzador.MAXIMO_LINEAS} más." in resumen


class TestGancho:
    """El gancho de auditoría que se pone antes de correr el código del estudiante."""

    @pytest.fixture
    def gancho(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # en el sandbox, la carpeta de trabajo es la de la entrega
        return lanzador.crear_gancho(str(tmp_path))

    @pytest.mark.parametrize(
        ("evento", "args"),
        [
            ("socket.__new__", (None, 2, 1, 0)),
            ("socket.connect", (None, ("1.1.1.1", 80))),
            ("socket.getaddrinfo", ("example.com", 80, 0, 0, 0)),
            ("subprocess.Popen", ("sh", ["sh"], None, None)),
            ("_posixsubprocess.fork_exec", ([b"/bin/sh"], [b"sh"], None)),
            ("os.system", (b"ls",)),
            ("os.fork", ()),
            ("os.posix_spawn", ("/bin/sh", ["sh"], {})),
            ("os.exec", ("/bin/sh", ["sh"], {})),
            ("ctypes.dlopen", ("libc.so.6",)),
            ("sys.addaudithook", ()),
            ("os.kill", (1, 9)),
        ],
    )
    def test_bloquea_red_procesos_y_ctypes(self, gancho, evento, args):
        with pytest.raises(PermissionError):
            gancho(evento, args)

    @pytest.mark.parametrize("ruta", ["/proc/1/environ", "/proc/123/mem", b"/proc/1/environ"])
    def test_no_deja_leer_otros_procesos(self, gancho, ruta):
        with pytest.raises(PermissionError):
            gancho("open", (ruta, "r", os.O_RDONLY))

    def test_deja_leer_el_propio_proceso(self, gancho):
        gancho("open", ("/proc/self/status", "r", os.O_RDONLY))
        gancho("open", (f"/proc/{os.getpid()}/status", "r", os.O_RDONLY))

    def test_solo_escribe_en_su_carpeta(self, gancho, tmp_path):
        gancho("open", (str(tmp_path / "salida.txt"), "w", None))
        gancho("open", ("relativo.txt", None, os.O_WRONLY | os.O_CREAT))
        gancho("open", ("/dev/null", "w", None))
        gancho("open", ("/etc/passwd", "r", os.O_RDONLY))  # leer sí
        afuera = str(tmp_path.parent / "fuera.txt")
        for args in (
            (afuera, "w", None),
            (afuera, "a", None),
            (afuera, None, os.O_RDWR),
            ("../x", "w", None),
        ):
            with pytest.raises(PermissionError):
                gancho("open", args)

    def test_no_deja_crear_librerias_nativas(self, gancho, tmp_path):
        with pytest.raises(PermissionError):
            gancho("open", (str(tmp_path / "truco.so"), "wb", None))
        with pytest.raises(PermissionError):
            gancho(
                "os.rename",
                (str(tmp_path / "a.txt"), str(tmp_path / "truco.cpython-312-x86_64-linux-gnu.so")),
            )

    def test_no_deja_cambiar_archivos_de_afuera(self, gancho, tmp_path):
        gancho("os.remove", (str(tmp_path / "a.txt"), None))
        for evento in ("os.remove", "os.chmod", "shutil.rmtree", "os.symlink"):
            with pytest.raises(PermissionError):
                gancho(evento, ("/home/app/algo", None))


# ---------- Pruebas reales en el sandbox (matriz C3) ----------

PRUEBAS_HOSTILES = """
import os
import socket
import subprocess
import urllib.request

import pytest

SECRETO = "{secreto}"


def test_red_socket():
    with pytest.raises(OSError):
        socket.create_connection(("1.1.1.1", 80), timeout=3)


def test_red_descarga():
    with pytest.raises(OSError):
        urllib.request.urlopen("http://example.com", timeout=3)


def test_entorno_sin_secretos():
    nombres = {{"LLM_API_KEY", "DATABASE_URL", "JWT_SECRETO", "SUPABASE_SERVICE_KEY"}}
    assert not nombres & set(os.environ)
    assert all(SECRETO not in valor for valor in os.environ.values())


def test_no_lanza_procesos():
    with pytest.raises(OSError):
        subprocess.run(["true"], check=False)
    with pytest.raises(OSError):
        os.system("true")


def test_no_escribe_fuera_de_su_carpeta():
    with pytest.raises(OSError):
        open("/tmp/fuera-del-sandbox.txt", "w").close()


def test_escribe_en_tmp_path(tmp_path):
    archivo = tmp_path / "ok.txt"
    archivo.write_text("bien")
    assert archivo.read_text() == "bien"


def test_no_lee_procesos_ajenos():
    otro = os.getppid() or 1
    if otro == os.getpid():
        return
    with pytest.raises(OSError):
        open(f"/proc/{{otro}}/environ", "rb").read()


def test_proc_disfrazado():
    for ruta in ("//proc/1/environ", "/proc/self/../1/environ", "/proc/./1/environ"):
        with pytest.raises(OSError):
            open(ruta, "rb").read()


def test_cambiar_las_listas_del_gancho_no_sirve():
    import __main__

    __main__.PREFIJOS_BLOQUEADOS = ()
    __main__.EVENTOS_BLOQUEADOS = frozenset()
    __main__.EVENTOS_DE_ARCHIVO = frozenset()
    with pytest.raises(OSError):
        subprocess.run(["true"], check=False)
    with pytest.raises(OSError):
        socket.socket()


def test_sin_gc_ni_pidfd():
    import gc
    import signal

    with pytest.raises(OSError):
        gc.get_objects()
    with pytest.raises(OSError):
        gc.get_referrers(os)
    assert not hasattr(os, "pidfd_open")
    assert not hasattr(signal, "pidfd_send_signal")


def test_sqlite_solo_en_memoria_o_en_su_carpeta(tmp_path):
    import sqlite3

    sqlite3.connect(":memory:").close()
    sqlite3.connect(tmp_path / "ok.db").close()
    for base in ("/tmp/fuera.db", "file:/tmp/fuera.db?mode=rwc"):
        with pytest.raises(OSError):
            sqlite3.connect(base, uri=True)


def test_no_sale_de_su_carpeta_con_chdir(tmp_path):
    os.chdir(tmp_path)  # adentro sí
    with pytest.raises(OSError):
        os.chdir("/")
    with pytest.raises(OSError):
        os.chdir("/tmp")


def test_no_carga_librerias_nativas_propias():
    import glob
    import importlib.machinery
    import importlib.util
    import sys
    import sysconfig

    # Una extensión que todavía no esté cargada: si ya lo está, Python usa la que tiene y no
    # carga código nuevo (así que no habría nada que bloquear).
    carpeta = os.path.join(sysconfig.get_path("platstdlib"), "lib-dynload")
    candidatas = [
        (nombre, archivo)
        for nombre in ("_bz2", "_lzma", "_curses", "_dbm", "_gdbm", "_testcapi")
        if nombre not in sys.modules
        for archivo in glob.glob(os.path.join(carpeta, nombre + ".*so"))
    ]
    if not candidatas or not hasattr(os, "memfd_create"):
        pytest.skip("Esta instalación de Python no trae extensiones aparte")
    nombre, archivo = candidatas[0]
    with open(archivo, "rb") as original:
        datos = original.read()
    fd = os.memfd_create("truco")
    os.write(fd, datos)
    cargador = importlib.machinery.ExtensionFileLoader(nombre, f"/proc/self/fd/{{fd}}")
    spec = importlib.util.spec_from_loader(nombre, cargador)
    with pytest.raises(OSError):
        importlib.util.module_from_spec(spec)
"""
NOMBRES_HOSTILES = (
    "test_red_socket",
    "test_red_descarga",
    "test_entorno_sin_secretos",
    "test_no_lanza_procesos",
    "test_no_escribe_fuera_de_su_carpeta",
    "test_escribe_en_tmp_path",
    "test_no_lee_procesos_ajenos",
    "test_proc_disfrazado",
    "test_cambiar_las_listas_del_gancho_no_sirve",
    "test_sin_gc_ni_pidfd",
    "test_sqlite_solo_en_memoria_o_en_su_carpeta",
    "test_no_sale_de_su_carpeta_con_chdir",
    "test_no_carga_librerias_nativas_propias",
)


@pytest.fixture(scope="module", params=MODOS or ["ninguno"])
def hostil(request):
    """Una sola corrida por modo con todas las pruebas que intentan salirse del sandbox."""
    if request.param == "ninguno":
        pytest.skip("No hay Linux ni imagen de Docker del sandbox en este equipo")
    anterior = {k: os.environ.get(k) for k in ("LLM_API_KEY", "JWT_SECRETO")}
    os.environ.update(LLM_API_KEY=SECRETO, JWT_SECRETO=SECRETO)
    try:
        archivos = _archivos(**{"tests/test_hostil.py": PRUEBAS_HOSTILES.format(secreto=SECRETO)})
        yield _pruebas(verificar(archivos, _config(request.param)))
    finally:
        for clave, valor in anterior.items():
            if valor is None:
                os.environ.pop(clave, None)
            else:
                os.environ[clave] = valor


def _fallidas(resultado) -> list[str]:
    return [linea for linea in resultado.salida.splitlines() if linea.startswith(("FAILED", "ERROR"))]


@pytest.mark.parametrize("nombre", NOMBRES_HOSTILES)
def test_matriz_cada_escape_queda_bloqueado(hostil, nombre):
    assert not [f for f in _fallidas(hostil) if f"::{nombre}" in f], hostil.salida


def test_matriz_sin_errores_de_recoleccion(hostil):
    assert not [linea for linea in hostil.salida.splitlines() if linea.startswith("ERROR")], hostil.salida


def test_matriz_red_entorno_y_procesos_todas_pasan(hostil):
    """Matriz C3: red bloqueada y entorno vacío (las pruebas del estudiante lo comprueban)."""
    assert hostil.codigo_salida == 0, hostil.salida
    # La de librerías nativas se salta si Python no trae _bisect aparte
    assert f"{len(NOMBRES_HOSTILES)} passed" in hostil.salida or (
        f"{len(NOMBRES_HOSTILES) - 1} passed, 1 skipped" in hostil.salida
    )
    assert SECRETO not in hostil.salida


@sin_modos
@pytest.mark.parametrize("modo", MODOS)
def test_matriz_ciclo_infinito_se_corta(modo):
    archivos = _archivos(**{"test_ciclo.py": "def test_ciclo():\n    while True:\n        pass\n"})
    antes = _contenedores_sandbox() if modo == "docker" else set()
    inicio = time.monotonic()
    resultado = _pruebas(verificar(archivos, _config(modo, tiempo_seg=15)))
    assert resultado.tiempo_agotado
    assert resultado.codigo_salida is None
    assert resultado.salida.startswith(sandbox.AGOTADO)
    assert time.monotonic() - inicio < 40
    if modo == "docker":
        # docker kill + --rm tarda un momento en quitarlo. Solo cuentan los contenedores
        # nuevos: otra corrida del sandbox en el mismo equipo no hace fallar esta prueba.
        limite = time.monotonic() + 15
        while (nuevos := _contenedores_sandbox() - antes) and time.monotonic() < limite:
            time.sleep(0.5)
        assert not nuevos


def _contenedores_sandbox() -> set[str]:
    """Nombres de los contenedores del sandbox que siguen existiendo (vivos o saliendo)."""
    hecho = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{.Names}}", "--filter", "name=asesor-sandbox-"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    return set(hecho.stdout.split())


@sin_modos
@pytest.mark.parametrize("modo", MODOS)
def test_matriz_un_giga_de_memoria_falla(modo):
    archivos = _archivos(
        **{"test_memoria.py": "def test_memoria():\n    x = bytearray(1024 ** 3)\n    assert x\n"}
    )
    resultado = _pruebas(verificar(archivos, _config(modo)))
    assert not resultado.tiempo_agotado
    assert resultado.codigo_salida not in (0, None)
    assert "MemoryError" in resultado.salida or resultado.codigo_salida == 137


@sin_modos
@pytest.mark.parametrize("modo", MODOS)
def test_caso_normal_sintaxis_ruff_y_pytest(modo):
    archivos = _archivos(
        **{
            "src/main.py": "import os\n\n\ndef suma(a, b):\n    return a + b\n\n\nx = eval('1')\n",
            "src/malo.py": "def f(:\n    pass\n",
            "tests/test_main.py": (
                "import sys\nsys.path.insert(0, 'src')\nfrom main import suma\n\n\n"
                "def test_bien():\n    assert suma(1, 2) == 3\n\n\n"
                "def test_mal():\n    assert suma(1, 1) == 3\n"
            ),
            "datos.csv": "a,b\n1,2\n",
        }
    )
    sintaxis, estilo, seguridad, pruebas = verificar(archivos, _config(modo))

    assert sintaxis.tipo == TipoVerificacion.SINTAXIS
    assert sintaxis.codigo_salida == 1
    assert "src/malo.py:1:" in sintaxis.salida

    assert estilo.tipo == seguridad.tipo == TipoVerificacion.ESTATICO
    assert "F401" in estilo.salida
    assert "S307" in seguridad.salida
    assert "S101" not in seguridad.salida  # assert en pruebas no es hallazgo

    assert pruebas.codigo_salida == 1
    assert "1 failed, 1 passed" in pruebas.salida
    # Las rutas salen relativas: ni la carpeta interna del sandbox ni la del equipo
    for verificacion in (sintaxis, estilo, seguridad, pruebas):
        assert "sandbox-" not in verificacion.salida


IMPOSTOR = "import json, sys\nprint(json.dumps([]))\nprint('1 passed')\nsys.exit(0)\n"


@sin_modos
@pytest.mark.parametrize("modo", MODOS)
def test_entrega_no_puede_suplantar_a_ruff_ni_a_pytest(modo):
    """Un ruff.py, ruff/__main__.py o pytest.py de la entrega no reemplaza al instalado.

    Si se colara, "revisar" ejecutaría código del estudiante (en Render, sin gancho y con red)
    y podría decir "sin hallazgos" o "todo pasa" a su gusto."""
    archivos = _archivos(
        **{
            "ruff.py": IMPOSTOR,
            "ruff/__init__.py": IMPOSTOR,
            "ruff/__main__.py": IMPOSTOR,
            "pytest.py": IMPOSTOR,
            "_pytest/__init__.py": IMPOSTOR,
            "main.py": "import os\n\nx = eval('1')\n",
            "test_main.py": "def test_mal():\n    assert 1 == 2\n",
        }
    )
    sintaxis, estilo, seguridad, pruebas = verificar(archivos, _config(modo))
    assert "F401" in estilo.salida
    assert "S307" in seguridad.salida
    assert seguridad.codigo_salida == 1
    assert pruebas.codigo_salida == 1
    assert "1 failed" in pruebas.salida


def test_binario_de_ruff_dentro_de_la_entrega_se_rechaza(monkeypatch, tmp_path):
    import ruff.__main__

    monkeypatch.setattr(ruff.__main__, "find_ruff_bin", lambda: str(tmp_path / "ruff"))
    with pytest.raises(RuntimeError):
        lanzador.binario_ruff(str(tmp_path))


def test_binario_de_ruff_es_el_instalado(tmp_path):
    binario = lanzador.binario_ruff(str(tmp_path))
    assert os.path.isabs(binario)
    assert not binario.startswith(str(tmp_path))


def test_ruff_sin_salida_no_es_sin_hallazgos(tmp_path):
    """Si ruff no imprime su lista (falló o no era ruff), se dice que no pudo revisar."""
    resultado = lanzador.revisar_ruff(
        str(tmp_path), lanzador.RUFF_SEGURIDAD, ["a.py"], por_tipo=False, binario=sys.executable
    )
    assert resultado["codigo_salida"] == 2
    assert resultado["salida"].startswith("ruff no pudo revisar el código.")


def test_lanzador_se_niega_a_correr_sin_aislamiento():
    hecho = subprocess.run(
        [sys.executable, "-c", ejecutar._lanzador()],
        input=b"{}",
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert hecho.returncode != 0
    assert b"python -I" in hecho.stderr


@sin_modos
@pytest.mark.parametrize("modo", MODOS)
def test_salida_enorme_se_recorta(modo):
    archivos = _archivos(
        **{"test_ruido.py": "def test_ruido():\n    print('x' * 3_000_000)\n    assert False\n"}
    )
    resultado = _pruebas(verificar(archivos, _config(modo)))
    assert len(resultado.salida) <= sandbox.MAXIMO_SALIDA
    assert resultado.salida.endswith(sandbox.RECORTADA)


@pytest.mark.skipif(not EN_LINUX, reason="prctl y /proc solo existen en Linux")
def test_proceso_web_protegido_no_deja_leer_sus_variables():
    """Aunque algo se saltara el gancho, otro proceso del mismo usuario no lee /proc/<web>/environ."""
    if os.geteuid() == 0:
        pytest.skip("root puede leer todo; en Render la app no corre como root")
    ejecutar.proteger_proceso_web()
    hecho = subprocess.run(["cat", f"/proc/{os.getpid()}/environ"], capture_output=True, check=False)  # noqa: S607
    assert hecho.returncode != 0
    assert not hecho.stdout


# ---------- Arreglos de la Puerta 2 ----------


def _produccion(**cambios) -> dict:
    base = {
        "entorno": "produccion",
        "jwt_secreto": "x" * 40,
        "database_url": "postgresql+psycopg://u:c@h:5432/b",
        "origenes_permitidos": "https://asesor.onrender.com",
        "sandbox_mode": "proceso",
        "sandbox_pruebas": False,
    }
    return base | cambios


def test_produccion_no_arranca_con_proceso_y_pruebas():
    """En Render (modo proceso) el código del estudiante nunca se ejecuta."""
    with pytest.raises(ValidationError, match="SANDBOX_PRUEBAS"):
        Ajustes(**_produccion(sandbox_pruebas=True))
    Ajustes(**_produccion())  # apagadas: arranca
    Ajustes(**_produccion(sandbox_mode="docker", sandbox_pruebas=True))  # con contenedor: arranca


def test_render_apaga_las_pruebas():
    texto = Path(__file__).resolve().parent.parent.joinpath("render.yaml").read_text(encoding="utf-8")
    assert "key: SANDBOX_MODE\n        value: proceso" in texto
    assert 'key: SANDBOX_PRUEBAS\n        value: "false"' in texto


@pytest.fixture
def secretos_falsos(monkeypatch):
    """Pone secretos únicos en el entorno; monkeypatch los devuelve como estaban al final."""
    valor = f"{SECRETO}-{os.getpid()}-{time.monotonic_ns()}"
    for nombre in SECRETOS_DEL_ENTORNO:
        monkeypatch.setenv(nombre, valor)
    monkeypatch.setattr(ejecutar, "proteger_proceso_web", lambda: None)
    return valor


def test_preparar_proceso_web_saca_los_secretos_del_entorno(secretos_falsos):
    sandbox.preparar_proceso_web()
    assert not SECRETOS_DEL_ENTORNO & set(os.environ)
    # Un proceso hijo ya no los hereda
    hijo = subprocess.run(
        [sys.executable, "-c", "import os, sys; sys.stdout.write(repr(sorted(os.environ)))"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert secretos_falsos not in hijo.stdout
    assert not [n for n in SECRETOS_DEL_ENTORNO if n in hijo.stdout]


def test_la_app_sigue_teniendo_sus_ajustes_despues_de_preparar(secretos_falsos):
    from app.config import ajustes

    antes = ajustes().jwt_secreto
    sandbox.preparar_proceso_web()
    assert ajustes().jwt_secreto == antes  # quedaron guardados al leerlos


@pytest.mark.skipif(not EN_LINUX, reason="/proc solo existe en Linux")
def test_ningun_proceso_del_usuario_queda_con_los_secretos(monkeypatch):
    """El caso del revisor: el lector de PDF (spawn) deja un resource_tracker vivo con el
    entorno de la app. Después de preparar, ningún proceso nuevo lleva los secretos."""
    from archivos_prueba import pdf

    from app.archivos.pdf import leer_paginas

    if os.geteuid() == 0:
        pytest.skip("root puede leer todo; en Render la app no corre como root")
    valor = f"{SECRETO}-tracker-{time.monotonic_ns()}"
    for nombre in SECRETOS_DEL_ENTORNO:
        monkeypatch.setenv(nombre, valor)
    sandbox.preparar_proceso_web()
    leer_paginas(pdf(), maximo_paginas=5, maximo_caracteres=10000)
    uid = os.getuid()
    con_secreto = []
    for nombre in os.listdir("/proc"):
        if not nombre.isdigit():
            continue
        try:
            if os.stat(f"/proc/{nombre}").st_uid != uid:
                continue
            with open(f"/proc/{nombre}/environ", "rb") as entorno:
                if valor.encode() in entorno.read():
                    con_secreto.append(nombre)
        except OSError:
            continue
    assert not con_secreto


def test_limpiar_salida_quita_controles_y_colores():
    sucia = "\x1b[31mrojo\x1b[0m\r\nlinea\x07\u202eal reves\u202c\tfin\x85"
    assert limpiar_salida(sucia) == "[31mrojo[0m\nlineaal reves\tfin"


def _corrida(texto: str, **cambios) -> Corrida:
    datos = {"codigo_salida": 0, "salida": texto.encode(), "recortada": False, "duracion_ms": 4}
    return Corrida(**(datos | {"tiempo_agotado": False} | cambios))


@pytest.mark.parametrize(
    "paso",
    [
        {"comando": "c", "codigo_salida": "uno", "salida": "x", "duracion_ms": 1},
        {"comando": "c", "codigo_salida": 0, "salida": "x", "duracion_ms": -5},
        {"comando": "c", "codigo_salida": 0, "salida": "x", "duracion_ms": 1, "nota": 5},
        {"comando": "c" * 600, "codigo_salida": 0, "salida": "x", "duracion_ms": 1},
        "no es un diccionario",
    ],
)
def test_resultado_raro_del_lanzador_es_falla_y_no_error(monkeypatch, paso):
    datos = {"sintaxis": paso, "estilo": paso, "seguridad": paso}
    texto = lanzador.MARCA + __import__("json").dumps(datos)
    monkeypatch.setattr(ejecutar, "revisar_docker", lambda _imagen: None)
    monkeypatch.setattr(ejecutar, "correr_docker", lambda *a: _corrida(texto))
    (fallo,) = verificar(_archivos(**{"main.py": "x = 1\n"}), _config("docker"))
    assert fallo.salida.startswith(sandbox.FALLO)


@pytest.mark.parametrize("error", [OSError("docker desapareció"), FileNotFoundError(), RuntimeError("x")])
def test_error_al_lanzar_no_tumba_la_evaluacion(monkeypatch, error):
    def falla(*_a):
        raise error

    monkeypatch.setattr(ejecutar, "revisar_docker", lambda _imagen: None)
    monkeypatch.setattr(ejecutar, "correr_docker", falla)
    (aviso,) = verificar(_archivos(**{"main.py": "x = 1\n"}), _config("docker"))
    assert aviso.salida == sandbox.FALLO
    assert sandbox._TURNO.acquire(timeout=0.1)  # el turno quedó libre
    sandbox._TURNO.release()


def test_revisar_con_tiempo_agotado(monkeypatch):
    monkeypatch.setattr(ejecutar, "revisar_docker", lambda _imagen: None)
    monkeypatch.setattr(
        ejecutar, "correr_docker", lambda *a: _corrida("", codigo_salida=None, tiempo_agotado=True)
    )
    (aviso,) = verificar(_archivos(**{"main.py": "x = 1\n"}), _config("docker"))
    assert aviso.tiempo_agotado
    assert aviso.salida == sandbox.AGOTADO


def test_pruebas_sin_tiempo_restante(monkeypatch):
    """Si "revisar" se gastó todo el tiempo, pytest ni arranca y se dice por qué."""
    llamadas = []

    def revisar_lento(tarea, *a):
        llamadas.append(tarea)
        time.sleep(1.1)
        return _revision_falsa()

    monkeypatch.setattr(ejecutar, "revisar_docker", lambda _imagen: None)
    monkeypatch.setattr(ejecutar, "correr_docker", revisar_lento)
    archivos = _archivos(**{"main.py": "x = 1\n", "test_a.py": "def test_a():\n    pass\n"})
    pruebas = _pruebas(verificar(archivos, _config("docker", tiempo_seg=1)))
    assert llamadas == ["revisar"]
    assert pruebas.tiempo_agotado
    assert pruebas.salida == sandbox.SIN_TIEMPO


class TestGanchoEndurecido:
    @pytest.fixture
    def gancho(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        raiz = tmp_path.parent / "python-instalado"
        return lanzador.crear_gancho(str(tmp_path), (str(raiz),))

    def test_cambiar_las_listas_despues_no_lo_apaga(self, gancho, monkeypatch):
        monkeypatch.setattr(lanzador, "EVENTOS_BLOQUEADOS", frozenset())
        monkeypatch.setattr(lanzador, "PREFIJOS_BLOQUEADOS", ())
        with pytest.raises(PermissionError):
            gancho("subprocess.Popen", ("sh", ["sh"], None, None))
        with pytest.raises(PermissionError):
            gancho("socket.connect", (None, ("1.1.1.1", 80)))

    @pytest.mark.parametrize(
        "ruta", ["//proc/1/environ", "/proc/self/../1/environ", "/proc/./1/environ", "///proc/1/mem"]
    )
    def test_proc_disfrazado(self, gancho, ruta):
        with pytest.raises(PermissionError):
            gancho("open", (ruta, "r", os.O_RDONLY))

    @pytest.mark.parametrize("evento", ["gc.get_objects", "gc.get_referrers", "gc.get_referents"])
    def test_sin_gc(self, gancho, evento):
        with pytest.raises(PermissionError):
            gancho(evento, ())

    def test_chdir_solo_adentro(self, gancho, tmp_path):
        (tmp_path / "sub").mkdir()
        gancho("os.chdir", (str(tmp_path / "sub"),))
        gancho("os.chdir", ("sub",))
        for afuera in (str(tmp_path.parent), "..", 3):
            with pytest.raises(PermissionError):
                gancho("os.chdir", (afuera,))

    def test_escritura_relativa_se_mide_desde_la_carpeta_real(self, gancho, tmp_path):
        gancho("open", ("adentro.txt", "w", None))
        with pytest.raises(PermissionError):
            gancho("open", ("../afuera.txt", "w", None))

    def test_sqlite(self, gancho, tmp_path):
        gancho("sqlite3.connect", (":memory:",))
        gancho("sqlite3.connect", (str(tmp_path / "ok.db"),))
        for base in (str(tmp_path.parent / "fuera.db"), "file:x.db?mode=rwc", None):
            with pytest.raises(PermissionError):
                gancho("sqlite3.connect", (base,))
        for evento in ("sqlite3.enable_load_extension", "sqlite3.load_extension"):
            with pytest.raises(PermissionError):
                gancho(evento, (None, True))

    def test_extensiones_nativas_solo_de_python_instalado(self, gancho, tmp_path):
        instalada = str(tmp_path.parent / "python-instalado" / "lib-dynload" / "_bisect.so")
        gancho("import", ("_bisect", instalada, [], [], []))
        gancho("import", ("modulo_de_la_entrega", None, [], [], []))  # los .py llegan sin archivo
        for ruta in (
            str(tmp_path / "truco.so"),
            "/proc/self/fd/3",  # memfd: la ruta no termina en .so
            str(tmp_path / "x.cpython-312-x86_64-linux-gnu.so"),
            str(tmp_path / "sin_extension"),
        ):
            with pytest.raises(PermissionError):
                gancho("import", ("truco", ruta, [], [], []))


def test_quita_funciones_sin_auditoria(monkeypatch):
    """Con módulos falsos: quitarlas de verdad dañaría el proceso de las pruebas."""
    import types

    falso_os, falso_signal = types.ModuleType("falso_os"), types.ModuleType("falso_signal")
    falso_os.pidfd_open = lambda *a: 0
    falso_signal.pidfd_send_signal = lambda *a: None
    monkeypatch.setitem(sys.modules, "falso_os", falso_os)
    monkeypatch.setitem(sys.modules, "falso_signal", falso_signal)
    lanzador.quitar_funciones_sin_auditoria(
        (("falso_os", "pidfd_open"), ("falso_signal", "pidfd_send_signal"), ("falso_os", "no_existe"))
    )
    assert not hasattr(falso_os, "pidfd_open")
    assert not hasattr(falso_signal, "pidfd_send_signal")
    assert lanzador.SIN_AUDITORIA == (
        ("os", "pidfd_open"),
        ("posix", "pidfd_open"),
        ("signal", "pidfd_send_signal"),
    )


def test_raices_de_python_son_carpetas_absolutas():
    raices = lanzador.raices_de_python()
    assert raices
    assert all(os.path.isabs(r) for r in raices)


@sin_modos
@pytest.mark.parametrize("modo", MODOS)
def test_la_entrega_no_puede_esconder_hallazgos_de_ruff(modo):
    """# noqa, # ruff: noqa, # ruff: disable, .ignore, .gitignore y carpetas como build/ no
    esconden nada; y un archivo llamado "--fix.py" no se toma como opción de ruff."""
    malo = "x = eval(input())\n"
    archivos = _archivos(
        **{
            "a.py": "# ruff: noqa\n" + malo,
            "b.py": "x = eval(input())  # noqa: S307\n",
            "c.py": "# ruff: disable[S307]\n" + malo + "# ruff: enable[S307]\n",
            "build/d.py": malo,
            "venv/e.py": malo,
            "--fix.py": malo,
            ".ignore": "*\n",
            ".gitignore": "*\n",
            "pyproject.toml": "[tool.ruff]\nexclude = ['*']\n",
        }
    )
    _sintaxis, _estilo, seguridad = verificar(archivos, _config(modo))
    assert seguridad.salida.count("S307") == 6, seguridad.salida
    assert seguridad.codigo_salida == 1
    assert "(6 archivo(s))" in seguridad.comando


def test_sintaxis_lista_con_tope(tmp_path):
    rutas = [f"m{i}.py" for i in range(lanzador.MAXIMO_LINEAS + 5)]
    lanzador.escribir_archivos(str(tmp_path), [{"ruta": r, "texto": "def f(:\n"} for r in rutas])
    resultado = lanzador.revisar_sintaxis(str(tmp_path), rutas)
    assert resultado["salida"].endswith("... y 5 más.")


@pytest.mark.skipif(not EN_LINUX, reason="Los enlaces y chmod se prueban en Linux")
def test_borrar_no_sigue_enlaces(tmp_path):
    afuera = tmp_path / "afuera"
    afuera.mkdir(mode=0o755)
    carpeta = tmp_path / "sandbox-x"
    carpeta.mkdir()
    (carpeta / "enlace").symlink_to(afuera, target_is_directory=True)
    afuera.chmod(0o500)
    ejecutar._borrar(str(carpeta))
    assert not carpeta.exists()
    assert afuera.exists()
    assert (afuera.stat().st_mode & 0o777) == 0o500


def test_error_de_ajustes_no_muestra_los_secretos():
    """El error de arranque sale en el registro de Render: no debe traer las llaves."""
    llave = "sk-no-debe-salir-en-el-registro-123456"
    with pytest.raises(ValidationError) as error:
        Ajustes(**_produccion(sandbox_pruebas=True, llm_api_key=llave, jwt_secreto=llave))
    assert llave not in str(error.value)
    assert "SANDBOX_PRUEBAS" in str(error.value)
