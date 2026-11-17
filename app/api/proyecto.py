"""Página pública del proyecto y bitácora de uso de IA (RF-18, RF-22)."""

from pathlib import Path

from fastapi import APIRouter

from app.api.seguridad import ruta
from app.esquemas import BitacoraPublica, Integrante, ProyectoPublico

router = APIRouter()

_BITACORA = Path(__file__).resolve().parents[2] / "docs" / "bitacora-ia.md"


@ruta(router, "GET", "/api/proyecto", response_model=ProyectoPublico)
def ver_proyecto() -> ProyectoPublico:
    return ProyectoPublico(
        titulo="Asesor Pedagógico Inteligente",
        abstract=(
            "Plataforma web para evaluar laboratorios de inteligencia artificial de dos cohortes. "
            "El estudiante sube su informe y su código, la IA propone un nivel por cada criterio "
            "de la rúbrica citando evidencias, y el backend calcula la nota de 0,0 a 5,0. "
            "El docente revisa, ajusta y publica. El estudiante ve un informe de su aprendizaje "
            "y un mapa mental de los temas."
        ),
        tecnologias=[
            "Python, FastAPI y Pydantic",
            "PostgreSQL",
            "React",
            "Modelos de lenguaje configurables (OpenAI, Ollama u OpenRouter)",
            "Sandbox para revisar el código sin red",
        ],
        aportes=[
            "La nota la calcula el sistema, no el modelo de lenguaje.",
            "Cada cita de la IA se busca en la entrega y se marca si no aparece.",
            "El docente aprueba antes de que el estudiante vea la nota.",
            "Queda la traza: rúbrica, modelo, pruebas del código y quién aprobó.",
        ],
        equipo=[
            Integrante(nombre="Andrés Ospina Silva", rol="Desarrollo", foto_url=None),
            Integrante(nombre="Santiago Arias Aguirre", rol="Integrante del equipo", foto_url=None),
            Integrante(nombre="Jerónimo Aristizabal", rol="Integrante del equipo", foto_url=None),
        ],
    )


@ruta(router, "GET", "/api/bitacora", response_model=BitacoraPublica)
def ver_bitacora() -> BitacoraPublica:
    texto = _BITACORA.read_text(encoding="utf-8") if _BITACORA.is_file() else ""
    return BitacoraPublica(contenido=texto[:100_000])
