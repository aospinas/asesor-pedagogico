import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// En el PC: `npm run dev` y la API con uvicorn en 127.0.0.1:8000 (no localhost: tarda 30 s).
// En producción la misma app de FastAPI sirve dist/ (D-23).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/salud": "http://127.0.0.1:8000",
    },
  },
  build: {
    sourcemap: false,
    // El mapa (Cytoscape) va en su propio pedazo: solo se baja en la pantalla del mapa.
    chunkSizeWarningLimit: 600,
  },
});
