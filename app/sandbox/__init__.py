"""Sandbox: verificación del código de una entrega (RF-10, RNF-03, SRS sección 10).

Uso: `verificar(archivos) -> list[VerificacionCodigo]`, con los archivos que sacó el lector
de ZIP o de GitHub. Nunca lanza error: si el sandbox no puede correr, lo dice en una
verificación (RNF-10). Lista vacía = la entrega no trae código Python.

Nada del código del estudiante corre en el proceso web: la sintaxis, ruff y pytest corren
en el lanzador, dentro de un contenedor (docker) o de un proceso aparte (proceso).
"""

import json
import threading
import time
from dataclasses import dataclass
from typing import Literal

from app.archivos.zip import ArchivoCodigo
from app.config import ajustes
from app.esquemas import TipoVerificacion, VerificacionCodigo
from app.sandbox import ejecutar
from app.sandbox.ejecutar import Corrida, SandboxNoDisponible
from app.sandbox.lanzador import MARCA, es_prueba

MAXIMO_SALIDA = 20000  # tope de VerificacionCodigo.salida
MAXIMO_ENTRADA = 8 * 1024 * 1024  # texto total que se le pasa al sandbox (el tmpfs es de 10 MB)
ESPERA_TURNO_SEG = 120
COMANDO_PRUEBAS = "pytest -q -p no:cacheprovider"
RECORTADA = "\n... (salida recortada)"

OCUPADO = "El sandbox está ocupado con otra entrega. Vuelve a lanzar la evaluación en unos minutos."
SIN_TIEMPO = "Se acabó el tiempo del sandbox antes de llegar a este paso."
AGOTADO = "Tiempo agotado: el sandbox cortó la ejecución."
FALLO = "El sandbox no pudo terminar la revisión."
GRANDE = "La entrega es demasiado grande para el sandbox."
PRUEBAS_APAGADAS = (
    "La entrega trae pruebas, pero en este servidor no se ejecutan (SANDBOX_PRUEBAS=no). "
    "Se revisaron sin ejecutar: sintaxis y ruff."
)

# Uno a la vez: Render tiene 512 MB y cada corrida puede usar 256 MB.
_TURNO = threading.BoundedSemaphore(1)


@dataclass(frozen=True)
class ConfigSandbox:
    modo: Literal["docker", "proceso"]
    tiempo_seg: int
    memoria_mb: int
    imagen: str
    pruebas: bool

    @classmethod
    def desde_ajustes(cls) -> "ConfigSandbox":
        a = ajustes()
        return cls(
            modo=a.sandbox_mode,
            tiempo_seg=a.sandbox_tiempo_seg,
            memoria_mb=a.sandbox_memoria_mb,
            imagen=a.sandbox_imagen,
            pruebas=a.sandbox_pruebas,
        )


def limpiar_salida(salida: str | bytes, recortada: bool = False) -> str:
    """Texto guardable: sin NUL (PostgreSQL no los acepta) y con tope de tamaño."""
    if isinstance(salida, bytes):
        salida = salida.decode("utf-8", errors="replace")
    salida = salida.replace("\x00", "")
    if len(salida) > MAXIMO_SALIDA - len(RECORTADA):
        salida = salida[: MAXIMO_SALIDA - len(RECORTADA)]
        recortada = True
    return salida + RECORTADA if recortada else salida


def _aviso(
    tipo: TipoVerificacion, comando: str, mensaje: str, *, agotado: bool = False
) -> VerificacionCodigo:
    return VerificacionCodigo(
        tipo=tipo, comando=comando, codigo_salida=None, salida=mensaje, duracion_ms=0, tiempo_agotado=agotado
    )


