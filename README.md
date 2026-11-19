# Asesor Pedagógico Inteligente

Plataforma web que evalúa laboratorios de IA de las cohortes 1 y 2.
**La IA propone, el backend calcula, el docente aprueba.**

Proyecto final de Profundización I - Inteligencia Artificial, Universidad de Manizales.
Equipo: Andrés Ospina Silva, Santiago Arias Aguirre y Jerónimo Aristizabal.



## Cómo está organizado

```
asesor-pedagogico/
├── CLAUDE.md                  reglas que Claude Code lee en cada sesión (orquestador)
├── .claude/
│   ├── agents/
│   │   ├── revisor-seguridad.md   subagente (Mythos 5.2): OWASP Top 10:2025 + LLM 2025, no edita
│   │   ├── revisor-calidad.md     subagente (Opus 5.5): ruff, pytest, criterios del SRS, no edita
│   │   └── depurador.md           subagente (Mythos 5.2): causa raíz cuando algo falla 2 veces
│   ├── commands/
│   │   ├── modulo.md          /modulo <nombre>  ciclo completo con las 4 puertas
│   │   ├── disenar.md         /disenar <pantalla>  3 opciones en Claude Design
│   │   ├── revisar.md         /revisar  lanza los dos revisores en paralelo
│   │   ├── bitacora.md        /bitacora <modulo>  fila en la bitácora de IA
│   │   ├── desplegar.md       /desplegar  CI en verde → Render → prueba /salud
│   │   └── probar-imagen.md   /probar-imagen  construye y prueba la imagen en el PC
│   ├── hooks/guardia.py       guardrail: bloquea push a main, merge de PR, borrados, leer .env
│   └── settings.json          permisos y hooks (guardrail + ruff automático)
├── .github/workflows/ci.yml   CI: pruebas en 3.15 y 3.12, OWASP, y construye y prueba la imagen Docker
├── app/
│   ├── esquemas.py            contrato de datos con la IA (extra="forbid")
│   ├── evaluador/nota.py      ÚNICO lugar donde se calcula la nota
│   ├── main.py                arranque de la API, cabeceras de seguridad y errores
│   ├── config.py, db.py, modelos.py   ajustes, conexión y tablas de la base
│   ├── api/rutas.py           tabla de rutas con el rol que puede usar cada una
│   ├── api/                   seguridad, sesión, usuarios y auditoría
│   ├── crear_admin.py         comando para crear el primer administrador
│   └── sandbox, rubricas, informes, ia   (se llenan con /modulo)
├── migraciones/               cambios de la base de datos (Alembic)
├── prompts/                   prompts versionados
├── tests/                     pruebas (nota, esquemas, rutas, sesión, usuarios, auditoría, guardrail)
├── frontend/                  React, después de elegir el diseño
├── docs/
│   ├── srs.md                 SRS completo (lo que lee Claude Code)
│   ├── 2026-11-15_srs_asesor-pedagogico.docx   el mismo SRS en Word, para el profesor
│   ├── modelos.md             qué modelo (Mythos 5.2 u Opus 5.5) usa cada tarea
│   ├── arranque-claude-code.md   el primer mensaje para pegar en Claude Code
│   ├── puertas-calidad.md     quality gates
│   ├── owasp-checklist.md     lista OWASP que usa el revisor
│   ├── decisiones.md          decisiones técnicas y por qué
│   ├── bitacora-ia.md         uso de IA (lo pide el profesor)
│   ├── costos.md              planes gratis y gasto de OpenAI
│   └── diseno/brief.md        entrada para Claude Design
├── Dockerfile                 imagen para Render (Python 3.15; plan B 3.12)
├── render.yaml                Render arma el servicio solo con este archivo
├── docker-compose.yml         PostgreSQL local para desarrollo
├── requirements*.in / *.txt   dependencias (versiones fijadas y probadas en 3.15)
├── pyproject.toml             configuración de ruff y pytest
└── .env.example               variables de entorno (copiar a .env)
```

