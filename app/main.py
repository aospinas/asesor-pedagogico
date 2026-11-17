"""Punto de entrada de la API.

Cada ruta se registra con `app.api.seguridad.ruta`, que le pone los roles de la
tabla de `app/api/rutas.py`. Los módulos se agregan con /modulo.
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as ErrorHTTP

from app.api import auditoria, sesion, usuarios
from app.api.seguridad import limitador
from app.config import ajustes
from app.db import BaseNoDisponible
from app.mensajes import explicar

registro = logging.getLogger("asesor")

app = FastAPI(
    title="Asesor Pedagógico Inteligente",
    docs_url=None,  # OWASP A02: la documentación de la API no queda pública
    redoc_url=None,
    openapi_url=None,  # sin esto, /openapi.json publica todas las rutas sin sesión
)
app.state.limiter = limitador

METODOS_QUE_CAMBIAN_DATOS = {"POST", "PUT", "PATCH", "DELETE"}


def _viene_de_otro_sitio(request: Request) -> bool:
    """Una petición que cambia datos solo se acepta desde nuestra propia página (CSRF).

    Los navegadores mandan `Origin` en estas peticiones: debe estar en
    ORIGENES_PERMITIDOS. Si no viene, se mira `Sec-Fetch-Site`. Además la cookie
    es SameSite=Lax, que ya frena los envíos desde otros sitios.
    """
    if request.method not in METODOS_QUE_CAMBIAN_DATOS:
        return False
    origen = request.headers.get("origin")
    if origen is not None:
        return origen.rstrip("/") not in ajustes().origenes
    return request.headers.get("sec-fetch-site", "").lower() == "cross-site"


@app.middleware("http")
async def proteger(request: Request, call_next):
    if _viene_de_otro_sitio(request):
        respuesta = JSONResponse(
            {"detail": "Petición no permitida desde ese sitio."}, status.HTTP_403_FORBIDDEN
        )
    else:
        try:
            respuesta = await call_next(request)
        except Exception:
            # OWASP A10: el detalle queda en los registros del servidor, no en la respuesta.
            # Se atrapa aquí para que el error 500 también salga con las cabeceras de abajo.
            registro.exception("Error inesperado en %s %s", request.method, request.url.path)
            respuesta = JSONResponse(
                {"detail": "Ocurrió un error. Intenta de nuevo."}, status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    respuesta.headers["X-Frame-Options"] = "DENY"
    respuesta.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/api/"):
        respuesta.headers["Cache-Control"] = "no-store"
    if ajustes().en_produccion:
        respuesta.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return respuesta


app.add_middleware(
    CORSMiddleware,
    allow_origins=ajustes().origenes,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(RequestValidationError)
async def datos_no_validos(request: Request, error: RequestValidationError) -> JSONResponse:
    # Mensajes en español y sin devolver lo que escribió el usuario (app/mensajes.py).
    errores = [explicar(e, desde=1) for e in error.errors()]
    return JSONResponse({"detail": "Revisa los datos enviados.", "errores": errores}, 422)


@app.exception_handler(ErrorHTTP)
async def error_http(request: Request, error: ErrorHTTP) -> JSONResponse:
    # Los avisos que escribimos nosotros pasan tal cual; los automáticos salen en español.
    automaticos = {404: "Esa dirección no existe.", 405: "Esa acción no se puede hacer aquí."}
    detalle = error.detail
    if error.status_code in automaticos and detalle in {"Not Found", "Method Not Allowed"}:
        detalle = automaticos[error.status_code]
    return JSONResponse({"detail": detalle}, error.status_code, headers=error.headers)


@app.exception_handler(RateLimitExceeded)
async def demasiadas_peticiones(request: Request, error: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        {"detail": "Demasiados intentos. Espera un minuto y vuelve a intentar."},
        status.HTTP_429_TOO_MANY_REQUESTS,
    )


@app.exception_handler(BaseNoDisponible)
@app.exception_handler(OperationalError)
async def base_no_disponible(request: Request, error: Exception) -> JSONResponse:
    # La base está dormida, pausada o sin configurar: la app sigue arriba (RNF-10).
    registro.error(
        "Base de datos no disponible en %s %s: %s", request.method, request.url.path, type(error).__name__
    )
    return JSONResponse(
        {"detail": "La base de datos no está disponible. Intenta de nuevo en un minuto."},
        status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@app.get("/salud")
def salud() -> dict[str, str]:
    return {"estado": "ok"}


app.include_router(sesion.router)
app.include_router(usuarios.router)
app.include_router(auditoria.router)
