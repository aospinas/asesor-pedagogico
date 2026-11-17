import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ErrorApi, api, type EvaluacionResumen, type Laboratorio } from "../api";
import { Estado } from "../componentes";
import { ESTADO, MOTIVO, coma, fecha } from "../util";

export default function Bandeja() {
  const [lista, setLista] = useState<EvaluacionResumen[] | null>(null);
  const [labs, setLabs] = useState<Laboratorio[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api<EvaluacionResumen[]>("/api/evaluaciones"), api<Laboratorio[]>("/api/laboratorios")])
      .then(([evaluaciones, laboratorios]) => {
        setLista(evaluaciones);
        setLabs(laboratorios);
      })
      .catch((e) => setError(e instanceof ErrorApi ? e.message : "No se pudo cargar la bandeja."));
  }, []);

  if (!lista) return <Estado cargando={!error} error={error} />;
  const titulo = (id: string) => labs.find((l) => l.id === id)?.titulo ?? "Laboratorio";

  return (
    <>
      <h1>Bandeja de revisión</h1>
      <p className="secundario">Primero salen las que necesitan más atención. La IA propone; tú decides.</p>
      {lista.length === 0 ? (
        <p className="exito">No hay evaluaciones pendientes.</p>
      ) : (
        <div className="tabla-scroll">
          <table>
            <thead>
              <tr>
                <th>Laboratorio</th>
                <th>Estado</th>
                <th>Nota preliminar</th>
                <th>Revisar por</th>
                <th>Fecha</th>
                <th>
                  <span className="sr-only">Abrir</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {lista.map((e) => (
                <tr key={e.id}>
                  <td>{titulo(e.laboratorio_id)}</td>
                  <td>
                    <span className={`etiqueta${e.estado === "revision_manual" ? " alerta" : ""}`}>{ESTADO[e.estado]}</span>
                  </td>
                  <td>{coma(e.nota_preliminar)}</td>
                  <td>
                    {e.motivos.length === 0
                      ? "—"
                      : e.motivos.map((m) => (
                          <span key={m} className={`etiqueta ${m === "alerta_inyeccion" ? "rojo" : "alerta"}`} style={{ marginRight: 4 }}>
                            {MOTIVO[m]}
                          </span>
                        ))}
                  </td>
                  <td>{fecha(e.fecha)}</td>
                  <td>
                    <Link to={`/revision/${e.id}?laboratorio=${e.laboratorio_id}`}>Revisar</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
