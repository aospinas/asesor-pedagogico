import { useEffect, useState } from "react";
import { api } from "../api";
import Grafo from "../mapa/Grafo";

type MapaDatos = {
  nodos: {
    id: string;
    tipo: string;
    etiqueta: string;
    nivel: string | null;
    que_profundizar: string[];
    evidencias: { archivo: string; fragmento: string }[];
  }[];
  aristas: { origen: string; destino: string }[];
};

export default function Mapa({ estudianteId }: { estudianteId: string }) {
  const [mapa, setMapa] = useState<MapaDatos | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<MapaDatos>(`/api/mapa/${estudianteId}`)
      .then(setMapa)
      .catch((e) => setError(e.message));
  }, [estudianteId]);

  if (error) return <p className="error">{error}</p>;
  if (!mapa) return <p>Cargando el mapa…</p>;
  if (mapa.nodos.length === 0) return <p>Cuando haya notas publicadas, aquí aparece el mapa.</p>;
  return (
    <>
      <h1>Mapa de temas</h1>
      <p className="secundario">Arriba está lo que ya dominas. Toca un tema para ver evidencias.</p>
      <Grafo mapa={mapa} />
    </>
  );
}
