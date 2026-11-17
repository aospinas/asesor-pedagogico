"""El proceso de evaluación con IA (CU-04, RF-09 a RF-13). Corre en segundo plano.

1. Si la entrega trae enlace de GitHub y no ZIP, se baja el código (app/evaluador/github.py).
2. Las imágenes sin descripción se describen con visión (se guarda para no pagar dos veces).
   Después el sandbox (app/sandbox) revisa el código: sintaxis, ruff y, si se puede, pytest.
3. Se arma el material (app/evaluador/material.py), con los resultados del sandbox como
   datos, y se pasa por el filtro de inyección.
4. Por cada criterio, la IA propone un nivel con evidencias. Si la respuesta no sirve (no es
   JSON válido, cambia el criterio o inventa un nivel) se reintenta hasta 3 veces; si sigue
   fallando, el criterio queda "Sin propuesta" y lo califica el docente.
5. Cada cita se busca en el material (RF-12).
6. La nota la calcula el backend con app/evaluador/nota.py, solo si todos los criterios
   tienen nivel (RF-13). La IA nunca la calcula ni la escribe.

Topes (OWASP LLM10): dos evaluaciones a la vez en un grupo de hilos propio (no ocupan los
hilos de las rutas), un máximo de evaluaciones en cola, tokens por evaluación (contando los
intentos que fallaron) y material por criterio.
"""

import hashlib
import json
import logging
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import timedelta
from functools import cache
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import almacen as almacenes
from app.almacen import Almacen, AlmacenNoDisponible
from app.api.seguridad import ahora
from app.archivos import ArchivoNoValido
from app.archivos import zip as lector_zip
from app.archivos.zip import ArchivoCodigo
from app.auditoria.registro import registrar
from app.config import ajustes
from app.esquemas import (
    ConfigIA,
    Criterio,
    DescripcionImagen,
    EstadoEvaluacion,
    ResultadoCriterio,
    RubricaEstructura,
    TipoEvidencia,
    VerificacionCodigo,
)
from app.evaluador import citas, imagenes, inyeccion, material, revision
from app.evaluador.nota import ErrorDeNota, calcular_nota
from app.ia.cliente import ErrorIA, Imagen, Uso
from app.modelos import (
    Entrega,
    Evaluacion,
    EvaluacionCriterio,
    Evidencia,
    RubricaVersion,
    VerificacionCodigoFila,
)

registro = logging.getLogger("asesor.evaluador")

VERSION_PROMPT = "evaluar_criterio_v2"  # la v2 explica las verificaciones del sandbox (D-20)
INTENTOS_POR_CRITERIO = 3
MAXIMO_TOKENS_EVALUACION = 300_000
MINUTOS_COLGADA = 30
EVALUACIONES_A_LA_VEZ = 2
MAXIMO_EN_COLA = 20  # entre todos los docentes: las que corren más las que esperan
MAXIMO_POR_DOCENTE = 5  # así un solo docente no llena la cola de todos
MINUTOS_MAXIMOS = 20  # plazo total de una evaluación, contado desde que toma el turno
CARPETA_PROMPTS = Path(__file__).resolve().parents[2] / "prompts"

AVISO_ERROR = "Ocurrió un error al evaluar. Califícala a mano o vuelve a lanzarla."
AVISO_COLGADA = "La evaluación se interrumpió (el servidor se reinició). Vuelve a lanzarla."
AVISO_TOKENS = (
    "Se llegó al tope de tokens o de tiempo de la evaluación: "
    "los criterios que faltaban quedaron sin propuesta."
)
AVISO_NOTA = "No se pudo calcular la nota con esta rúbrica. Califícala a mano."
AVISO_IMAGEN = "Una imagen no se pudo describir y no entró en la evaluación."
AVISO_ALMACEN = "No se pudo guardar el código bajado de GitHub; se evaluó sin él."
AVISO_SANDBOX = "No se pudo verificar el código en el sandbox; se evaluó sin esa verificación."
AVISO_SANDBOX_SIN_CORRER = "El sandbox no pudo revisar el código: mira el detalle en las verificaciones."
# El sandbox corre una entrega a la vez y solo espera 30 s su turno. Las dos evaluaciones que
# corren a la vez se turnan aquí con más paciencia, para no quedar con "sandbox ocupado".
MINUTOS_ESPERA_SANDBOX = 5
_TURNO_SANDBOX = threading.Lock()

