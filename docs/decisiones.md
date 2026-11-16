# Decisiones técnicas

Una entrada por decisión: qué se decidió, por qué y qué se descartó.

## D-01 · Render + Supabase para desplegar gratis (13-nov-2026)

- **Decisión:** la app corre en Render (servicio web gratis con Docker) y los datos y archivos en Supabase (plan gratis).
- **Por qué:** cero costo, despliegue desde GitHub, PostgreSQL que el equipo ya conoce.
- **Descartado:** Hugging Face Spaces, porque crear un Space con Docker ya pide plan de pago.
- **Costo de la decisión:** Render se duerme a los 15 minutos sin visitas y tarda cerca de un minuto en despertar; Supabase se pausa tras una semana sin uso.

## D-02 · Python 3.15 (13-nov-2026)

- **Decisión:** usar Python 3.15, que es la versión que Andrés ya tiene instalada.
- **Prueba hecha:** todas las dependencias de `requirements-dev.txt` instalan con paquetes binarios para Python 3.15 en Windows y en Linux, y las pruebas pasan en 3.15 (26 ese día; 31 después de sumar las del flujo de Git).
- **Excepción:** PyYAML aún no tiene paquete para 3.15. Por eso `uvicorn` va sin `[standard]` y `bandit` solo se instala en 3.12; en 3.15 se corre con `uvx --python 3.12 bandit -r app -q`.
- **Plan B:** Python 3.12. Se probó igual: las dependencias instalan en Windows y Linux, las pruebas pasan y bandit no encuentra problemas. Para cambiar: `PYTHON_VERSION=3.12` en el `Dockerfile` y `py -3.12` en el PC. El CI corre en las dos versiones.

## D-03 · Un solo cliente de IA para tres proveedores (13-nov-2026)

- **Decisión:** SDK oficial de OpenAI cambiando la dirección base para OpenAI, Ollama y OpenRouter.
- **Por qué:** los tres aceptan el mismo formato de API; cambiar de proveedor es cambiar variables de entorno (RF-19).

## D-04 · La nota se calcula solo en el backend (13-nov-2026)

- **Decisión:** `app/evaluador/nota.py` es el único lugar que calcula notas; la salida de la IA no tiene campo de nota y `extra="forbid"` rechaza cualquier campo extra.
- **Por qué:** lo exige el enunciado (condición 2) y protege contra inyección de prompt.

## D-05 · Sandbox por proceso en la nube, Docker en local (13-nov-2026)

- **Decisión:** en Render el sandbox usa procesos con límites (`SANDBOX_MODE=proceso`); en local usa contenedores sin red (`SANDBOX_MODE=docker`).
- **Por qué:** Render gratis no permite Docker dentro del contenedor.
- **Nota de licencia:** Docker Desktop es gratis para uso personal y educativo, pero pide licencia paga en empresas grandes. Si el PC es de la empresa, revisar eso o usar Docker Engine dentro de WSL2, que es gratis.

## D-06 · El diseño se elige en Claude Design antes de programar (13-nov-2026)

- **Decisión:** el orquestador propone 3 direcciones en Claude Design, Andrés escoge una y se pasa a código con el handoff.
- **Por qué:** que la interfaz sea propia del equipo y no una plantilla genérica.

## D-07 · Docker en el PC para probar; CI y Render para confirmar y publicar (15-nov-2026)

- **Decisión:** Andrés tiene Docker en el PC. Claude Code prueba la imagen ahí con `/probar-imagen` antes de cada PR que la toque; el CI la vuelve a construir y probar en cada push, y Render la construye al desplegar con `render.yaml`.
- **Además:** PostgreSQL local con `docker compose up -d db` para desarrollo, y sandbox completo (`SANDBOX_MODE=docker`, contenedores sin red) en el PC.
- **Por qué:** los fallos de la imagen salen en minutos en el PC y no después del push; y el sandbox con contenedores es el que se muestra en la sustentación.
- **Lo que hace el humano:** solo la primera conexión de Render con el repo (New → Blueprint) y llenar las variables secretas.

## D-08 · Mythos 5.2 para lo crítico, Opus 5.5 para lo demás (15-nov-2026)

