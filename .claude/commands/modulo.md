---
description: Ciclo completo de un módulo con sus puertas humanas (plan, construcción, revisión, prueba, bitácora)
argument-hint: <nombre-del-modulo>
---

Vamos a trabajar el módulo: **$ARGUMENTS**

Sigue estos pasos en orden. En cada PUERTA te detienes y esperas al humano.

0. **Modelo.** Busca el módulo en `docs/modelos.md`. Si le toca Mythos 5.2 y
   esta sesión no está en Mythos, para y pide al humano: `/model claude-mythos-5-2`.
   Si le toca Opus 5.5 y la sesión está en Mythos, sugiere `/model claude-opus-5-5`
   para no gastar de más.
1. **Contexto.** Lee en `docs/srs.md` los RF del módulo y su fila en la matriz
   de trazabilidad (sección 13). Lee `app/esquemas.py`.
2. **Plan.** Propón: archivos que vas a crear o cambiar, RF que cubres, pruebas
   que vas a escribir y riesgos OWASP que aplican.
   → **PUERTA 1:** espera aprobación del plan. No escribas código antes.
3. **Rama.** `git switch -c feat/$ARGUMENTS`
4. **Construcción.** Escribe primero las pruebas y luego el código. Corre
   `pytest -q` hasta que pase. Si falla dos veces seguidas por lo mismo, llama
   al subagente `depurador` antes del tercer intento.
5. **Revisión.** Lanza en paralelo los subagentes `revisor-seguridad` y
   `revisor-calidad`. Muestra sus dos tablas sin resumirlas de más.
   → **PUERTA 2:** el humano decide qué hallazgos se arreglan ya.
6. **Arreglos.** Arregla lo aprobado y vuelve a correr las pruebas.
7. **Prueba manual.** Explica en 3 a 5 pasos cómo probar el módulo a mano.
   → **PUERTA 3:** espera que el humano confirme que funciona.
8. **Bitácora.** Ejecuta lo que dice `/bitacora` para este módulo.
8b. **Imagen.** Si el módulo tocó `Dockerfile`, `requirements*.txt` o el arranque
   de la app, corre `/probar-imagen` antes de subir.
9. **Subir y abrir PR.** Haz commit, `git push -u origin feat/$ARGUMENTS` y
   `gh pr create --base main` con: qué hace el módulo, RF cubiertos, resumen de
   los dos revisores, resultado de las pruebas y cómo probarlo a mano.
   Comparte el enlace del PR.
   → **PUERTA 4:** Andrés revisa el PR, espera el CI en verde y hace el merge en
   GitHub. Luego tú haces `git switch main` y `git pull`.
10. **Producción.** Render despliega solo después del merge. Avisa cuando
   `/salud` responda en la URL pública.
   → **PUERTA 5:** Andrés abre la URL pública, recorre el flujo del módulo y
   confirma que funciona.