# Grupo de hilos propio: si usara el de FastAPI, una cola larga dejaría sin hilos al login.
_EJECUTOR = ThreadPoolExecutor(max_workers=EVALUACIONES_A_LA_VEZ, thread_name_prefix="evaluador")
# Evaluaciones vivas en este proceso (corriendo o en cola), con el docente que la lanzó.
# recuperar_colgadas no las toca: solo da por perdidas las que quedaron de un proceso
# anterior (Render se reinició). _CORRIENDO: las que ya tomaron turno.
_EN_COLA: dict[uuid.UUID, uuid.UUID] = {}
_CORRIENDO: set[uuid.UUID] = set()
_CANDADO = threading.Lock()

PedirJson = Callable[..., tuple[BaseModel, Uso]]


class _YaCerrada(Exception):
    """Otro cerró la evaluación mientras corría: se deja como quedó."""


@dataclass(frozen=True)
class Contexto:
    """Lo que necesita una evaluación en segundo plano. Las pruebas cambian cada pieza."""

    fabrica: Callable[[], Session]
    pedir: PedirJson
    almacen: Almacen
    config: ConfigIA
    bajar_github: Callable[[str], bytes]
    # El sandbox (app.sandbox.verificar). None = no se verifica el código.
    verificar: Callable[[list[ArchivoCodigo]], list[VerificacionCodigo]] | None = None


@cache
def _prompt(nombre: str) -> str:
    return (CARPETA_PROMPTS / f"{nombre}.md").read_text(encoding="utf-8")


def costo(entrada: int, salida: int, config: ConfigIA | None = None) -> float:
    """Costo en USD con los precios del modelo elegido (config_ia) o, si no los tiene,
    los de las variables LLM_PRECIO_* (RF-20)."""
    a = ajustes()
    precio_entrada = a.llm_precio_entrada_usd
    precio_salida = a.llm_precio_salida_usd
    if config is not None and config.precio_entrada_usd is not None:
        precio_entrada = config.precio_entrada_usd
    if config is not None and config.precio_salida_usd is not None:
        precio_salida = config.precio_salida_usd
    return round((entrada * precio_entrada + salida * precio_salida) / 1_000_000, 6)


def _a_revision_manual(db: Session, evaluacion_id: uuid.UUID, aviso: str, motivo: str) -> bool:
    """Pasa la evaluación de "En proceso" a revisión manual y lo deja en la auditoría.
    Solo si sigue en proceso: nunca pisa una que ya terminó. Devuelve si la cambió."""
    cambio = db.execute(
        update(Evaluacion)
        .where(Evaluacion.id == evaluacion_id, Evaluacion.estado == EstadoEvaluacion.EN_PROCESO.value)
        .values(estado=EstadoEvaluacion.REVISION_MANUAL.value, aviso=aviso, actualizada=ahora())
    )
    if not cambio.rowcount:
        return False
    lanzada_por = db.scalar(select(Evaluacion.lanzada_por).where(Evaluacion.id == evaluacion_id))
    registrar(
        db,
        usuario_id=lanzada_por,
        accion="evaluacion_interrumpida",
        entidad="evaluacion",
        entidad_id=evaluacion_id,
        detalle={"motivo": motivo},
    )
    return True


def recuperar_colgadas(db: Session) -> None:
    """Una evaluación "En proceso" sin avances en 30 minutos que no está viva en este proceso se
    dio por perdida (Render se reinició): pasa a revisión manual para que no quede colgada.
    Las que esperan turno en la cola no se tocan, aunque lleven más de 30 minutos."""
    limite = ahora() - timedelta(minutes=MINUTOS_COLGADA)
    with _CANDADO:
        vivas = set(_EN_COLA)
    consulta = select(Evaluacion.id).where(
        Evaluacion.estado == EstadoEvaluacion.EN_PROCESO.value, Evaluacion.actualizada < limite
    )
    if vivas:
        consulta = consulta.where(Evaluacion.id.not_in(vivas))
    cambiadas = [i for i in db.scalars(consulta).all() if _a_revision_manual(db, i, AVISO_COLGADA, "colgada")]
    if cambiadas:
        db.commit()