- **Decisión:** el proyecto corre por defecto en Claude Opus 5.5. Los módulos donde un error cuesta caro (contrato de esquemas, evaluador, sandbox, autenticación, pasada OWASP final) y los subagentes `revisor-seguridad` y `depurador` usan Claude Mythos 5.2. Detalle en `docs/modelos.md`.
- **Por qué:** Mythos 5.2 es el modelo más capaz al que tiene acceso el equipo y el más fuerte en seguridad, pero cuesta el doble por token que Opus 5.5; se usa donde más rinde.
- **Plan B:** Claude Fable 5.2, que es el mismo modelo con más protecciones, si Mythos no está disponible en Claude Code.

## D-09 · Flujo de Git con PR: Claude sube, Andrés hace el merge (15-nov-2026)

- **Decisión:** Andrés crea el repo. Claude Code trabaja en ramas `feat/<modulo>`, las sube y abre un PR. Andrés revisa el PR en GitHub, espera el CI en verde, hace el merge y luego `git pull`. Es el mismo flujo del proyecto SECOP TIC.
- **Por qué:** el merge del PR es la puerta humana final antes de producción, y queda registrada en GitHub como evidencia de la supervisión.
- **Cómo se hace cumplir:** el guardrail bloquea push a `main`, `gh pr merge` y merges locales de ramas.
- **Quién desarrolla:** todo el desarrollo lo lleva Andrés con Claude Code; Santiago Arias Aguirre figura como integrante del equipo.

## D-10 · La documentación de la API queda cerrada para todos (15-nov-2026)

- **Decisión:** `/docs` y `/redoc` de FastAPI quedan apagados para todos los roles. La lista de rutas se lee en `docs/api.md`.
- **Por qué:** el SRS (A02) decía "`/docs` solo para admin", pero cerrarla del todo es más simple y más seguro, y así ya estaban `app/main.py` y la lista OWASP.

## D-11 · Un solo nombre por estado de evaluación (15-nov-2026)

- **Decisión:** los estados son cinco y viven en `EstadoEvaluacion` de `app/esquemas.py`: en proceso, en revisión, revisión manual, aprobada y publicada.
- **Por qué:** el SRS usaba "Pendiente de revisión" y "En revisión" para lo mismo, y "Requiere revisión manual" y "Revisión manual" para lo mismo. Queda el nombre del diagrama de la sección 6.

## D-12 · Contrato de datos y tabla de rutas con rol (15-nov-2026)

- **Decisión:** `app/api/rutas.py` es la fuente única de qué rol usa cada ruta; `docs/api.md` es la misma tabla para leer y una prueba falla si no coinciden.
- **Usuarios:** los crea el administrador (`POST /api/usuarios`); no hay registro público. RF-01 dice "registro e inicio de sesión" y aquí "registro" se entiende como el alta que hace el administrador (RF-02).
- **Niveles ordenados (RF-05):** los valores de los niveles de un criterio deben ir de menor a mayor o de mayor a menor, sin repetirse.
- **Notas:** ningún modelo de entrada (IA, docente o estudiante) tiene campo de nota; solo aparecen en modelos que arma el backend.

## D-13 · Arreglos de la revisión del contrato (15-nov-2026)

Salieron de los dos revisores en la Puerta 2 del módulo contrato.

- **Dirección de la IA cerrada:** OpenAI y OpenRouter solo aceptan su dirección oficial; Ollama solo los equipos de la variable `OLLAMA_HOSTS_PERMITIDOS`. Así nadie puede hacer que el backend mande la llave a otro servidor.
- **Contraseñas:** máximo 72 bytes (límite de bcrypt), no se les recortan los espacios, y cada usuario cambia la suya en `PUT /api/yo/contrasena` para que el administrador no la conozca.
- **Correo:** se guarda en minúsculas.
- **Topes de tamaño:** textos y listas de la IA, de la rúbrica y del sandbox tienen máximo; los números no aceptan infinito.
- **Documentación de la API:** además de `/docs` y `/redoc`, se cierra `/openapi.json`.
- **Rutas:** `GET /api/estudiantes` para el docente y `/api/mis-entregas` en vez de `/api/entregas/mias`.

**Queda para el módulo que lo toca:**

| Módulo | Pendiente |
| --- | --- |
| auth | Marcar en la tabla de rutas las que son "solo si está publicada"; no guardar secretos en el detalle de la auditoría y tipar la IP; auditar cambios de rol |
| entregas | Modelos `LaboratorioEditar` y `Rubrica`; que el estudiante llegue desde su entrega a la evaluación publicada |
| revision | Que el docente pueda editar la justificación; publicar solo citas encontradas; decidir si el administrador ve la traza |
| proyecto | Modelo `IntegranteEquipo` sin correo para la página pública |
