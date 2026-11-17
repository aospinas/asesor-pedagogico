import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

type Lab = {
  evaluacion_id: string;
  titulo: string;
  cohorte: string;
  nota_final: number;
  nivel: string;
};
type InformeDatos = {
  nombre_estudiante: string;
  promedio_general: number | null;
  laboratorios: Lab[];
  brechas: string[];
  plan: { resumen: string; acciones: { tema: string; que_hacer: string }[] } | null;
};

export default function Informe({ estudianteId }: { estudianteId: string }) {
  const [informe, setInforme] = useState<InformeDatos | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<InformeDatos>(`/api/informe/${estudianteId}`)
      .then(setInforme)
      .catch((e) => setError(e.message));
  }, [estudianteId]);

  if (error) return <p className="error">{error}</p>;
  if (!informe) return <p>Armando el informe…</p>;
  const notas = informe.laboratorios.map((l) => l.nota_final);
  const max = Math.max(5, ...notas, 1);

  return (
    <>
      <h1>Tu ascenso</h1>
      <p className="nota">{informe.promedio_general ?? "—"}</p>
      <p className="secundario">Promedio de lo que ya publicó el docente.</p>
      <svg className="perfil" viewBox="0 0 600 160" role="img" aria-label="Evolución de las notas">
        <polyline
          fill="none"
          stroke="#00b4d8"
          strokeWidth="3"
          points={informe.laboratorios
            .map((lab, i) => {
              const x = 40 + (i * 520) / Math.max(informe.laboratorios.length - 1, 1);
              const y = 140 - (lab.nota_final / max) * 110;
              return `${x},${y}`;
            })
            .join(" ")}
        />
      </svg>
      <table>
        <thead>
          <tr>
            <th>Cohorte</th>
            <th>Laboratorio</th>
            <th>Nota</th>
            <th>Dominio</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {informe.laboratorios.map((lab) => (
            <tr key={lab.evaluacion_id}>
              <td>{lab.cohorte}</td>
              <td>{lab.titulo}</td>
              <td>{lab.nota_final.toFixed(1)}</td>
              <td>{lab.nivel}</td>
              <td>
                <Link to={`/publicada/${lab.evaluacion_id}`}>Ver</Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {informe.laboratorios.length === 0 && <p>Todavía no hay notas publicadas.</p>}
      <h2>Qué reforzar</h2>
      <ul>
        {informe.brechas.length === 0 && <li>Nada marcado por ahora.</li>}
        {informe.brechas.map((b) => (
          <li key={b}>{b}</li>
        ))}
      </ul>
      {informe.plan && (
        <>
          <h2>Plan</h2>
          <p>{informe.plan.resumen}</p>
          <ul>
            {informe.plan.acciones.map((a) => (
              <li key={a.tema}>
                <strong>{a.tema}.</strong> {a.que_hacer}
              </li>
            ))}
          </ul>
        </>
      )}
      <p>
        <a className="boton" href={`/api/informe/${estudianteId}/pdf`}>
          Descargar PDF
        </a>
      </p>
    </>
  );
}