def reservar(evaluacion_id: uuid.UUID, docente_id: uuid.UUID) -> str | None:
    """Aparta un lugar en la cola (OWASP LLM10). Revisar y apartar van en el mismo paso, con el
    candado: dos peticiones a la vez no pasan las dos. Devuelve None si hay lugar, o
    "cola" / "docente" según qué tope se alcanzó."""
    with _CANDADO:
        if len(_EN_COLA) >= MAXIMO_EN_COLA:
            return "cola"
        if sum(1 for d in _EN_COLA.values() if d == docente_id) >= MAXIMO_POR_DOCENTE:
            return "docente"
        _EN_COLA[evaluacion_id] = docente_id
    return None


def liberar(evaluacion_id: uuid.UUID) -> None:
    with _CANDADO:
        _EN_COLA.pop(evaluacion_id, None)
        _CORRIENDO.discard(evaluacion_id)


def _registrar_falla(evaluacion_id: uuid.UUID, error: BaseException) -> None:
    """Solo el tipo y la traza (sin el mensaje): el mensaje podría traer texto del estudiante."""
    registro.error(
        "Falló la evaluación %s (%s)\n%s",
        evaluacion_id,
        type(error).__name__,
        "".join(traceback.format_tb(error.__traceback__)),
    )


def encolar(evaluacion_id: uuid.UUID, contexto: Contexto) -> None:
    """Manda al grupo de hilos propio (dos corren a la vez) una evaluación ya reservada."""

    def trabajo() -> None:
        try:
            ejecutar(evaluacion_id, contexto)
        except Exception as error:  # p. ej. la base cayó al tomar el turno: que quede en el registro
            _registrar_falla(evaluacion_id, error)
        finally:
            liberar(evaluacion_id)

    try:
        _EJECUTOR.submit(trabajo)
    except RuntimeError as error:  # el grupo ya se apagó: no queda viva para siempre
        _registrar_falla(evaluacion_id, error)
        liberar(evaluacion_id)


def apagar(fabrica: Callable[[], Session] | None = None) -> None:
    """Al apagar el servidor (cada despliegue de Render): no se empiezan las que esperan turno
    y pasan de una vez a revisión manual, en vez de quedar "En proceso" 30 minutos."""
    _EJECUTOR.shutdown(wait=False, cancel_futures=True)
    with _CANDADO:
        pendientes = [i for i in _EN_COLA if i not in _CORRIENDO]
    if not pendientes:
        return
    try:
        if fabrica is None:
            from app.db import motor as motor_db

            def fabrica() -> Session:
                return Session(motor_db())

        with fabrica() as db:
            for evaluacion_id in pendientes:
                _a_revision_manual(db, evaluacion_id, AVISO_COLGADA, "apagado")
            db.commit()
    except Exception as error:  # al apagar no hay a quién avisarle: queda en el registro
        _registrar_falla(pendientes[0], error)


def ejecutar(evaluacion_id: uuid.UUID, contexto: Contexto) -> None:
    """Corre una evaluación. Nunca la deja "En proceso"."""
    with _CANDADO:
        _CORRIENDO.add(evaluacion_id)
    with contexto.fabrica() as db:
        # Al tomar el turno se marca el avance; si ya no está en proceso (la cerró
        # recuperar_colgadas o algo más), no se corre: así nunca hay dos sobre la misma entrega.
        tomada = db.execute(
            update(Evaluacion)
            .where(Evaluacion.id == evaluacion_id, Evaluacion.estado == EstadoEvaluacion.EN_PROCESO.value)
            .values(actualizada=ahora())
        )
        db.commit()
        if not tomada.rowcount:
            return
        try:
            _evaluar(db, evaluacion_id, contexto)
        except _YaCerrada:
            return
        except Exception as error:
            _registrar_falla(evaluacion_id, error)
            db.rollback()
            if _a_revision_manual(db, evaluacion_id, AVISO_ERROR, "error"):
                db.commit()


# ---------- Pasos ----------


