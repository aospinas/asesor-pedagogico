---
description: Proponer direcciones visuales en Claude Design antes de construir pantallas (Puerta 0 del frontend)
argument-hint: <pantalla o "todo">
---

Vamos a diseñar: **$ARGUMENTS**

No escribas código de interfaz todavía.

1. Lee `docs/diseno/brief.md`. Si falta algo para esta pantalla, agrégalo al brief.
2. Propón **3 direcciones visuales distintas** (nombre, paleta, tipografía,
   cómo se ve cada pantalla clave y qué la hace propia de este equipo).
   Usa como punto de partida las ideas del brief, pero puedes proponer otras.
3. Llévalas a Claude Design con `/design` (o pide al humano que abra Claude
   Design en claude.ai con el brief) para que se vean en un lienzo.
   → **PUERTA 0:** el humano escoge una, o pide mezclar partes de varias.
4. Cuando el diseño esté aprobado, el humano hace en Claude Design:
   Export → Handoff to Claude Code → Send to local coding agent, y pega la
   orden en esta terminal. Si la orden no arranca, descarga el ZIP y te lo pasa.
5. Escribe `docs/diseno/decision.md`: opción elegida, por qué, paleta,
   tipografía y enlaces al diseño.
6. Construye con la skill `frontend-design` activa, respetando el diseño aprobado.
