import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";

type PublicadaDatos = {
  nota_final: number;
  criterios: {
    criterio_id: string;
    nivel_id: string;
    justificacion: string;
    fortalezas: string[];
    debilidades: string[];
    recomendaciones: string[];
  }[];
};

export default function Publicada() {
  const { id } = useParams();
  const [datos, setDatos] = useState<PublicadaDatos | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<PublicadaDatos>(`/api/evaluaciones/${id}/publicada`)
      .then(setDatos)
      .catch((e) => setError(e.message));
  }, [id]);

  if (error) return <p className="error">{error}</p>;
  if (!datos) return <p>Cargando…</p>;
  return (
    <>
      <h1>Nota publicada</h1>
      <p className="nota">{datos.nota_final.toFixed(1)}</p>
      {datos.criterios.map((c) => (
        <section className="tarjeta" key={c.criterio_id}>
          <h2>
            {c.criterio_id} · {c.nivel_id}
          </h2>
          <p>{c.justificacion}</p>
          <p>Fortalezas: {c.fortalezas.join(", ") || "—"}</p>
          <p>Por mejorar: {c.debilidades.join(", ") || "—"}</p>
          <p>Recomendaciones: {c.recomendaciones.join(", ") || "—"}</p>
        </section>
      ))}
    </>
  );
}
