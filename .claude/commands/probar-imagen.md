---
description: Construir y probar en el PC la misma imagen Docker que usa Render, antes de abrir el PR
---

Prueba la imagen Docker en el PC. Así los fallos salen aquí y no en el CI ni en Render.

1. `docker build -t asesor:local .`
   Si falla, muestra el error. Si falla dos veces por lo mismo, llama al
   subagente `depurador`.
2. `docker run -d --name asesor-prueba -p 8001:8000 -e PORT=8000 asesor:local`
3. Espera hasta 30 segundos y prueba `curl -fsS http://localhost:8001/salud`.
4. Muestra el resultado y el tamaño de la imagen (`docker images asesor:local`).
5. Detén y quita el contenedor de prueba: `docker stop asesor-prueba` y
   `docker rm asesor-prueba` (es un contenedor temporal creado por ti, no un archivo
   del proyecto).
6. Di en una línea si la imagen está lista para el PR.
