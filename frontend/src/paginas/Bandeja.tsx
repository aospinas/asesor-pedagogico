import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

type Fila = {
  id: string;
  estado: string;
  nota_preliminar: number | null;
  motivos: string[];
  fecha: string;
};

const MOTIVOS: Record<string, string> = {
  cita_no_encontrada: "Hay una cita que no aparece en la entrega",
  alerta_inyeccion: "El texto intenta dar instrucciones a la IA",
  sin_propuesta: "A un criterio le falta el nivel",
  baja_coincidencia: "Dos corridas no coincidieron",
};

export default function Bandeja() {
  const [filas, setFilas] = useState<Fila[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Fila[]>("/api/evaluaciones")
      .then(setFilas)
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!filas) return <p>Cargando la bandeja…</p>;

  return (
    <>
      <h1>Por revisar</h1>
      <p className="secundario">Las que necesitan tu ojo van primero.</p>
      {filas.length === 0 && <p className="tarjeta">No hay evaluaciones pendientes.</p>}
      {filas.map((fila) => (
        <article className="tarjeta" key={fila.id}>
          <div className="fila">
            <strong>{fila.nota_preliminar ?? "—"}</strong>
            <span className="secundario">{fila.estado.replaceAll("_", " ")}</span>
            <Link to={`/revision/${fila.id}`}>Abrir</Link>
          </div>
          {fila.motivos.map((m) => (
            <p className="aviso" key={m}>
              {MOTIVOS[m] || m}
            </p>
          ))}
        </article>
      ))}
    </>
  );
}