def _bajar_github(db: Session, entrega: Entrega, contexto: Contexto) -> None:
    """Baja el repositorio y lo guarda como una evidencia más, con su huella (traza RNF-08)."""
    from app.evaluador import github

    contenido = contexto.bajar_github(entrega.enlace_github)
    extraido = lector_zip.leer_zip(contenido)
    usuario, repositorio = github.partes(entrega.enlace_github)
    evidencia_id = uuid.uuid4()
    ruta = almacenes.ruta_de(entrega.id, evidencia_id)
    contexto.almacen.guardar(ruta, contenido, "application/zip")
    db.add(
        Evidencia(
            id=evidencia_id,
            entrega_id=entrega.id,
            tipo=TipoEvidencia.CODIGO.value,
            nombre=f"github-{usuario}-{repositorio}.zip"[:120],
            sha256=hashlib.sha256(contenido).hexdigest(),
            tamano_bytes=len(contenido),
            tipo_mime="application/zip",
            ruta_storage=ruta,
            texto_extraido=extraido.como_json(),
            resumen=f"{len(extraido.archivos)} archivos de código (bajado de GitHub)",
        )
    )
    db.commit()


def _describir(evidencia: Evidencia, contexto: Contexto) -> Uso:
    contenido = contexto.almacen.leer(evidencia.ruta_storage)
    imagenes.revisar(contenido)
    resultado, uso = contexto.pedir(
        _prompt(imagenes.VERSION_PROMPT),
        "Describe la imagen adjunta.",
        DescripcionImagen,
        config=contexto.config,
        imagenes=[Imagen(imagenes.en_base64(contenido), evidencia.tipo_mime)],
    )
    evidencia.texto_extraido = {
        "descripcion": resultado.descripcion,
        "modelo": uso.modelo,
        "prompt_version": imagenes.VERSION_PROMPT,
    }
    return uso


def _archivos_de_codigo(evidencias: list[Evidencia], avisos: list[str]) -> list[ArchivoCodigo]:
    """El código de la entrega (ZIP o GitHub), ya leído al subir. Se arma ANTES de cerrar la
    transacción: texto_extraido es una columna diferida y leerla después abriría otra."""
    try:  # un texto_extraido mal formado tampoco tumba la evaluación (RNF-10)
        return [
            ArchivoCodigo(ruta=str(a["ruta"]), texto=str(a["texto"]))
            for e in evidencias
            if e.tipo == TipoEvidencia.CODIGO.value
            for a in (e.texto_extraido or {}).get("archivos", [])
        ]
    except (KeyError, TypeError, AttributeError) as error:
        registro.warning("Código de la entrega mal guardado: %s", type(error).__name__)
        avisos.append(AVISO_SANDBOX)
        return []


def _verificar_codigo(
    archivos: list[ArchivoCodigo], contexto: Contexto, gasto: "Gasto", avisos: list[str]
) -> list[VerificacionCodigo]:
    """Corre el sandbox sobre el código. El sandbox nunca lanza error (RNF-10); si algo falla
    igual, la evaluación sigue con aviso."""
    if contexto.verificar is None or not archivos:
        return []
    # La espera del turno no pasa del plazo de la evaluación
    espera = min(MINUTOS_ESPERA_SANDBOX * 60, gasto.vence - time.monotonic())
    if espera <= 0 or gasto.agotado or not _TURNO_SANDBOX.acquire(timeout=espera):
        avisos.append(AVISO_SANDBOX)
        return []
    try:
        resultado = contexto.verificar(archivos)
        # Se vuelve a validar: lo que se guarda y lo que ve la IA cumple el esquema
        verificaciones = [VerificacionCodigo.model_validate(v.model_dump()) for v in resultado]
    except Exception as error:
        registro.warning("Falló el sandbox: %s", type(error).__name__)
        avisos.append(AVISO_SANDBOX)
        return []
    finally:
        _TURNO_SANDBOX.release()
    # El sandbox de verdad nunca lanza error: si no pudo correr (sin Docker, ocupado...), lo
    # dice en una verificación sin código de salida. Entonces también va el aviso arriba.
    if verificaciones and all(v.codigo_salida is None for v in verificaciones):
        avisos.append(AVISO_SANDBOX_SIN_CORRER)
    return verificaciones


def _pedido_del_criterio(criterio: Criterio, entrega_material: material.Material) -> str:
    datos = {
        "id": criterio.id,
        "nombre": criterio.nombre,
        "competencia": criterio.competencia,
        "niveles": [{"id": n.id, "nombre": n.nombre, "descriptor": n.descriptor} for n in criterio.niveles],
    }
    criterio_json = json.dumps(datos, ensure_ascii=False, indent=1).replace("<", "\\u003c")
    return f"Criterio a evaluar:\n{criterio_json}\n\nMaterial del estudiante:\n{entrega_material.texto}"


