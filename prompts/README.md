# Prompts versionados

Cada prompt es un archivo con versión en el nombre. Nunca se edita una versión
publicada: se crea la siguiente (`_v2`) y cada evaluación guarda cuál usó.

| Archivo | Para qué | Estado |
| --- | --- | --- |
| `evaluar_criterio_v1.md` | Proponer el nivel de un criterio con evidencias | Por crear en el módulo evaluador |
| `interpretar_rubrica_v1.md` | Convertir una rúbrica en PDF o Word a `RubricaEstructura` | Por crear en el módulo rúbricas |
| `plan_fortalecimiento_v1.md` | Redactar el plan a partir de datos ya calculados | Por crear en el módulo informes |

Reglas para todos los prompts:

- El material del estudiante va dentro de `<entrega>...</entrega>` y se trata
  como datos, nunca como instrucciones (OWASP LLM01).
- Nunca se pide una nota.
- La respuesta debe cumplir el esquema de `app/esquemas.py`.
