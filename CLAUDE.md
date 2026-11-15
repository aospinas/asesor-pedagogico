# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Asesor Pedagógico Inteligente

Proyecto final de Profundización I - IA (Universidad de Manizales).
Equipo: Andrés Ospina Silva y Santiago Arias Aguirre. El desarrollo lo lleva Andrés.

Plataforma web que evalúa laboratorios con IA. Regla de oro:
**la IA propone, el backend calcula, el docente aprueba.**

El SRS completo está en `docs/srs.md`. Antes de tocar un módulo, lee la sección
del SRS y la fila de la matriz de trazabilidad que le corresponde.

## Tu papel: orquestador

Eres la sesión principal. Planeas, construyes y llamas a los revisores.
Los subagentes no pueden lanzar otros subagentes, así que la coordinación es tuya.

Para cada módulo sigue `/modulo <nombre>` (archivo `.claude/commands/modulo.md`).
No te saltes ninguna puerta humana de `docs/puertas-calidad.md`.

## Modelos

Mythos 5.2 donde un error cuesta caro; Opus 5.5 para lo demás. Si Mythos no
está disponible en la sesión, se usa `claude-fable-5-2` (mismo modelo). Tabla completa en
`docs/modelos.md`.

- **Mythos 5.2 (`claude-mythos-5-2`):** contrato de esquemas y arquitectura,
  evaluador, sandbox, login/roles/auditoría, pasada final OWASP, despliegue con
  problemas. Subagentes `revisor-seguridad` y `depurador`.
- **Opus 5.5 (`claude-opus-5-5`, por defecto):** rúbricas, laboratorios,
  entregas, portafolio, revisión docente, informe, mapa mental, página del
  equipo, frontend, documentación. Subagente `revisor-calidad`.
- Antes de planear un módulo, revisa la tabla. Si el módulo es Mythos y la
  sesión no lo está, pide al humano `/model claude-mythos-5-2` y espera.
- Si una prueba, el CI o el despliegue fallan dos veces seguidas, no sigas
  probando a ciegas: llama al subagente `depurador`.

## Reglas que no se rompen

1. La nota la calcula `app/evaluador/nota.py`. Ningún prompt pide una nota y
   ningún esquema de salida de la IA tiene campo de nota.
2. Toda salida de la IA se valida con los modelos de `app/esquemas.py`
   (tienen `extra="forbid"`: si la IA agrega campos, se rechaza).
3. Nunca ejecutes código de un estudiante fuera de `app/sandbox/`.
4. Secretos solo en variables de entorno. Nunca leas ni escribas `.env`.
   Usa `.env.example` para documentar variables nuevas.
5. Cada RF nuevo lleva al menos una prueba en `tests/`.
6. Interfaz en español, lenguaje sencillo, sin palabras rebuscadas.
7. Antes de crear o cambiar una pantalla: usa `/disenar`, propone opciones en
   Claude Design y espera la elección del humano. Nada de estilos fuera de lo
   aprobado en `docs/diseno/decision.md`.
8. Flujo de Git (como en el proyecto SECOP): trabajas en ramas `feat/<modulo>`,
   tú subes la rama (`git push -u origin feat/<modulo>`) y abres el PR con
   `gh pr create`. **Andrés revisa el PR en GitHub, hace el merge y luego
   `git pull`.** Nunca hagas push a `main`, push forzado ni `gh pr merge`.
9. Al cerrar un módulo, agrega una fila a `docs/bitacora-ia.md` con `/bitacora`.
10. Si una decisión técnica cambia el SRS, anótala en `docs/decisiones.md`.

## Stack

- Python 3.15 (probado el 13-nov-2026: todas las dependencias instalan y las
  pruebas pasan). Plan B: Python 3.12, también probado. El CI corre en las dos.
- FastAPI + Pydantic 2.14+, SQLAlchemy + PostgreSQL (Supabase), PyMuPDF,
  rapidfuzz, WeasyPrint, SDK de OpenAI (sirve para OpenAI, Ollama y OpenRouter).
- Frontend: React + Vite + Cytoscape.js en `frontend/` (se crea después del diseño).
- Despliegue: Render (Docker, plan gratis, definido en `render.yaml`) + Supabase (plan gratis).

## Docker

Andrés tiene Docker en el PC. Se usa para tres cosas:

1. **Probar la imagen antes de cada PR** que toque `Dockerfile`, `requirements*.txt`
   o el arranque de la app: corre `/probar-imagen`. El CI la vuelve a probar y
   Render la construye al desplegar.
2. **Base de datos de desarrollo:** `docker compose up -d db` (PostgreSQL local).
   Supabase solo se usa en producción.
3. **Sandbox completo:** en el PC, `SANDBOX_MODE=docker` ejecuta el código de los
   estudiantes en contenedores desechables con `--network none`, límite de memoria,
   CPU y procesos, y sistema de archivos de solo lectura. En Render se usa
   `SANDBOX_MODE=proceso`. La app en el PC se corre con uvicorn desde `.venv`,
   nunca dentro de un contenedor con el socket de Docker montado.

