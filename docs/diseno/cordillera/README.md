# Handoff del diseño Cordillera

Estos archivos son el diseño aprobado en la Puerta 0, tal como quedó en el lienzo
de Claude Design (https://claude.ai/artifact/4TRUmruCqwyUF6pBoWkBbu, versión
1794927348-8252). Son la referencia exacta para construir el frontend: colores,
tamaños, espacios, textos y estructura de cada pantalla.

| Archivo | Pantallas |
| --- | --- |
| `revision-docente.html` | 2 · Revisión docente (la más importante) |
| `inicio-informe-mapa-equipo.html` | 1 · Inicio, 3 · Informe, 4 · Mapa mental, 5 · Equipo |

Cómo usarlos:

- **No son código de la app.** Están en el formato de lienzo de Claude Design
  (`<x-dc>`, `{{verde}}`, `support.js`). Si se abren directo en el navegador no
  se ven completos; se ven bien en el lienzo.
- Al construir en React (`frontend/`), se copian los valores (colores, fuentes,
  tamaños) y la estructura, y se cumplen las reglas de `docs/diseno/decision.md`
  (animaciones, gráficas y metas de rendimiento), que van más allá de estos
  bocetos estáticos.
- Si el diseño cambia en el lienzo, se vuelven a copiar aquí y se anota en
  `decision.md`.

Por qué no se usó *Export → Handoff to Claude Code*: el lienzo lo armó Claude Code
desde esta misma sesión, así que ya tenía los archivos fuente. Se guardaron
directo en el repo, que es lo mismo que entrega el handoff.