@dataclass
class Gasto:
    """Tokens y tiempo de la evaluación, contando también los intentos que la IA respondió mal.
    El plazo total corta una evaluación que se alarga (p. ej. un proveedor que responde a
    gotas): se revisa antes de cada pedido a la IA."""

    entrada: int = 0
    salida: int = 0
    vence: float = field(default_factory=lambda: time.monotonic() + MINUTOS_MAXIMOS * 60)

    def sumar(self, uso: Uso | None) -> None:
        if uso is not None:
            self.entrada += uso.entrada
            self.salida += uso.salida

    @property
    def agotado(self) -> bool:
        return self.entrada + self.salida >= MAXIMO_TOKENS_EVALUACION or time.monotonic() > self.vence


def _proponer(
    criterio: Criterio, entrega_material: material.Material, contexto: Contexto, gasto: Gasto
) -> tuple[ResultadoCriterio | None, int]:
    """(resultado o None, intentos). Suma lo gastado en `gasto` y para si se llega al tope."""
    pedido = _pedido_del_criterio(criterio, entrega_material)
    niveles = {n.id for n in criterio.niveles}
    intentos = 0
    while intentos < INTENTOS_POR_CRITERIO and not gasto.agotado:
        intentos += 1
        try:
            resultado, uso = contexto.pedir(
                _prompt(VERSION_PROMPT), pedido, ResultadoCriterio, config=contexto.config
            )
        except ErrorIA as error:
            gasto.sumar(error.uso)  # si la IA alcanzó a responder, igual cobró
            registro.warning("Criterio %s, intento %s: %s", criterio.id, intentos, error)
            continue
        gasto.sumar(uso)
        if resultado.criterio_id != criterio.id or resultado.nivel_id not in niveles:
            registro.warning("Criterio %s, intento %s: la IA devolvió otro criterio o un nivel inventado",
                             criterio.id, intentos)  # fmt: skip
            continue
        return resultado, intentos
    return None, intentos


