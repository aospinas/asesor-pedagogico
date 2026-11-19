"""Página del proyecto y bitácora de IA, públicas y sin sesión (RF-18, RF-22; D-26).

- El contenido del proyecto está aquí mismo: no sale de la base ni de la IA.
- La bitácora se lee de `docs/bitacora-ia.md` (la tabla "Registro por módulo"), que el
  Dockerfile copia a la imagen. Si el archivo no está, la ruta responde 503 sin tumbar la app.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status

from app.api import seguridad
from app.api.seguridad import limitador, ruta
from app.esquemas import Bitacora, FilaBitacora, MiembroEquipo, Proyecto, Tecnologia

router = APIRouter()

ARCHIVO_BITACORA = Path(__file__).resolve().parents[2] / "docs" / "bitacora-ia.md"
SIN_BITACORA = "La bitácora no está disponible en este momento."
SECCION = "## Registro por módulo"
COLUMNAS = 7

PROYECTO = Proyecto(
    nombre="Asesor Pedagógico Inteligente",
    abstract=(
        "Plataforma web que evalúa laboratorios de inteligencia artificial con apoyo de IA. "
        "El estudiante sube su informe, su código y sus evidencias; la IA propone un nivel por "
        "criterio de la rúbrica citando la evidencia exacta; el sistema verifica las citas, prueba "
        "el código en un entorno aislado y calcula la nota; y el docente revisa, ajusta y publica. "
        "Con lo publicado, cada estudiante recibe un informe de su avance, un plan para mejorar y "
        "un mapa mental de los temas de IA que domina."
    ),
    regla="La IA propone, el backend calcula, el docente aprueba.",
    tecnologias=[
        Tecnologia(
            nombre="FastAPI y Pydantic", para_que="API y validación estricta de todo lo que responde la IA"
        ),
        Tecnologia(
            nombre="PostgreSQL (Supabase)", para_que="Datos, versiones de rúbricas y traza de cada evaluación"
        ),
        Tecnologia(
            nombre="OpenAI, Ollama u OpenRouter",
            para_que="Evaluar criterios, convertir rúbricas y redactar planes",
        ),
        Tecnologia(
            nombre="Sandbox con Docker", para_que="Probar el código del estudiante sin red y con límites"
        ),
        Tecnologia(
            nombre="React, Vite y Cytoscape.js", para_que="Interfaz Cordillera y mapa mental interactivo"
        ),
        Tecnologia(nombre="WeasyPrint", para_que="Informe integrado en PDF"),
        Tecnologia(
            nombre="Render y GitHub Actions", para_que="Despliegue con Docker y pruebas en cada cambio"
        ),
        Tecnologia(nombre="Claude Code", para_que="Desarrollo asistido con revisores de seguridad y calidad"),
    ],
    aportes=[
        "La nota nunca la pone la IA: la calcula el backend con los pesos de la rúbrica.",
        "Cada evidencia que cita la IA se busca en la entrega; si no aparece, se marca.",
        "El código del estudiante corre en un sandbox sin red, con límites de tiempo y memoria.",
        "El docente revisa, cambia niveles con justificación y solo entonces publica.",
        "Traza completa por evaluación: modelo, prompt, huellas de archivos y cambios del docente.",
        "Se puede cambiar de proveedor de IA sin tocar el código, y se ve cuánto cuesta.",
    ],
    equipo=[
        MiembroEquipo(
            nombre="Andrés Ospina Silva",
            rol="Desarrollo y arquitectura",
            aporte="Lleva el desarrollo con Claude Code: backend, frontend, despliegue y pruebas",
        ),
        MiembroEquipo(
            nombre="Santiago Arias Aguirre",
            rol="QA y sustentación",
            aporte=(
                "Prueba el recorrido completo en producción con las cuentas de estudiante, docente y "
                "administrador · Presenta el problema, la regla de oro y cómo construimos el proyecto"
            ),
        ),
        MiembroEquipo(
            nombre="Jerónimo Aristizabal",
            rol="Frontend y sustentación",
            aporte=(
                "Hizo la base del frontend en React (PR #16) · Presenta la revisión del docente y lo que "
                "ve el estudiante"
            ),
        ),
    ],
    repositorio="https://github.com/aospinas/asesor-pedagogico",
)


@ruta(router, "GET", "/api/proyecto", response_model=Proyecto)
def ver_proyecto() -> Proyecto:
    return PROYECTO


def leer_bitacora(texto: str) -> list[FilaBitacora]:
    """Las filas de la tabla "Registro por módulo" (sin el encabezado ni la línea de guiones)."""
    filas: list[FilaBitacora] = []
    dentro = False
    for linea in texto.splitlines():
        if linea.startswith("## "):
            dentro = linea.strip() == SECCION
            continue
        if not dentro or not linea.startswith("|"):
            continue
        celdas = [c.strip() for c in linea.strip().strip("|").split(" | ")]
        if len(celdas) != COLUMNAS or celdas[0] in {"Fecha", "---"} or set(celdas[0]) <= {"-", " "}:
            continue
        filas.append(FilaBitacora(**dict(zip(FilaBitacora.model_fields, celdas, strict=True))))
    return filas


@ruta(router, "GET", "/api/bitacora", response_model=Bitacora)
@limitador.limit("30/minute", key_func=seguridad.ip_de)
def ver_bitacora(request: Request) -> Bitacora:
    try:
        texto = ARCHIVO_BITACORA.read_text(encoding="utf-8")
    except OSError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, SIN_BITACORA) from None
    return Bitacora(filas=leer_bitacora(texto))
