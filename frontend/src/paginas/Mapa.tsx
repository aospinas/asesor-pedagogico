import { lazy, Suspense, useEffect, useState } from "react";
import { ErrorApi, api, type MapaMental } from "../api";
import { Estado, Nivel } from "../componentes";

// El grafo (y Cytoscape) se bajan solo al abrir esta pantalla.
const Grafo = lazy(() => import("../mapa/Grafo"));

export default function Mapa({ estudianteId }: { estudianteId: string }) {
  const [mapa, setMapa] = useState<MapaMental | null>(null);
  const [error, setError] = useState("");
  const [busqueda, setBusqueda] = useState("");
  const [nivel, setNivel] = useState("");

  useEffect(() => {
    api<MapaMental>(`/api/mapa/${estudianteId}`)
      .then(setMapa)
      .catch((e) => setError(e instanceof ErrorApi ? e.message : "No se pudo cargar el mapa."));
  }, [estudianteId]);

  if (!mapa) return <Estado cargando={!error} error={error} />;
  const temas = mapa.nodos.filter((n) => n.tipo === "tema");

  return (
    <>
      <h1>Mapa mental</h1>
      <p className="secundario">Cada tema queda a la altura de tu nivel: lo más alto es lo que mejor dominas.</p>
      {temas.length === 0 ? (
        <p className="aviso">El mapa aparece cuando tengas al menos una evaluación publicada.</p>
      ) : (
        <>
          <div className="fila">
            <label className="campo" style={{ margin: 0, flex: "1 1 220px" }}>
              Buscar tema
              <input type="search" value={busqueda} onChange={(e) => setBusqueda(e.target.value)} />
            </label>
            <label className="campo" style={{ margin: 0, flex: "0 1 220px" }}>
              Mostrar nivel
              <select value={nivel} onChange={(e) => setNivel(e.target.value)}>
                <option value="">Todos</option>
                <option>Alto</option>
                <option>Medio</option>
                <option>Básico</option>
                <option>Por fortalecer</option>
              </select>
            </label>
          </div>
          <Suspense fallback={<p className="secundario">Dibujando el mapa…</p>}>
            <Grafo mapa={mapa} busqueda={busqueda} nivel={nivel} />
          </Suspense>
          <h2>El mismo mapa en lista</h2>
          <ul>
            {temas.map((t) => (
              <li key={t.id}>
                {t.etiqueta} <Nivel nivel={t.nivel} />
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}
