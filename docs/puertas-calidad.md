# Puertas de calidad (quality gates)

Ningún cambio llega a producción sin pasar estas puertas. Las automáticas las
revisa la máquina; las humanas solo las abre Andrés.

| Puerta | Cuándo | Quién la abre | Qué se exige |
| --- | --- | --- | --- |
| 0. Diseño | Antes de crear o cambiar pantallas | Humano | Una de las 3 direcciones de Claude Design elegida y anotada en `docs/diseno/decision.md` |
| 1. Plan | Antes de escribir código del módulo | Humano | Plan con archivos, RF cubiertos, pruebas y riesgos OWASP |
| Guardrails | En cada acción de Claude Code | Automática (`.claude/hooks/guardia.py`) | Sin push a main, sin merge hecho por Claude, sin borrados recursivos, sin leer `.env` |
| Formato | Después de cada edición | Automática (hook de ruff) | Código formateado y sin errores de ruff |
| 2. Revisión | Al terminar el módulo | Humano, con las tablas de los dos revisores | Ningún hallazgo Crítico o Alto abierto |
| 3. Prueba manual | Antes de abrir el PR | Andrés | El caso de uso del módulo funciona en local |
| 4. PR | Cuando Claude sube la rama y abre el PR | Andrés, en GitHub | CI en verde, revisa el PR, hace el merge y luego `git pull` |
| Imagen local | Antes del PR, si se tocó la imagen | Automática (`/probar-imagen`) | La imagen construye en el PC y responde en `/salud` |
| CI | En cada push | Automática (GitHub Actions) | Pruebas en 3.15 y 3.12, ruff, pip-audit, bandit, y la imagen Docker construye y responde en `/salud` |
| 5. Producción | Después del merge | Andrés | La URL pública responde y el flujo del módulo funciona |
