# Arranque en Claude Code

Todo el desarrollo lo lleva Andrés con Claude Code. El flujo de Git es el mismo
del proyecto SECOP TIC: **Claude sube las ramas y abre los PR; Andrés hace el
merge en GitHub y el pull.**

No hace falta adjuntarle el SRS en Word a Claude Code: ya está dentro del repo
como `docs/srs.md`, que Claude lee mejor. El Word (`docs/2026-11-15_srs_asesor-pedagogico.docx`)
queda para entregarlo al profesor.

## Paso a paso

Tú solo haces dos cosas; lo demás lo hace Claude Code.

1. Copia el ZIP del kit (`2026-11-15_kit_asesor-pedagogico_v7.zip`) dentro de
   la carpeta que creaste para el proyecto. Que quede solo el ZIP ahí.
2. Abre una terminal en esa carpeta y arranca Claude Code con Mythos:
   `claude --model claude-mythos-5-2`
   (si dice que el modelo no existe: `claude --model claude-fable-5-2`, es el mismo modelo)

Luego pega este mensaje tal cual:

```text
Soy Andrés. Vamos a construir el Asesor Pedagógico Inteligente; tú eres el orquestador. Ya creé en GitHub el repo vacío asesor-pedagogico y esta carpeta solo tiene el ZIP del kit. Haz tú toda la preparación, en este orden, y avísame solo si necesitas algo de mí:

1. Herramientas: revisa que estén git, gh (con gh auth status) y Python 3.15 (py -3.15 --version; si no está, usa 3.12). Si gh no tiene sesión, dime qué comando correr y espera.
2. Repo: busca con gh repo list la URL de mi repo asesor-pedagogico. Haz git init -b main, crea un README.md con el título "Asesor Pedagógico Inteligente", haz commit "Inicio del repositorio", conecta el remoto y sube main. Esto se hace ANTES de descomprimir el kit, porque el kit trae un guardrail que después bloquea los push a main.
3. Kit: descomprime el ZIP aquí mismo (su contenido está dentro de una carpeta asesor-pedagogico: pasa todo, incluidos los archivos y carpetas ocultos, a la raíz del repo y reemplaza el README). Saca el ZIP y la carpeta vacía del repo, sin borrarlos: muévelos a una carpeta _fuera_del_repo al lado de esta.
4. Prueba local: crea .venv con Python 3.15, instala requirements-dev.txt y corre pytest -q (deben pasar 31) y ruff check . Después revisa que Docker esté corriendo (docker info), corre /probar-imagen y levanta la base local con docker compose up -d db. Copia .env.example a .env (yo lleno las llaves después).
5. PR del kit: crea la rama kit-inicial, haz commit "Kit inicial: SRS, agentes, guardrails, CI y contrato base", súbela y abre el PR hacia main con gh pr create. Pásame el enlace y espera a que yo haga el merge en GitHub. Después haz git switch main y git pull, y revisa con gh run list que el CI de main quede en verde (pruebas en 3.15 y 3.12 y la imagen Docker).
6. Contexto: lee CLAUDE.md, docs/srs.md (sobre todo las secciones 3, 4, 9, 11, 12 y 13), docs/modelos.md, docs/puertas-calidad.md y docs/owasp-checklist.md. Dime en 5 líneas qué entendiste del proyecto, de las reglas y del flujo de Git, y cualquier contradicción que veas.
7. Primer módulo: arranca /modulo contrato y propón cómo completar app/esquemas.py (usuarios, cohortes, laboratorios, entregas, evidencias, evaluaciones, revisiones del docente) y la lista de rutas de la API con el rol que puede usar cada una. No escribas código del módulo hasta que yo apruebe el plan.

Tengo Docker en el PC: úsalo para probar la imagen antes de cada PR, para la base de datos local y para el sandbox en modo docker.
```

Cuando Claude termine la preparación, instala la skill de diseño dentro de
Claude Code: `/plugin install frontend-design@claude-plugins-official` y luego
`/reload-plugins`.

## Después de cada módulo

1. Claude te pasa el enlace del PR.
2. En GitHub: revisa el PR, espera el CI en verde y haz el merge.
3. Le dices a Claude "listo el merge" y él hace `git pull`.
4. Sigues con el siguiente módulo de la tabla. Cuando cambie el modelo, escribe
   `/model claude-mythos-5-2` o `/model claude-opus-5-5` (Claude te lo recuerda).

## Orden de los módulos

| # | Módulo | Modelo | Comando |
| --- | --- | --- | --- |
| 1 | Contrato de esquemas y rutas | Mythos 5.2 | `/modulo contrato` |
| 2 | Login, roles, usuarios y auditoría | Mythos 5.2 | `/modulo auth` |
| 3 | Primer despliegue en Render | Mythos 5.2 | `/desplegar` |
| 4 | Diseño en Claude Design | Opus 5.5 | `/disenar todo` |
| 5 | Rúbricas | Opus 5.5 | `/modulo rubricas` |
| 6 | Cohortes, laboratorios, entregas y portafolio | Opus 5.5 | `/modulo entregas` |
| 7 | Evaluador | Mythos 5.2 | `/modulo evaluador` |
| 8 | Sandbox | Mythos 5.2 | `/modulo sandbox` |
| 9 | Revisión docente | Opus 5.5 | `/modulo revision` |
| 10 | Informe integrado y mapa mental | Opus 5.5 | `/modulo informe` |
| 11 | Página del proyecto y bitácora pública | Opus 5.5 | `/modulo proyecto` |
| 12 | Pasada final OWASP | Mythos 5.2 | `/revisar` sobre `main` |
| 13 | Despliegue final | Mythos 5.2 | `/desplegar` |

**Para ir más rápido (opcional):** mientras una sesión con Mythos hace el
evaluador o el sandbox, abre otra terminal con Opus 5.5 en una copia aparte del
repo y avanza un módulo de interfaz:

```powershell
git worktree add ..\asesor-front -b feat/revision
cd ..\asesor-front
claude --model claude-opus-5-5
```

Cada sesión abre su propio PR y tú haces los dos merges.