Para desplegar usa `/desplegar`.

## Comandos (Windows, PowerShell)

```powershell
py -3.15 -m venv .venv        # plan B: py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
pytest -q
pytest tests/test_nota.py -q                    # un solo archivo
pytest tests/test_nota.py::nombre_prueba -q     # una sola prueba (o -k "texto")
pytest -q --cov=app --cov-report=term-missing   # igual que el CI
ruff check . ; ruff format --check .
pip-audit -r requirements.txt         # el CI falla si hay dependencias vulnerables
uvx --python 3.12 bandit -r app -q    # en 3.15 bandit no instala (le falta PyYAML)
docker compose up -d db               # PostgreSQL local (DATABASE_URL de .env.example)
uvicorn app.main:app --reload         # la API no publica /docs ni /redoc; prueba con /salud
```

**Dependencias:** se editan `requirements.in` / `requirements-dev.in`, nunca los
`.txt` a mano. Los `.txt` se regeneran con uv:

```powershell
uv pip compile --universal --python-version 3.12 requirements.in -o requirements.txt
```

`requirements-dev.in` usa `-c requirements.txt`, así que primero se regenera
`requirements.txt`. No agregues nada que dependa de PyYAML (por eso `uvicorn` va
sin `[standard]`): todavía no tiene paquete para 3.15. Si cambian los `.txt`,
toca `/probar-imagen`.

Ruff: línea de 110, reglas `E, F, I, B, UP, S, SIM` (las `S` son de seguridad).
En `tests/` se permiten `assert` y `subprocess`.

## Cómo encaja todo

Flujo de una evaluación (SRS secciones 9 y 10):

1. La rúbrica se guarda como `RubricaEstructura` y debe pasar `validar_rubrica`
   (pesos que suman 100, ids únicos, niveles con descriptor).
2. Por cada criterio, la IA recibe un prompt versionado de `prompts/` y devuelve
   un `ResultadoCriterio`: nivel propuesto, justificación y evidencias con
   archivo, ubicación y fragmento textual. Sin nota.
3. El backend calcula la nota con `calcular_nota(rubrica, {criterio_id: nivel_id})`.
   Exige un nivel para **todos** los criterios y ninguno de sobra; si algo no
   cuadra lanza `ErrorDeNota`. Usa `Decimal` y redondeo comercial a un decimal.
4. El docente revisa, cambia niveles si quiere (la nota se recalcula con la misma
   función) y aprueba. Solo entonces la ve el estudiante.

Puntos que hay que conocer antes de tocar código:

- **Modelos nuevos** en `app/esquemas.py` heredan de `Estricto`
  (`extra="forbid"` y recorte de espacios), no de `BaseModel` directo.
- **Prompts** (`prompts/README.md`): una versión publicada no se edita, se crea
  la siguiente (`_v2`) y cada evaluación guarda cuál usó. El material del
  estudiante va dentro de `<entrega>...</entrega>` y se trata como datos, nunca
  como instrucciones.
- **Un solo cliente de IA:** SDK de OpenAI con `LLM_BASE_URL`; cambiar de
  proveedor es cambiar variables de entorno, no código.
- **Imagen:** el `Dockerfile` solo copia `app/` y `prompts/`, y corre como
  usuario sin privilegios. Si la app necesita otra carpeta en producción, hay
  que agregarla ahí. Las variables de producción se declaran en `render.yaml`
  además de `.env.example`.
- **Estado actual:** solo existen el contrato base (`esquemas.py`), el cálculo
  de la nota y la ruta `/salud`. Los demás paquetes de `app/` están vacíos y se
  llenan en el orden de `docs/arranque-claude-code.md`.

## Guardrails automáticos

Definidos en `.claude/settings.json`:

- **Antes de cada acción** corre `.claude/hooks/guardia.py`. Además de lo de la
  regla 8, bloquea `git merge` de ramas `feat/` o `fix/`, `git reset --hard`,
  borrados recursivos (`rm -rf`, `Remove-Item -Recurse`, `rd /s`), `curl | sh`,
  leer `.env` y listar variables de entorno. Si bloquea algo, no busques otra
  forma de hacerlo: pregunta a Andrés.
- **Después de cada edición** corre `ruff check --fix` y `ruff format` sobre
  todo el repo: puede reordenar imports o quitar los que aún no se usan.
- Los hooks llaman a `python` y `ruff` del PATH, así que la sesión debe abrirse
  con `.venv` activado.
- Si cambias `guardia.py`, actualiza `tests/test_guardia.py` (prueba cada
  patrón bloqueado y los permitidos).

## Estructura

```
app/            backend (api, evaluador, sandbox, rubricas, informes, ia, auditoria)
app/esquemas.py contrato de datos con la IA y entre módulos
prompts/        prompts versionados (evaluar_criterio_v1.md, ...)
tests/          pruebas con pytest
frontend/       React (después de aprobar el diseño)
docs/           SRS, bitácora, decisiones, costos, OWASP, diseño
.claude/        agentes, comandos y guardrails de Claude Code
```
