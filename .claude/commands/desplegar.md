---
description: Llevar main a producción en Render y comprobar que quedó funcionando (Puerta 4)
---

Vamos a desplegar. Primero corre `/probar-imagen` para confirmar en el PC que la
imagen construye y responde; luego GitHub Actions la vuelve a probar y Render la publica.

1. **CI en verde.** Revisa el último CI de `main` con `gh run list --branch main --limit 3`.
   Si el trabajo "Imagen Docker" o "Pruebas" falló, muestra el error con
   `gh run view <id> --log-failed`, propone el arreglo y para. Si es la segunda
   vez que falla por lo mismo, llama al subagente `depurador` (Mythos 5.2).
2. **Primera vez en Render** (si el humano dice que aún no existe el servicio):
   explícale en 4 pasos cortos cómo crear el servicio desde `render.yaml`
   (Render → New → Blueprint → este repo → llenar las variables `sync: false`).
   Espera a que confirme. No le pidas que pegue llaves en este chat.
3. **PR.** Si hay una rama lista sin PR, súbela y abre el PR con `gh pr create`.
   Andrés hace el merge en GitHub; espera a que confirme y luego `git pull`.
4. **Comprobación.** Cuando el humano te dé la URL de Render, corre
   `curl -fsS <url>/salud` (puede tardar hasta un minuto si Render estaba dormido).
   → **PUERTA 4:** muestra el resultado y pide al humano que abra la URL y
   recorra el flujo del último módulo.
5. Anota el despliegue en `docs/bitacora-ia.md` con `/bitacora despliegue`.