def verificar(archivos: list[ArchivoCodigo], config: ConfigSandbox | None = None) -> list[VerificacionCodigo]:
    """Sintaxis, ruff (estilo y seguridad) y, si la entrega trae pruebas, pytest."""
    config = config or ConfigSandbox.desde_ajustes()
    if not any(a.ruta.endswith(".py") for a in archivos):
        return []
    lista = [{"ruta": a.ruta, "texto": a.texto} for a in archivos]
    if sum(len(a["texto"].encode("utf-8")) for a in lista) > MAXIMO_ENTRADA:
        return [_aviso(TipoVerificacion.SINTAXIS, "ast.parse", GRANDE)]
    trae_pruebas = any(es_prueba(a.ruta) for a in archivos)

    if not _TURNO.acquire(timeout=ESPERA_TURNO_SEG):
        return [_aviso(TipoVerificacion.SINTAXIS, "ast.parse", OCUPADO)]
    try:
        if config.modo == "docker":
            ejecutar.revisar_docker(config.imagen)
        limite = time.monotonic() + config.tiempo_seg
        verificaciones = _revisar(lista, config, limite)
        if trae_pruebas:
            verificaciones.append(_pruebas(lista, config, limite))
        return verificaciones
    except SandboxNoDisponible as error:
        return [_aviso(TipoVerificacion.SINTAXIS, "ast.parse", str(error))]
    finally:
        _TURNO.release()


def _correr(tarea: str, lista: list[dict], config: ConfigSandbox, limite: float) -> Corrida | None:
    restante = limite - time.monotonic()
    if restante <= 0:
        return None
    if config.modo == "docker":
        return ejecutar.correr_docker(tarea, lista, restante, config.imagen, config.memoria_mb)
    return ejecutar.correr_proceso(tarea, lista, restante, config.memoria_mb)


def _revisar(lista: list[dict], config: ConfigSandbox, limite: float) -> list[VerificacionCodigo]:
    corrida = _correr("revisar", lista, config, limite)
    if corrida is None:
        return [_aviso(TipoVerificacion.SINTAXIS, "ast.parse", SIN_TIEMPO, agotado=True)]
    if corrida.tiempo_agotado:
        return [
            VerificacionCodigo(
                tipo=TipoVerificacion.SINTAXIS,
                comando="ast.parse y ruff",
                codigo_salida=None,
                salida=AGOTADO,
                duracion_ms=corrida.duracion_ms,
                tiempo_agotado=True,
            )
        ]
    texto = corrida.salida.decode("utf-8", errors="replace")
    resultado = None
    for linea in reversed(texto.splitlines()):
        if linea.startswith(MARCA):
            try:
                resultado = json.loads(linea[len(MARCA) :])
            except json.JSONDecodeError:
                resultado = None
            break
    if not isinstance(resultado, dict):
        return [
            VerificacionCodigo(
                tipo=TipoVerificacion.SINTAXIS,
                comando="ast.parse y ruff",
                codigo_salida=corrida.codigo_salida,
                salida=limpiar_salida(f"{FALLO}\n{texto[-4000:]}"),
                duracion_ms=corrida.duracion_ms,
                tiempo_agotado=False,
            )
        ]
    pasos = (
        ("sintaxis", TipoVerificacion.SINTAXIS),
        ("estilo", TipoVerificacion.ESTATICO),
        ("seguridad", TipoVerificacion.ESTATICO),
    )
    verificaciones = []
    for clave, tipo in pasos:
        paso = resultado.get(clave) or {}
        verificaciones.append(
            VerificacionCodigo(
                tipo=tipo,
                comando=str(paso.get("comando", clave))[:500],
                codigo_salida=paso.get("codigo_salida"),
                salida=limpiar_salida(str(paso.get("salida", ""))),
                duracion_ms=max(int(paso.get("duracion_ms", 0)), 0),
                tiempo_agotado=False,
            )
        )
    return verificaciones


def _pruebas(lista: list[dict], config: ConfigSandbox, limite: float) -> VerificacionCodigo:
    if not config.pruebas:
        return _aviso(TipoVerificacion.PRUEBAS, COMANDO_PRUEBAS, PRUEBAS_APAGADAS)
    corrida = _correr("pruebas", lista, config, limite)
    if corrida is None:
        return _aviso(TipoVerificacion.PRUEBAS, COMANDO_PRUEBAS, SIN_TIEMPO, agotado=True)
    salida = limpiar_salida(corrida.salida, corrida.recortada)
    if corrida.tiempo_agotado:
        salida = limpiar_salida(f"{AGOTADO}\n{salida}")
    return VerificacionCodigo(
        tipo=TipoVerificacion.PRUEBAS,
        comando=COMANDO_PRUEBAS,
        codigo_salida=corrida.codigo_salida,
        salida=salida,
        duracion_ms=corrida.duracion_ms,
        tiempo_agotado=corrida.tiempo_agotado,
    )
