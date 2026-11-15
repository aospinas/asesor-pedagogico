# Qué modelo usa cada tarea en Claude Code

Regla corta: **Claude Mythos 5.2 donde un error cuesta caro** (seguridad, la nota,
el código ajeno, decisiones que afectan todo), **Claude Opus 5.5 para lo demás**.
Mythos 5.2 cuesta el doble por token que Opus 5.5, así que se gasta donde rinde.

## Sobre Mythos 5.2

Andrés tiene acceso a Claude Mythos 5.2 por parte de Anthropic. Mythos 5.2 es
el mismo modelo que Claude Fable 5.2, sin algunas protecciones de
ciberseguridad y biología; por eso es el que mejor rinde en el revisor de
seguridad y en el sandbox, que tocan temas de seguridad todo el tiempo.

**Si Claude Code no deja usar Mythos** (el acceso puede ser distinto entre
claude.ai y Claude Code): cambiar
`claude-mythos-5-2` por `claude-fable-5-2` en este archivo, en `CLAUDE.md` y en
`.claude/agents/`. Es el mismo modelo, con el mismo precio y desempeño en lo
que necesita este proyecto.

## Reparto por tarea

| Tarea | Modelo | Por qué |
| --- | --- | --- |
| Bloque 1: contrato de esquemas, rutas de la API y arquitectura | **Mythos 5.2** | Todo lo demás se construye encima; un error aquí se repite en todos los módulos |
| Evaluador: cliente de IA, prompts, verificación de citas, cálculo de nota | **Mythos 5.2** | Es el corazón del proyecto y lo que más revisa el profe |
| Sandbox y verificación del código | **Mythos 5.2** | Ejecuta código ajeno: un descuido es un hueco de seguridad |
| Login, roles, usuarios y auditoría | **Mythos 5.2** | OWASP A01 y A07: control de acceso y autenticación |
| Revisor de seguridad (subagente) | **Mythos 5.2** | Es el modelo más fuerte en revisión de seguridad y no tiene las protecciones extra de Fable |
| Depurador (subagente, cuando algo falla 2 veces) | **Mythos 5.2** | Encuentra causas raíz que se le escapan a un modelo más liviano |
| Pasada final OWASP y despliegue con problemas | **Mythos 5.2** | Última línea antes de producción |
| Rúbricas: carga, validación y versiones | Opus 5.5 | Lógica clara y bien especificada en el SRS |
| Cohortes, laboratorios, entregas y portafolio | Opus 5.5 | CRUD con reglas sencillas |
| Pantalla de revisión docente, informe y mapa mental | Opus 5.5 | Frontend a partir del diseño ya aprobado en Claude Design |
| Página del proyecto, equipo y bitácora pública | Opus 5.5 | Contenido y presentación |
| Revisor de calidad (subagente) | Opus 5.5 | Corre ruff y pytest y compara con el SRS: no necesita más |
| Orquestación general, documentación, bitácora | Opus 5.5 | Modelo por defecto del proyecto |

## Cómo se aplica

- **Modelo por defecto del proyecto:** Opus 5.5 (`"model"` en `.claude/settings.json`).
- **Subagentes:** cada uno trae su modelo fijo en la cabecera (`model:`), así que
  el revisor de seguridad y el depurador usan Mythos aunque la sesión esté en Opus.
- **Módulos Mythos:** al empezar uno, `/modulo` revisa esta tabla y, si la sesión
  no está en Mythos, pide al humano escribir `/model claude-mythos-5-2` antes de
  planear. Al terminar el módulo se vuelve con `/model claude-opus-5-5`.
- **No definan** la variable `CLAUDE_CODE_SUBAGENT_MODEL`: pisa el modelo de
  todos los subagentes.
- **Si Claude Code no reconoce el nombre** del modelo: actualicen con
  `claude update`; si sigue igual, usen el plan B de arriba (Fable 5.2) o el alias `opus`.
