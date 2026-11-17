"""Sandbox: verificación del código de una entrega (RF-10, RNF-03, SRS sección 10, D-18).

Uso: `verificar(archivos) -> list[VerificacionCodigo]`, con los archivos que sacó el lector
de ZIP o de GitHub. Nunca lanza error: si el sandbox no puede correr, lo dice en una
verificación (RNF-10). Lista vacía = la entrega no trae código Python. Puede tardar más de
un minuto: el evaluador la llama desde su tarea en segundo plano, nunca dentro de una ruta.

Nada del código del estudiante corre en el proceso web: la sintaxis, ruff y pytest corren
en el lanzador, dentro de un contenedor (docker) o de un proceso aparte (proceso).

Ojo (LLM01): TODAS las salidas traen texto del estudiante (nombres de archivo, nombres que
repite ruff, lo que imprimen sus pruebas). Para la IA son datos, nunca instrucciones.
"""

import json
import logging
import os
import re
import secrets
import sys
import threading
import time
from dataclasses import dataclass
from typing import Literal

from pydantic import Field, ValidationError

from app.archivos.zip import ArchivoCodigo
from app.config import SECRETOS_DEL_ENTORNO, ajustes
from app.esquemas import Estricto, TipoVerificacion, VerificacionCodigo
from app.sandbox import ejecutar
from app.sandbox.ejecutar import Corrida, SandboxNoDisponible
from app.sandbox.lanzador import MARCA, es_prueba

MAXIMO_SALIDA = 20000  # tope de VerificacionCodigo.salida
MAXIMO_ENTRADA = 8 * 1024 * 1024  # texto total que se le pasa al sandbox (el tmpfs es de 10 MB)
ESPERA_TURNO_SEG = 30
COMANDO_PRUEBAS = "pytest -q -p no:cacheprovider"
RECORTADA = "\n... (salida recortada)"
# Controles que no son salto de línea ni tabulación (incluye ESC de los colores de terminal,
# los C1 y los que invierten el sentido del texto).
CONTROLES = re.compile(
    r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u061c\u200e\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069]"
)

OCUPADO = "El sandbox está ocupado con otra entrega. Vuelve a lanzar la evaluación en unos minutos."
SIN_TIEMPO = "Se acabó el tiempo del sandbox antes de llegar a este paso."
AGOTADO = "Tiempo agotado: el sandbox cortó la ejecución."
FALLO = "El sandbox no pudo terminar la revisión."
GRANDE = "La entrega es demasiado grande para el sandbox."
PRUEBAS_APAGADAS = (
    "La entrega trae pruebas, pero en este servidor no se ejecutan. "
    "Se revisaron sin ejecutar: la sintaxis y el estilo."
)

registro = logging.getLogger("asesor.sandbox")

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


class _Paso(Estricto):
    """Un paso de "revisar" tal como lo devuelve el lanzador. Se valida con tipos estrictos:
    una salida rara se toma como falla, nunca tumba la evaluación."""

    comando: str = Field(max_length=500)
    codigo_salida: int | None
    salida: str
    duracion_ms: int = Field(ge=0)


class _Revision(Estricto):
    sintaxis: _Paso
    estilo: _Paso
    seguridad: _Paso


def preparar_proceso_web() -> None:
    """Se llama al arrancar la app en modo proceso (Render), antes de cualquier proceso hijo.

    1. Lee los ajustes (quedan guardados) y saca los secretos de os.environ: así ningún
       proceso hijo los hereda (lector de PDF, su resource_tracker, el sandbox).
    2. Marca el proceso web como no volcable: otro proceso del mismo usuario no puede leer
       /proc/<pid>/environ, que conserva el entorno con el que arrancó.
    """
    ajustes()
    for nombre in list(os.environ):
        if nombre.upper() in SECRETOS_DEL_ENTORNO:
            del os.environ[nombre]
    if sys.platform.startswith("linux"):
        ejecutar.proteger_proceso_web()


def limpiar_salida(salida: str | bytes, recortada: bool = False) -> str:
    """Texto guardable y mostrable: sin NUL (PostgreSQL no los acepta), sin caracteres de
    control (colores de terminal, texto invertido) y con tope de tamaño."""
    if isinstance(salida, bytes):
        salida = salida.decode("utf-8", errors="replace")
    salida = CONTROLES.sub("", salida.replace("\r\n", "\n"))
    if len(salida) > MAXIMO_SALIDA - len(RECORTADA):
        salida = salida[: MAXIMO_SALIDA - len(RECORTADA)]
        recortada = True
    return salida + RECORTADA if recortada else salida