## Arranque (Windows, PowerShell)

```powershell
# 0. Primera vez: sigue docs/arranque-claude-code.md (clonar, copiar el kit,
#    y Claude Code lo sube como PR "Kit inicial")
gh auth login                  # para que Claude Code pueda abrir los PR

# 1. Entorno con tu Python 3.15 (plan B: py -3.12 -m venv .venv)
py -3.15 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt

# 2. Verificar que todo está bien
pytest -q                      # deben pasar todas (corren en SQLite, no tocan tu base)
ruff check .

# 3. Variables
copy .env.example .env         # y llena los valores

# 3b. Base de datos local y primer administrador
docker compose up -d db        # PostgreSQL local (detén antes otro PostgreSQL que use el puerto 5432)
alembic upgrade head           # crea las tablas
python -m app.crear_admin      # pide nombre, correo y contraseña por teclado
uvicorn app.main:app --reload  # http://localhost:8000/salud

# 4. Skill de diseño (dentro de Claude Code)
#   /plugin install frontend-design@claude-plugins-official
#   /reload-plugins

# 5. Arrancar (el primer módulo va con Mythos 5.2)
#   claude --model claude-mythos-5-2
#   y pegar el mensaje de docs/arranque-claude-code.md
```

`bandit` no instala todavía en Python 3.15 (le falta PyYAML). Córrelo con:

```powershell
uvx --python 3.12 bandit -r app -q
```

(`uvx` viene con [uv](https://docs.astral.sh/uv/); baja Python 3.12 aparte sin tocar tu 3.15.)

**Pruebas contra PostgreSQL.** El CI corre las pruebas en SQLite. Antes de un PR que
toque la base de datos, córrelas también contra PostgreSQL, en una base aparte (las
pruebas borran sus tablas):

```powershell
docker compose exec db createdb -U asesor asesor_pruebas     # solo la primera vez
$env:PRUEBAS_DATABASE_URL = "postgresql+psycopg://asesor:asesor_local@127.0.0.1:5432/asesor_pruebas"
pytest -q
Remove-Item Env:PRUEBAS_DATABASE_URL
```

**Primer administrador en producción.** Render gratis no tiene consola. Se crea desde
el PC, apuntando esa terminal a la base de Supabase:

```powershell
$env:DATABASE_URL = "<la dirección de Supabase>"   # solo en esta terminal; no la guardes en archivos
python -m app.crear_admin
Remove-Item Env:DATABASE_URL
```

**Archivos de las entregas en producción.** En Supabase: Storage → New bucket →
nombre `evidencias`, **sin** marcar "Public bucket". En Render (Environment) van
`SUPABASE_URL` (Project Settings → Data API → Project URL) y `SUPABASE_SERVICE_KEY`
(Project Settings → API Keys → service_role). En el PC los archivos quedan en la
carpeta `almacen_local/`, que no se sube a GitHub.

Los demás usuarios los crea el administrador desde la app. Si alguien olvida su
contraseña o queda bloqueado, el administrador le pone una clave temporal y la persona
la cambia al entrar.

**Docker en el PC:** `/probar-imagen` construye y prueba la misma imagen que usa
Render antes de cada PR; `docker compose up -d db` levanta PostgreSQL local; y el
sandbox corre en contenedores sin red (`SANDBOX_MODE=docker`). El CI vuelve a
probar la imagen en cada push y Render la construye al desplegar. La primera vez
en Render: New → Blueprint → escoger el repo → llenar las variables. Después, `/desplegar`.

## Flujo de trabajo

Cada módulo pasa por `/modulo <nombre>`: plan → **puerta 1** → código y pruebas →
revisores → **puerta 2** → prueba manual → **puerta 3** → bitácora → Claude sube
la rama y abre el PR → **puerta 4**: Andrés hace el merge en GitHub y `git pull` →
despliegue → **puerta 5**. Las pantallas pasan antes por `/disenar` (**puerta 0**).
Detalle en `docs/puertas-calidad.md`.
