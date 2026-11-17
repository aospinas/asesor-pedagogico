"""Punto de entrada de la API.

Cada ruta se registra con `app.api.seguridad.ruta`, que le pone los roles de la
tabla de `app/api/rutas.py`. Los módulos se agregan con /modulo.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as ErrorHTTP

from app.almacen import AlmacenNoDisponible
from app.api import (
    auditoria,
    config_ia,
    entregas,
    evaluaciones,
    informe,
    laboratorios,
    mapa,
    portafolio,
    proyecto,
    revision,
    rubricas,
    sesion,
    usuarios,
)
from app.api.seguridad import limitador, tiene_sesion_firmada
from app.archivos.pdf import ServidorOcupado
from app.config import ajustes
from app.db import BaseNoDisponible
from app.evaluador import motor as motor_evaluador
from app.mensajes import explicar
from app.sandbox import preparar_proceso_web

registro = logging.getLogger("asesor")


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    yield
    # Al apagar (cada despliegue): las evaluaciones que esperan turno no se empiezan y pasan
    # a revisión manual de una vez, en vez de quedar "En proceso" 30 minutos (D-19).
    motor_evaluador.apagar()


app = FastAPI(
    lifespan=ciclo_de_vida,
    title="Asesor Pedagógico Inteligente",
    docs_url=None,  # OWASP A02: la documentación de la API no queda pública
    redoc_url=None,
    openapi_url=None,  # sin esto, /openapi.json publica todas las rutas sin sesión
)
app.state.limiter = limitador

# Modo proceso (Render): antes de crear cualquier proceso hijo, los secretos salen de
# os.environ y el proceso web queda protegido contra lecturas de /proc (D-18).
if ajustes().sandbox_mode == "proceso":
    preparar_proceso_web()

METODOS_QUE_CAMBIAN_DATOS = {"POST", "PUT", "PATCH", "DELETE"}
# El archivo más grande que se acepta (la rúbrica, 5 MB) más el sobre del formulario.
MAXIMO_CUERPO_BYTES = 6 * 1024 * 1024
# Las rutas que reciben más, cada una con su decisión (D-17).
MAXIMO_CUERPO_POR_RUTA = {("POST", "/api/entregas"): 30 * 1024 * 1024}


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


def _cuerpo_no_permitido(request: Request) -> JSONResponse | None:
    """Frena las peticiones demasiado grandes ANTES de leerlas (OWASP A08).

    FastAPI guarda en disco los archivos subidos antes de revisar la sesión: sin este
    tope, cualquiera podría llenar el disco del servidor sin haber iniciado sesión.
    """
    if request.method not in METODOS_QUE_CAMBIAN_DATOS:
        return None
    if "transfer-encoding" in request.headers:  # sin tamaño declarado no se sabe cuánto llega
        return JSONResponse({"detail": "Falta el tamaño de la petición."}, status.HTTP_411_LENGTH_REQUIRED)
    maximo = MAXIMO_CUERPO_POR_RUTA.get((request.method, request.url.path), MAXIMO_CUERPO_BYTES)
    try:
        tamano = int(request.headers.get("content-length", "0"))
    except ValueError:
        tamano = maximo + 1
    if tamano > maximo:
        return JSONResponse(
            {"detail": f"La petición pesa más de {maximo // (1024 * 1024)} MB."},
            status.HTTP_413_CONTENT_TOO_LARGE,
        )
    if tamano > MAXIMO_CUERPO_BYTES and not tiene_sesion_firmada(request):
        # Más de 6 MB solo para quien ya inició sesión: sin cuenta no se gasta disco ni red.
        return JSONResponse({"detail": "Inicia sesión para continuar."}, status.HTTP_401_UNAUTHORIZED)
    return None


@app.middleware("http")
async def proteger(request: Request, call_next):
    rechazo = _cuerpo_no_permitido(request)
    if _viene_de_otro_sitio(request):
        respuesta = JSONResponse(
            {"detail": "Petición no permitida desde ese sitio."}, status.HTTP_403_FORBIDDEN
        )
    elif rechazo is not None:
        respuesta = rechazo
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


@app.exception_handler(ServidorOcupado)
async def servidor_ocupado(request: Request, error: ServidorOcupado) -> JSONResponse:
    # Otro PDF se está leyendo y no hubo turno a tiempo (rúbricas o entregas): aviso, no 500.
    return JSONResponse(
        {"detail": "Hay muchos archivos leyéndose en este momento. Intenta de nuevo en un minuto."},
        status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@app.exception_handler(AlmacenNoDisponible)
async def almacen_no_disponible(request: Request, error: AlmacenNoDisponible) -> JSONResponse:
    # Supabase Storage sin configurar o sin responder: la app sigue arriba. El detalle va al registro.
    registro.error("Almacén no disponible en %s %s: %s", request.method, request.url.path, error)
    return JSONResponse(
        {"detail": "El almacenamiento de archivos no está disponible. Intenta de nuevo en un rato."},
        status.HTTP_503_SERVICE_UNAVAILABLE,
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
app.include_router(laboratorios.router)
app.include_router(rubricas.router)
app.include_router(entregas.router)
app.include_router(portafolio.router)
app.include_router(evaluaciones.router)
app.include_router(revision.router)
app.include_router(informe.router)
app.include_router(mapa.router)
app.include_router(proyecto.router)
app.include_router(config_ia.router)


def _servir_interfaz() -> None:
    """Si existe el build del frontend, la misma app lo sirve. Las rutas /api quedan primero."""
    from pathlib import Path

    from starlette.exceptions import HTTPException as ErrorRuta
    from starlette.staticfiles import StaticFiles

    carpeta = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    if not carpeta.is_dir():
        return

    paginas = {"", "proyecto", "bitacora", "bandeja", "revision", "informe", "mapa", "publicada"}

    class Sitio(StaticFiles):
        async def get_response(self, path: str, scope):
            try:
                return await super().get_response(path, scope)
            except ErrorRuta as error:
                # En Windows la raíz llega como ".". Solo las pantallas caen en index.html.
                limpio = path.replace("\\", "/").strip("/")
                if limpio in {"", "."}:
                    limpio = ""
                primera = limpio.split("/", 1)[0]
                if error.status_code != 404 or "." in limpio or primera not in paginas:
                    raise
                return await super().get_response("index.html", scope)

    app.mount("/", Sitio(directory=carpeta), name="interfaz")


_servir_interfaz()