def _aviso(
    tipo: TipoVerificacion, comando: str, mensaje: str, *, agotado: bool = False, duracion_ms: int = 0
) -> VerificacionCodigo:
    return VerificacionCodigo(
        tipo=tipo,
        comando=comando,
        codigo_salida=None,
        salida=mensaje,
        duracion_ms=duracion_ms,
        tiempo_agotado=agotado,
    )


def verificar(archivos: list[ArchivoCodigo], config: ConfigSandbox | None = None) -> list[VerificacionCodigo]:
    """Sintaxis, ruff (estilo y seguridad) y, si la entrega trae pruebas, pytest."""
    try:
        config = config or ConfigSandbox.desde_ajustes()
        if not any(a.ruta.endswith(".py") for a in archivos):
            return []
        lista = [{"ruta": a.ruta, "texto": a.texto} for a in archivos]
        if sum(len(a["texto"].encode("utf-8")) for a in lista) > MAXIMO_ENTRADA:
            return [_aviso(TipoVerificacion.SINTAXIS, "ast.parse", GRANDE)]
        trae_pruebas = any(es_prueba(a.ruta) for a in archivos)
    except Exception as error:  # RNF-10: nada de aquí tumba la evaluación
        registro.warning("Sandbox: error inesperado al preparar (%s)", type(error).__name__)
        return [_aviso(TipoVerificacion.SINTAXIS, "ast.parse", FALLO)]

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
    except Exception as error:  # RNF-10. Solo el tipo al registro: nada del código del estudiante.
        registro.warning("Sandbox: error inesperado (%s)", type(error).__name__)
        return [_aviso(TipoVerificacion.SINTAXIS, "ast.parse", FALLO)]
    finally:
        _TURNO.release()


def _correr(
    tarea: str, lista: list[dict], config: ConfigSandbox, limite: float, marca: str = ""
) -> Corrida | None:
    restante = limite - time.monotonic()
    if restante <= 0:
        return None
    if config.modo == "docker":
        return ejecutar.correr_docker(tarea, lista, restante, config.imagen, config.memoria_mb, marca=marca)
    return ejecutar.correr_proceso(tarea, lista, restante, config.memoria_mb, marca=marca)


def _leer_revision(texto: str, marca: str) -> _Revision | None:
    """La línea del resultado: la que empieza con la marca de ESTA corrida. Se corta solo
    en "\n" (splitlines también corta en U+2028 y otros, que la entrega puede meter)."""
    for linea in reversed(texto.split("\n")):
        if linea.startswith(marca):
            try:
                return _Revision.model_validate(json.loads(linea[len(marca) :]))
            except (ValueError, ValidationError):  # JSON roto o con tipos que no son
                return None
    return None


def _revisar(lista: list[dict], config: ConfigSandbox, limite: float) -> list[VerificacionCodigo]:
    codigo = secrets.token_hex(16)
    corrida = _correr("revisar", lista, config, limite, codigo)
    if corrida is None:
        return [_aviso(TipoVerificacion.SINTAXIS, "ast.parse y ruff", SIN_TIEMPO, agotado=True)]
    if corrida.tiempo_agotado:
        return [
            _aviso(
                TipoVerificacion.SINTAXIS,
                "ast.parse y ruff",
                AGOTADO,
                agotado=True,
                duracion_ms=corrida.duracion_ms,
            )
        ]
    texto = corrida.salida.decode("utf-8", errors="replace")
    # Salida recortada: la línea del resultado pudo quedar afuera; no se adivina.
    revision = None if corrida.recortada else _leer_revision(texto, MARCA + codigo)
    if revision is None:
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
        (revision.sintaxis, TipoVerificacion.SINTAXIS),
        (revision.estilo, TipoVerificacion.ESTATICO),
        (revision.seguridad, TipoVerificacion.ESTATICO),
    )
    return [
        VerificacionCodigo(
            tipo=tipo,
            comando=paso.comando,
            codigo_salida=paso.codigo_salida,
            salida=limpiar_salida(paso.salida),
            duracion_ms=paso.duracion_ms,
            tiempo_agotado=False,
        )
        for paso, tipo in pasos
    ]


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
