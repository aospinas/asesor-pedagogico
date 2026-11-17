"""Plan de fortalecimiento (RF-16): lo redacta la IA con datos YA calculados por el backend.

- La IA recibe solo los números y los temas (dentro de <datos>, como JSON con "<" escapado);
  nunca texto del estudiante. No calcula ni ve notas nuevas: el esquema de salida no tiene nota.
- Se guarda con la huella (SHA-256) de lo que recibió, el proveedor y el modelo: solo se vuelve
  a pedir si cambian los datos (OWASP LLM10). Un intento que falla también se guarda (sin plan)
  y no se reintenta antes de MINUTOS_REINTENTO: así un proveedor caído no se llama en cada visita.
- Solo `/api/informe` lo pide a la IA (`generar=True`); el mapa y el PDF usan el guardado.
- Los tokens y el costo quedan en la fila y suman en el panel de costos (RF-20).
- Si la IA no está configurada o falla, el informe sale igual, sin plan (RNF-10).
"""

import hashlib
import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.seguridad import ahora
from app.esquemas import ConfigIA, PlanFortalecimiento
from app.ia.cliente import ErrorIA, Uso
from app.informes.calculo import Datos
from app.modelos import PlanFortalecimientoFila

registro = logging.getLogger("asesor.informes")

VERSION_PROMPT = "plan_fortalecimiento_v1"
MAXIMO_TOKENS = 4_000
MINUTOS_REINTENTO = 30
CARPETA_PROMPTS = Path(__file__).resolve().parents[2] / "prompts"


@cache
def _prompt() -> str:
    return (CARPETA_PROMPTS / f"{VERSION_PROMPT}.md").read_text(encoding="utf-8")


def datos_para_la_ia(datos: Datos) -> dict:
    """Solo lo calculado: títulos (los escribe el docente), niveles y brechas."""
    return {
        "laboratorios": [
            {"titulo": r.titulo, "cohorte": r.cohorte, "nivel": r.nivel.value} for r in datos.laboratorios
        ],
        "temas": [
            {"categoria": t.categoria, "tema": t.tema, "nivel": t.nivel.value, "promedio": t.promedio}
            for t in datos.temas
        ],
        "brechas": datos.brechas,
    }


def huella(contenido: dict, config: ConfigIA) -> str:
    texto = json.dumps(
        {
            "datos": contenido,
            "proveedor": config.proveedor.value,
            "base_url": config.base_url,
            "modelo": config.modelo,
            "prompt": VERSION_PROMPT,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _hace_poco(fecha: datetime) -> bool:
    if fecha.tzinfo is None:  # SQLite la devuelve sin zona
        fecha = fecha.replace(tzinfo=UTC)
    return ahora() - fecha < timedelta(minutes=MINUTOS_REINTENTO)


def obtener(
    db: Session,
    estudiante_id: uuid.UUID,
    datos: Datos,
    pedir: Callable | None,
    config: ConfigIA | None,
    *,
    generar: bool = True,
) -> PlanFortalecimiento | None:
    """El plan guardado para estos datos, o uno nuevo si `generar`. None si no hay nada que
    planear, no hay IA, falló hace poco o no se pidió generarlo."""
    if not datos.temas or pedir is None or config is None:
        return None
    contenido = datos_para_la_ia(datos)
    marca = huella(contenido, config)
    guardado = db.scalar(
        select(PlanFortalecimientoFila).where(
            PlanFortalecimientoFila.estudiante_id == estudiante_id, PlanFortalecimientoFila.huella == marca
        )
    )
    if guardado is not None and guardado.plan:
        return PlanFortalecimiento.model_validate(guardado.plan)
    if not generar or (guardado is not None and _hace_poco(guardado.fecha)):
        return None
    db.commit()  # la llamada a la IA puede tardar: no se deja la transacción abierta

    texto = json.dumps(contenido, ensure_ascii=False, indent=1).replace("<", "\\u003c")
    plan: PlanFortalecimiento | None = None
    uso: Uso | None = None
    try:
        respuesta, uso = pedir(
            _prompt(),
            f"<datos>\n{texto}\n</datos>",
            PlanFortalecimiento,
            config=config,
            maximo_tokens=MAXIMO_TOKENS,
        )
        # Solo acciones sobre temas que existen (la IA no inventa temas)
        nombres = {t.tema for t in datos.temas}
        acciones = [a for a in respuesta.acciones if a.tema in nombres]
        if acciones:
            plan = PlanFortalecimiento(resumen=respuesta.resumen, acciones=acciones)
        else:
            registro.warning("El plan de la IA no nombró ningún tema de los datos")
    except ErrorIA as error:
        uso = error.uso
        registro.warning("No se pudo redactar el plan: %s", type(error).__name__)
    _guardar(db, estudiante_id, marca, plan, uso, config, guardado)
    return plan


def _guardar(db, estudiante_id, marca, plan, uso, config, guardado) -> None:
    """Guarda el plan, o el intento fallido (plan vacío) para no reintentar en cada visita."""
    from app.evaluador.motor import costo

    entrada, salida = (uso.entrada, uso.salida) if uso else (0, 0)
    fila = db.get(PlanFortalecimientoFila, guardado.id) if guardado is not None else None
    if fila is None:
        fila = PlanFortalecimientoFila(
            estudiante_id=estudiante_id, huella=marca, tokens_entrada=0, tokens_salida=0
        )
        db.add(fila)
    fila.plan = plan.model_dump(mode="json") if plan else {}
    fila.proveedor = config.proveedor.value
    fila.modelo = config.modelo
    fila.version_prompt = VERSION_PROMPT
    fila.tokens_entrada = (fila.tokens_entrada or 0) + entrada  # los reintentos también cuentan
    fila.tokens_salida = (fila.tokens_salida or 0) + salida
    fila.costo_usd = costo(fila.tokens_entrada, fila.tokens_salida, config)
    fila.fecha = ahora()
    try:
        db.commit()
    except IntegrityError:  # otra petición lo guardó al mismo tiempo: vale el que ya está
        db.rollback()
