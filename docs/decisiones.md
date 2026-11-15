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