def _evaluar(db: Session, evaluacion_id: uuid.UUID, contexto: Contexto) -> None:
    evaluacion = db.get(Evaluacion, evaluacion_id)
    entrega = db.get(Entrega, evaluacion.entrega_id)
    version = db.get(RubricaVersion, evaluacion.rubrica_version_id)
    rubrica = RubricaEstructura.model_validate(version.estructura)
    avisos: list[str] = []
    gasto = Gasto()

    def evidencias() -> list[Evidencia]:
        return list(db.scalars(select(Evidencia).where(Evidencia.entrega_id == entrega.id)))

    def avance() -> None:
        # Si otro ya la cerró (al apagar, o otro servidor durante un despliegue), se para aquí:
        # no se gastan más tokens en una evaluación cerrada.
        sigue = db.execute(
            update(Evaluacion)
            .where(Evaluacion.id == evaluacion.id, Evaluacion.estado == EstadoEvaluacion.EN_PROCESO.value)
            .values(actualizada=ahora())
        )
        if not sigue.rowcount:
            db.rollback()
            raise _YaCerrada
        evaluacion.tokens_entrada, evaluacion.tokens_salida = gasto.entrada, gasto.salida
        evaluacion.costo_usd = costo(gasto.entrada, gasto.salida, contexto.config)
        evaluacion.actualizada = ahora()
        db.commit()

    # 1. Código de GitHub, si no hay ZIP
    if entrega.enlace_github and not any(e.tipo == TipoEvidencia.CODIGO.value for e in evidencias()):
        try:
            _bajar_github(db, entrega, contexto)
        except ArchivoNoValido as error:
            db.rollback()
            avisos.append(str(error))
        except AlmacenNoDisponible:
            db.rollback()
            avisos.append(AVISO_ALMACEN)
        avance()

    # 2. Imágenes sin describir
    for evidencia in evidencias():
        if evidencia.tipo != TipoEvidencia.IMAGEN.value or (evidencia.texto_extraido or {}).get(
            "descripcion"
        ):
            continue
        if gasto.agotado:
            avisos.append(AVISO_IMAGEN)
            continue
        try:
            gasto.sumar(_describir(evidencia, contexto))
            db.commit()
        except (ArchivoNoValido, ErrorIA, FileNotFoundError, AlmacenNoDisponible) as error:
            db.rollback()
            if isinstance(error, ErrorIA):
                gasto.sumar(error.uso)
            registro.warning("No se describió la imagen %s: %s", evidencia.id, type(error).__name__)
            avisos.append(AVISO_IMAGEN)
        avance()

    # 2b. Verificación del código en el sandbox (RF-10). Nada del código corre aquí.
    # Se cierra la transacción antes: la espera y el sandbox pueden tomar minutos.
    archivos = _archivos_de_codigo(evidencias(), avisos) if contexto.verificar else []
    db.commit()
    verificaciones = _verificar_codigo(archivos, contexto, gasto, avisos)
    for orden, v in enumerate(verificaciones):
        db.add(VerificacionCodigoFila(evaluacion_id=evaluacion.id, orden=orden, **v.model_dump(mode="json")))
    avance()

    # 3. Material y filtro de inyección
    entrega_material = material.armar(evidencias(), verificaciones)
    reglas = inyeccion.detectar(entrega_material.texto_plano)
    evaluacion.alerta_inyeccion = bool(reglas)
    evaluacion.reglas_inyeccion = reglas
    if entrega_material.recortado:
        avisos.append("Parte del material no cupo y la IA no lo vio completo.")
    avance()

    # 4 y 5. Un criterio a la vez, con sus citas verificadas
    niveles: dict[str, str | None] = {}
    filas: list[EvaluacionCriterio] = []
    for orden, criterio in enumerate(rubrica.criterios):
        fila = EvaluacionCriterio(evaluacion_id=evaluacion.id, criterio_id=criterio.id, orden=orden)
        resultado, fila.intentos = _proponer(criterio, entrega_material, contexto, gasto)
        if resultado is None and gasto.agotado and AVISO_TOKENS not in avisos:
            avisos.append(AVISO_TOKENS)
        if resultado is not None:
            fila.nivel_ia = resultado.nivel_id
            fila.justificacion = resultado.justificacion
            fila.evidencias = [
                {
                    **ev.model_dump(),
                    "encontrada": citas.cita_encontrada(
                        entrega_material.documentos, ev.archivo, ev.ubicacion, ev.fragmento
                    ),
                }
                for ev in resultado.evidencias
            ]
            fila.fortalezas = resultado.fortalezas
            fila.debilidades = resultado.debilidades
            fila.recomendaciones = resultado.recomendaciones
        niveles[criterio.id] = fila.nivel_ia
        db.add(fila)
        filas.append(fila)
        avance()  # el docente ve el avance criterio por criterio

    # 6. Nota calculada por el backend, solo si todos los criterios tienen nivel.
    # "En revisión" siempre trae nota; si no la hay, va a revisión manual.
    estado, nota = EstadoEvaluacion.REVISION_MANUAL.value, None
    if all(niveles.values()):
        try:
            nota = calcular_nota(rubrica, niveles)  # type: ignore[arg-type]
            estado = EstadoEvaluacion.EN_REVISION.value
        except ErrorDeNota:
            avisos.append(AVISO_NOTA)
    # Se cierra solo si sigue "En proceso": si otro servidor ya la cerró (p. ej. durante un
    # despliegue conviven dos), no se pisa.
    cerrada = db.execute(
        update(Evaluacion)
        .where(Evaluacion.id == evaluacion.id, Evaluacion.estado == EstadoEvaluacion.EN_PROCESO.value)
        .values(
            estado=estado,
            # Para ordenar la bandeja del docente (D-21)
            prioridad=len(revision.motivos(evaluacion.alerta_inyeccion, filas, terminada=True)),
            nota_preliminar=nota,
            aviso=" ".join(dict.fromkeys(avisos))[:300] or None,
            actualizada=ahora(),
        )
    )
    if not cerrada.rowcount:
        db.rollback()
        return
    registrar(
        db,
        usuario_id=evaluacion.lanzada_por,
        accion="evaluacion_terminada",
        entidad="evaluacion",
        entidad_id=evaluacion.id,
        detalle={
            "estado": estado,
            "nota_preliminar": nota,
            "sin_propuesta": sum(1 for n in niveles.values() if n is None),
            "verificaciones": len(verificaciones),
            "alerta_inyeccion": evaluacion.alerta_inyeccion,
            "tokens_entrada": gasto.entrada,
            "tokens_salida": gasto.salida,
        },
    )
    db.commit()
