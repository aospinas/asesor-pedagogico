# Frontend

Interfaz en React (dirección Cordillera, `docs/diseno/decision.md`).

```powershell
cd frontend
npm install
npm run dev
```

Abre http://localhost:5173. La API tiene que estar en http://127.0.0.1:8000
(`uvicorn app.main:app --reload`). El dev server reenvía `/api` hacia allá.

`npm run build` deja los archivos en `frontend/dist`. Si esa carpeta existe,
la API los sirve en la misma dirección (así Render muestra la interfaz).
