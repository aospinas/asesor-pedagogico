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

import pytest
from pydantic import ValidationError

import app.sandbox as sandbox
from app.archivos.zip import ArchivoCodigo
from app.config import Ajustes
from app.esquemas import TipoVerificacion
from app.sandbox import ConfigSandbox, ejecutar, lanzador, limpiar_salida, verificar
from app.sandbox.ejecutar import Corrida, SandboxNoDisponible

IMAGEN = os.environ.get("SANDBOX_IMAGEN_PRUEBAS", "asesor-sandbox:1")
EN_LINUX = sys.platform.startswith("linux")
SECRETO = "sk-secreto-falso-de-prueba-123"


def _docker_listo() -> bool:
    try:
        ejecutar.revisar_docker(IMAGEN)
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
    comando = ejecutar.comando_docker("asesor-sandbox-x", "asesor-sandbox:1", 256, "print(1)")
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
    assert comando[comando.index("asesor-sandbox:1") :][:5] == [
        "asesor-sandbox:1",
        "python",
        "-I",
        "-B",
        "-c",
    ]


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
    def gancho(self, tmp_path):
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
"""
NOMBRES_HOSTILES = (
    "test_red_socket",
    "test_red_descarga",
    "test_entorno_sin_secretos",
    "test_no_lanza_procesos",
    "test_no_escribe_fuera_de_su_carpeta",
    "test_escribe_en_tmp_path",
    "test_no_lee_procesos_ajenos",
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


def test_matriz_red_entorno_y_procesos_todas_pasan(hostil):
    """Matriz C3: red bloqueada y entorno vacío (las pruebas del estudiante lo comprueban)."""
    assert hostil.codigo_salida == 0, hostil.salida
    assert f"{len(NOMBRES_HOSTILES)} passed" in hostil.salida
    assert SECRETO not in hostil.salida


@sin_modos
@pytest.mark.parametrize("modo", MODOS)
def test_matriz_ciclo_infinito_se_corta(modo):
    archivos = _archivos(**{"test_ciclo.py": "def test_ciclo():\n    while True:\n        pass\n"})
    inicio = time.monotonic()
    resultado = _pruebas(verificar(archivos, _config(modo, tiempo_seg=15)))
    assert resultado.tiempo_agotado
    assert resultado.codigo_salida is None
    assert resultado.salida.startswith(sandbox.AGOTADO)
    assert time.monotonic() - inicio < 40
    if modo == "docker":
        vivos = subprocess.run(
            ["docker", "ps", "-q", "--filter", "name=asesor-sandbox-"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
        assert not vivos.stdout.strip()


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
