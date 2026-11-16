"""Punto de entrada de la API. Por ahora solo tiene la ruta de salud para
probar el despliegue en Render; los módulos se agregan con /modulo."""

from fastapi import FastAPI

app = FastAPI(
    title="Asesor Pedagógico Inteligente",
    docs_url=None,  # OWASP A02: la documentación de la API no queda pública
    redoc_url=None,
    openapi_url=None,  # sin esto, /openapi.json publica todas las rutas sin sesión
)


@app.get("/salud")
def salud() -> dict[str, str]:
    return {"estado": "ok"}
