"""Configuración de la IA y panel de costos (RF-19, RF-20, CU-08). Solo el administrador.

El administrador elige proveedor, modelo y dirección; la dirección no es libre (ConfigIA la
revisa: OpenAI y OpenRouter tienen una sola, Ollama solo en los equipos permitidos). La llave
NUNCA pasa por aquí: vive en la variable LLM_API_KEY y solo se dice si está puesta.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select

from app.api import seguridad
from app.api.entregas import LISTA_POR_DEFECTO, Desde, Limite
from app.api.seguridad import Actual, Db, limitador, ruta
from app.auditoria.registro import registrar
from app.config import ajustes
from app.esquemas import ConfigIA, ConfigIAVista, CostoEvaluacion, Costos, ProveedorIA, PruebaConexion
from app.ia import cliente
from app.ia.cliente import ErrorIA
from app.modelos import ConfigIAFila, PlanFortalecimientoFila
from app.modelos import Evaluacion as EvaluacionFila

router = APIRouter()

SIN_CONFIGURAR = "La IA no está configurada. Elige un proveedor y un modelo."


def obtener_probar():
    """La función que prueba la conexión. Las pruebas la cambian por una simulada."""
    return cliente.probar_conexion


def _vista(db: Db) -> ConfigIAVista:
    a = ajustes()
    fila = cliente.ultima_config_guardada(db)
    llave = bool(a.llm_api_key.get_secret_value())
    if fila is not None:
        return ConfigIAVista(
            proveedor=ProveedorIA(fila.proveedor),
            modelo=fila.modelo,
            base_url=fila.base_url,
            origen="base",
            llave_configurada=llave,
            precio_entrada_usd=(
                fila.precio_entrada_usd if fila.precio_entrada_usd is not None else a.llm_precio_entrada_usd
            ),
            precio_salida_usd=(
                fila.precio_salida_usd if fila.precio_salida_usd is not None else a.llm_precio_salida_usd
            ),
            fecha=fila.fecha,
        )
    try:
        proveedor = ProveedorIA(a.llm_provider)
    except ValueError:
        proveedor = ProveedorIA.OPENAI
    return ConfigIAVista(
        proveedor=proveedor,
        modelo=a.llm_model,
        base_url=a.llm_base_url,
        origen="entorno" if a.llm_model else "sin_configurar",
        llave_configurada=llave,
        precio_entrada_usd=a.llm_precio_entrada_usd,
        precio_salida_usd=a.llm_precio_salida_usd,
    )


@ruta(router, "GET", "/api/config-ia", response_model=ConfigIAVista)
def ver_config(db: Db) -> ConfigIAVista:
    return _vista(db)


@ruta(router, "PUT", "/api/config-ia", response_model=ConfigIAVista)
def cambiar_config(request: Request, datos: ConfigIA, actual: Actual, db: Db) -> ConfigIAVista:
    anterior = _vista(db)
    db.add(
        ConfigIAFila(
            proveedor=datos.proveedor.value,
            modelo=datos.modelo,
            base_url=datos.base_url.rstrip("/"),
            precio_entrada_usd=datos.precio_entrada_usd,
            precio_salida_usd=datos.precio_salida_usd,
            actualizado_por=actual.id,
        )
    )
    registrar(
        db,
        usuario_id=actual.id,
        accion="config_ia_cambiada",
        entidad="config_ia",
        detalle={
            # base_url también: es a dónde viaja el material de los estudiantes
            "anterior": {
                "proveedor": anterior.proveedor.value,
                "modelo": anterior.modelo,
                "base_url": anterior.base_url,
                "precio_entrada_usd": anterior.precio_entrada_usd,
                "precio_salida_usd": anterior.precio_salida_usd,
            },
            "nuevo": {
                "proveedor": datos.proveedor.value,
                "modelo": datos.modelo,
                "base_url": datos.base_url.rstrip("/"),
                "precio_entrada_usd": datos.precio_entrada_usd,
                "precio_salida_usd": datos.precio_salida_usd,
            },
        },
        ip=seguridad.ip_de(request),
    )
    db.commit()
    return _vista(db)


@ruta(router, "POST", "/api/config-ia/probar", response_model=PruebaConexion)
@limitador.limit("5/minute", key_func=seguridad.clave_de_usuario)
def probar_config(
    request: Request, actual: Actual, db: Db, probar: Annotated[object, Depends(obtener_probar)]
) -> PruebaConexion:
    try:
        config = cliente.configuracion(db)
    except ErrorIA:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, SIN_CONFIGURAR) from None
    try:
        uso = probar(config)
        resultado = PruebaConexion(
            ok=True, proveedor=config.proveedor, modelo=config.modelo, mensaje="La IA respondió bien."
        )
    except ErrorIA as error:  # el mensaje es nuestro, nunca la respuesta del proveedor
        uso = error.uso
        resultado = PruebaConexion(
            ok=False, proveedor=config.proveedor, modelo=config.modelo, mensaje=str(error)
        )
    # Los tokens de la prueba no son de ninguna evaluación: quedan en la auditoría (RF-20, LLM10)
    registrar(
        db,
        usuario_id=actual.id,
        accion="config_ia_probada",
        entidad="config_ia",
        detalle={
            "ok": resultado.ok,
            "modelo": config.modelo,
            "tokens_entrada": uso.entrada if uso else 0,
            "tokens_salida": uso.salida if uso else 0,
        },
        ip=seguridad.ip_de(request),
    )
    db.commit()
    return resultado


@ruta(router, "GET", "/api/costos", response_model=Costos)
def ver_costos(db: Db, desde: Desde = 0, limite: Limite = LISTA_POR_DEFECTO) -> Costos:
    entrada, salida, total = db.execute(
        select(
            func.coalesce(func.sum(EvaluacionFila.tokens_entrada), 0),
            func.coalesce(func.sum(EvaluacionFila.tokens_salida), 0),
            func.coalesce(func.sum(EvaluacionFila.costo_usd), 0.0),
        )
    ).one()
    # Los planes del informe también gastan tokens (D-22)
    p_entrada, p_salida, p_total = db.execute(
        select(
            func.coalesce(func.sum(PlanFortalecimientoFila.tokens_entrada), 0),
            func.coalesce(func.sum(PlanFortalecimientoFila.tokens_salida), 0),
            func.coalesce(func.sum(PlanFortalecimientoFila.costo_usd), 0.0),
        )
    ).one()
    filas = db.scalars(
        select(EvaluacionFila)
        .order_by(EvaluacionFila.fecha.desc(), EvaluacionFila.id.desc())
        .offset(desde)
        .limit(limite)
    )
    return Costos(
        tokens_entrada=int(entrada) + int(p_entrada),
        tokens_salida=int(salida) + int(p_salida),
        costo_usd=round(float(total) + float(p_total), 6),
        planes_tokens_entrada=int(p_entrada),
        planes_tokens_salida=int(p_salida),
        planes_costo_usd=round(float(p_total), 6),
        evaluaciones=[
            CostoEvaluacion(
                evaluacion_id=f.id,
                entrega_id=f.entrega_id,
                fecha=f.fecha,
                proveedor=ProveedorIA(f.proveedor),
                modelo=f.modelo,
                tokens_entrada=f.tokens_entrada,
                tokens_salida=f.tokens_salida,
                costo_usd=f.costo_usd,
            )
            for f in filas
        ],
    )
