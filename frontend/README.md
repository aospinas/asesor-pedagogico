# Frontend

Interfaz en React (dirección Cordillera, `docs/diseno/decision.md`). Base de Jerónimo
Aristizabal (PR #16), adaptada a la API real (D-23).

```powershell
cd frontend
npm install
npm run dev     # abre http://localhost:5173 (es el origen de ORIGENES_PERMITIDOS en .env.example);
                # reenvía /api y /salud a http://127.0.0.1:8000
npm test        # Vitest
npm run build   # deja los archivos en frontend/dist
```

La API tiene que estar corriendo (`uvicorn app.main:app --reload`). Si `frontend/dist`
existe, la API los sirve en la misma dirección (así funciona en Render).

## Cómo agregar una pantalla

1. Crea el archivo en `src/paginas/` y su ruta en `src/App.tsx` (con `solo("rol", ...)`).
2. Si el camino empieza por una palabra nueva, agrégala a `PANTALLAS` en `app/main.py`.
   Ya están reservadas `laboratorios`, `admin` y `equipo`.
3. Usa los tipos de `src/api.ts` (copian `app/esquemas.py`) y `api()` para llamar la API.
   Las rutas y sus roles están en `docs/api.md`.
4. Solo clases de `src/estilos.css` y piezas de `src/componentes.tsx`. Nada de
   `dangerouslySetInnerHTML`, ni tokens en `localStorage`.
